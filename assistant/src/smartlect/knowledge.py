"""Versioned, prefiltered local RAG evidence; no commerce state or generated answers.

Adapted synonym normalization and RRF from frozen shop-ai-python, commit
94d36aee925c75d286f48d2aee2eeea059a74dd9, app/rag/query_expander.py and rrf.py.
Copyright (c) 2026 Audreator, MIT; see licenses/shop-ai-python-LICENSE.
Changes: fail-closed MySQL ACL/lifecycle, Chinese BM25, fixed RRF empty/duplicates.
"""
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import re
import threading
import time
import unicodedata
import uuid

from prometheus_client import Counter as PromCounter

import jieba

from smartlect.algo_version import content_hash
from smartlect.observability import gen_ai_span, prometheus_counter
from smartlect.cache import TtlCache
from smartlect.db import canonical
from smartlect.knowledge_scope import parse_product_ids, search_document_clause
from smartlect.state import SessionStore, StateError, _actor, _expiry, _integer, _json, _public, _text
from smartlect.tokenizer import encoding

KNOWLEDGE_CACHE_REQUESTS = prometheus_counter("growth_knowledge_cache_requests_total",
                                              "Knowledge search cache outcomes", ["outcome"])

MAX_CHUNKS = 5000
# Tokenizer tokens (tiktoken cl100k_base), not Python characters. 512 + ~10% overlap
# is the industry default this repo now ships; eval_chunk_window.py starts from 512.
CHUNK_WINDOW = 512
CHUNK_OVERLAP = 51
COMPOSED_QUERY_LIMIT = 800
CONSTRAINT_WEIGHT = 0.45
FIRST_STAGE_DEPTH = 50
FUSED_DEPTH = 24
FINAL_DEPTH = 8
# Vocabulary variants only: colloquial or misspelled wording for the same word. Intent
# phrases do not belong here, because mapping an action request onto a document lookup
# only works for the phrasings someone thought to list.
SYNONYMS = (("退钱", "退款"), ("退回款项", "退款"), ("付钱", "支付"), ("付款", "支付"),
            ("快递", "物流"), ("包裹", "物流"), ("收货地", "地址"), ("优惠卷", "优惠券"),
            ("清空", "清理"))
STOP_TERMS = {"什么", "怎么", "如何", "可以", "能否", "是否", "请问", "一下", "我的", "这个", "那个", "哪些", "多少"}
LEXICAL_VERSION = content_hash({
    "algo": "jieba_bm25",
    "synonyms": list(SYNONYMS),
    "stop_terms": sorted(STOP_TERMS),
})
RERANK_VERSION = content_hash({
    "algo": "vendor_rerank_or_rrf",
    "first_stage_depth": FIRST_STAGE_DEPTH,
    "fused_depth": FUSED_DEPTH,
    "final_depth": FINAL_DEPTH,
})
INSTRUCTION_PATTERN = re.compile(r"忽略.{0,12}(?:指令|规则|提示)|(?:系统|开发者)提示词|泄露.{0,10}(?:密钥|token)|"
                                 r"ignore.{0,25}(?:instruction|previous)|system\s*prompt|api[_ -]?key", re.I)
# 索引双写失败计数：静默失败曾让"已发布却检索不到"完全不可观测（2026-10-16 审计）
INDEX_MIRROR_FAILURES = PromCounter(
    "smartlect_knowledge_mirror_failures_total",
    "知识发布后向 ES/Qdrant 双写失败的次数（发布不阻塞，但检索侧可能缺该文档）",
)

VISIBLE_DOCUMENT = """d.execution_scope_id=%s AND d.status='PUBLISHED'
    AND d.valid_from<=UTC_TIMESTAMP(6) AND d.valid_until>UTC_TIMESTAMP(6)
    AND (d.acl='PUBLIC' OR (d.acl='USER' AND %s='user') OR (d.acl='MERCHANT' AND %s='merchant')
         OR (d.acl='ACTOR' AND %s='user' AND d.acl_actor_id=%s))"""
HIDDEN_DOCUMENT = """d.execution_scope_id=%s AND d.status='PUBLISHED'
    AND d.valid_from<=UTC_TIMESTAMP(6) AND d.valid_until>UTC_TIMESTAMP(6)
    AND NOT (d.acl='PUBLIC' OR (d.acl='USER' AND %s='user') OR (d.acl='MERCHANT' AND %s='merchant')
             OR (d.acl='ACTOR' AND %s='user' AND d.acl_actor_id=%s))"""


def _visibility(actor):
    kind, actor_id, scope = _actor(actor)
    return scope, kind, kind, kind, actor_id


def _merchant(actor, permission="admin:legacy"):
    if _actor(actor)[0] != "merchant":
        raise StateError("permission_denied", 403)
    perms = getattr(actor, "permissions", ())
    if permission == "admin:read":
        if "admin:legacy" not in perms and "admin:trial" not in perms:
            raise StateError("permission_denied", 403)
        return
    if permission not in perms:
        raise StateError("permission_denied", 403)


def _ids(value, name):
    if not isinstance(value, list) or len(value) > 64:
        raise StateError("invalid_" + name, 422)
    return sorted({_text(item, name, 128) for item in value})


def tokens(text):
    """jieba words. Single-character policy verbs such as 退/付 are kept; stop words drop."""
    value = unicodedata.normalize("NFKC", text).casefold()
    for source, target in SYNONYMS:
        value = value.replace(source, target)
    result = []
    for part in re.findall(r"[\u3400-\u9fff]+|[a-z0-9]+", value):
        if re.fullmatch(r"[a-z0-9]+", part):
            result.append(part)
            continue
        for word in jieba.cut(part, cut_all=False):
            word = word.strip()
            if not word or word in STOP_TERMS:
                continue
            result.append(word)
    return result


def _token_windows(text, window, overlap):
    """Split `text` into token windows; return (content, start_char, end_char) slices."""
    if not text:
        return []
    pieces = []
    enc = encoding()
    token_ids = enc.encode(text)
    if not token_ids:
        return []
    # Approximate char mapping: decode prefixes.
    prefixes = [0]
    acc = []
    for token_id in token_ids:
        acc.append(token_id)
        prefixes.append(len(enc.decode(acc)))
    start = 0
    while start < len(token_ids):
        stop = min(start + window, len(token_ids))
        char_start, char_end = prefixes[start], prefixes[stop]
        content = text[char_start:char_end]
        if content.strip():
            pieces.append((content, char_start, char_end))
        if stop >= len(token_ids):
            break
        nxt = stop - overlap
        start = nxt if nxt > start else start + 1
    return pieces


def split_document(body, *, window=CHUNK_WINDOW, overlap=CHUNK_OVERLAP):
    """Heading-first chunks in tokenizer tokens, with ~10% overlap and character offsets."""
    body = _text(body, "body", 300000)
    window = _integer(window, "chunk_window", 1, 300000)
    overlap = _integer(overlap, "chunk_overlap", 0, 299999)
    if overlap >= window:
        raise StateError("invalid_chunk_overlap", 422)
    chunks, start, heading = [], 0, ""
    boundaries = [match.start() for match in re.finditer(r"(?m)^#{1,6} +[^\n]+", body)]
    for end in sorted(set([*boundaries, len(body)])):
        if end <= start:
            continue
        section = body[start:end]
        first = re.match(r"#{1,6} +([^\n]+)", section)
        if first:
            heading = first.group(1)[:256]
        for content, rel_start, rel_end in _token_windows(section, window, overlap):
            offset = start + rel_start
            stop = start + rel_end
            chunks.append({"chunk_id": f"c{len(chunks) + 1:04d}", "heading": heading,
                           "content": content, "start_offset": offset, "end_offset": stop,
                           "start_line": body.count("\n", 0, offset) + 1,
                           "end_line": body.count("\n", 0, max(offset, stop - 1)) + 1,
                           "token_window": window, "token_overlap": overlap})
        start = end
    return chunks


def compose_search_query(utterance, model_query, *, limit=COMPOSED_QUERY_LIMIT):
    """原话为主（组件 3 收口）：用户原话就是提交检索词；模型改写只作附加变体。

    改写继续经 model_query 参数走 extra_queries 一路（rank_chunks 的内存 BM25
    与 ES 的 extra_queries），不再是主检索词——替换式改写让检索词脱离用户原话，
    改写漂移（丢约束词、混入臆测）只能靠事后守卫兜底；原话为主把锚点放在检索
    之前。无原话（空 utterance）回落改写，再回落空串。
    """
    original = (utterance or "").strip()
    rewrite = (model_query or "").strip()
    if original:
        return original[:limit]
    return rewrite[:limit]


def parallel_queries(utterance, model_query, *, limit=COMPOSED_QUERY_LIMIT):
    original = (utterance or "").strip()[:limit]
    rewrite = (model_query or "").strip()[:limit]
    queries = []
    if rewrite:
        queries.append(rewrite)
    if original and original != rewrite:
        queries.append(original)
    return queries or [""]


def constraint_terms(utterance, model_query):
    return set(tokens(utterance or "")) - set(tokens(model_query or ""))


def constraint_coverage(texts, extra_terms):
    if not extra_terms:
        return 1.0
    present = set(tokens(" ".join(texts)))
    return len(extra_terms & present) / len(extra_terms)


def citation_constraint_texts(items):
    return [((item.get('content') or '') + ' ' + (item.get('heading') or '') + ' ' + (item.get('title') or ''))
            for item in items or []]


def misses_utterance_constraints(items, utterance, model_query=''):
    extra = constraint_terms(utterance, model_query)
    if not extra:
        return False
    return constraint_coverage(citation_constraint_texts(items), extra) < 0.5


def hidden_document_covers(item, text):
    """True when the hidden passage covers the question, or the question names its title.

    2026-10-05：标题命中阈值从「标题词的50%出现在问句」降为「问句与标题
    共享任一显著词」。内部资料标题多为概括性短语（内部直播排期/内部毛利），
    问句口语化（你们最近有直播活动吗）——50% 标题覆盖几乎不可达，acl_denied
    因此永不浮现，内部资料存在的「让步即转人工」合同形同虚设（holdout-3
    sup-h3-04 根因）。tokens 已滤停用词，单词命中即有指向性；误报面由
    上层「仅浮出标题不浮出正文」+转人工兜底承接。
    """
    if not misses_utterance_constraints([item], text):
        return True
    question_terms = set(tokens(text))
    title_terms = set(tokens((item.get('title') or '') + ' ' + (item.get('heading') or '')))
    return bool(question_terms & title_terms)


def acl_denied_documents(visible_rows, hidden_rows, utterance, query=''):
    """Hidden published docs that cover the question, when visible leftovers do not.

    Titles only: the caller must not place hidden bodies in the model observation.
    """
    text = (utterance or query or '').strip()
    visible_items = [{'content': row.get('content') or '', 'heading': row.get('heading') or '',
                      'title': row.get('title') or ''} for row in visible_rows or []]
    if visible_rows and not misses_utterance_constraints(visible_items, text):
        return []
    grouped = {}
    for row in hidden_rows or []:
        doc_id = row.get('doc_id')
        if not doc_id:
            continue
        item = grouped.setdefault(doc_id, {'doc_id': doc_id, 'title': row.get('title') or '',
                                          'content': [], 'heading': [], 'acl': row.get('acl') or ''})
        if row.get('title'):
            item['title'] = row['title']
        item['content'].append(row.get('content') or '')
        item['heading'].append(row.get('heading') or '')
    hits = []
    for doc_id, item in grouped.items():
        packed = {'content': ' '.join(item['content']), 'heading': ' '.join(item['heading']),
                  'title': item['title']}
        if not hidden_document_covers(packed, text):
            continue
        # Evidence strength, not mere membership: the any-term title gate is
        # deliberately sensitive (colloquial paraphrases, holdout-3 sup-h3-04),
        # so bridging terms (e.g. 核对 shared by an unrelated internal doc) can
        # produce weak hits. Rank by content-constraint coverage first, then by
        # the number of question terms the title carries; surface only the
        # strongest evidence — the handoff contract needs the best-explaining
        # hidden doc, not every doc that shares one word.
        question_terms = set(tokens(text))
        title_terms = set(tokens((item['title'] or '') + ' ' + ' '.join(item['heading'])))
        score = (0 if misses_utterance_constraints([packed], text) else 1000) \
            + len(question_terms & title_terms)
        hits.append({'doc_id': doc_id, 'title': item['title'], 'acl': item['acl'], 'score': score})
    if not hits:
        return []
    best = max(hit['score'] for hit in hits)
    return [{key: hit[key] for key in ('doc_id', 'title', 'acl')}
            for hit in hits if hit['score'] == best]


def covering_span(sequence, terms):
    """Distinct query terms present, and the shortest token window that holds them all."""
    positions = [(index, token) for index, token in enumerate(sequence) if token in terms]
    distinct = {token for _, token in positions}
    if len(distinct) < 2:
        return len(distinct), None
    window, best, left = Counter(), None, 0
    for index, token in positions:
        window[token] += 1
        while len(window) == len(distinct):
            best = min(best or index + 1, index - positions[left][0] + 1)
            dropped = positions[left][1]
            window[dropped] -= 1
            if not window[dropped]:
                del window[dropped]
            left += 1
    return len(distinct), best


def apply_index_order(candidates, order_keys):
    """Keep fused/vendor order. Coverage formulas are not a rerank substitute."""
    by_key = {key: (key, 0.0) for key, _ in candidates}
    ranked = []
    seen = set()
    for key in order_keys:
        if key in by_key and key not in seen:
            ranked.append((key, 1.0 / (1 + len(ranked))))
            seen.add(key)
    for key, _ in candidates:
        if key not in seen:
            ranked.append((key, 0.0))
            seen.add(key)
    return ranked


def rrf_merge(keyword_ids, vector_ids, limit=FUSED_DEPTH):
    if limit <= 0:
        return []
    scores = {}
    for ranked in (keyword_ids, vector_ids):
        seen = set()
        for identifier in ranked:
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            scores[identifier] = scores.get(identifier, 0.0) + 1.0 / (60 + len(seen))
    return [key for key, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _vector(value, dimensions=None):
    if (not isinstance(value, list) or not 1 <= len(value) <= 4096
            or dimensions is not None and len(value) != dimensions
            or any(type(number) not in {int, float} or not math.isfinite(number) for number in value)):
        raise StateError("invalid_embedding_vector", 422)
    norm = math.hypot(*value)
    if not math.isfinite(norm) or norm == 0:
        raise StateError("invalid_embedding_vector", 422)
    return [number / norm for number in value]


def _bm25_rank(rows, query):
    terms = set(tokens(query))
    counters = [Counter(tokens(row["heading"] + " " + row["content"])) for row in rows]
    frequency = Counter(term for counter in counters for term in counter)
    average = sum(sum(counter.values()) for counter in counters) / max(len(rows), 1)
    lexical, by_key = [], {}
    for row, counter in zip(rows, counters):
        key = (row["doc_id"], row["version"], row["chunk_id"])
        by_key[key] = row
        length, score = sum(counter.values()), 0.0
        matched = terms & counter.keys()
        for term in matched:
            tf = counter[term]
            idf = math.log(1 + (len(rows) - frequency[term] + .5) / (frequency[term] + .5))
            score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * length / max(average, 1)))
        if matched:
            if len(terms) > 4 and len(matched) < 2:
                score *= .3
            lexical.append((key, score))
    lexical.sort(key=lambda item: (-item[1], item[0]))
    return lexical, by_key


def rank_chunks(rows, query, *, query_vector=None, embedding_model=None, index_version=None,
                utterance=None, model_query=None, dense_hits=None, vendor_order=None, es_hits=None,
                vector_backend="unavailable", rerank_backend="rrf_only"):
    """Lexical (ES BM25 preferred, in-memory jieba fallback) + ANN + RRF. No MySQL vector_json scan."""
    if len(rows) > MAX_CHUNKS:
        raise StateError("knowledge_capacity_exceeded", 503)
    lexical, by_key = _bm25_rank(rows, query)
    extra_queries = [item for item in (utterance, model_query) if item and item != query]
    for extra in extra_queries:
        extra_lex, extra_map = _bm25_rank(rows, extra)
        by_key.update(extra_map)
        lexical = extra_lex + [(key, score * 0.9) for key, score in lexical]
        lexical.sort(key=lambda item: (-item[1], item[0]))
    if es_hits:
        # ES 是服务端 BM25（IK 分词）；分数域与内存 BM25 不同，只取序参与 RRF。
        seen = set()
        ordered = []
        for key, _score in es_hits:
            if key in by_key and key not in seen:
                seen.add(key)
                ordered.append(key)
        if ordered:
            lexical = [(key, 1.0 / (index + 1)) for index, key in enumerate(ordered)] + [
                (key, score) for key, score in lexical if key not in seen]
    dense = []
    if dense_hits:
        for hit in dense_hits:
            key = (hit["doc_id"], hit["version"], hit["chunk_id"])
            if key in by_key:
                dense.append((key, hit.get("score") or 0.0))
        dense.sort(key=lambda item: (-item[1], item[0]))
    fused = rrf_merge([key for key, _ in lexical[:FIRST_STAGE_DEPTH]],
                      [key for key, _ in dense[:FIRST_STAGE_DEPTH]])
    order = vendor_order or fused
    reranked = apply_index_order([(key, by_key[key]) for key in fused if key in by_key], order)
    keys = [key for key, _ in reranked[:FINAL_DEPTH] if key in by_key]
    mode = "hybrid" if dense else "lexical"
    retrieval = {"mode": mode,
            "lexical_version": LEXICAL_VERSION, "embedding_model": embedding_model if dense else None,
            "index_version": index_version if dense else None,
            "dimensions": len(query_vector) if query_vector is not None else None,
            "eligible_chunks": len(rows), "lexical_matches": len(lexical), "dense_matches": len(dense),
            "dense_verified": bool(dense),
            "vector_backend": vector_backend if dense else "unused",
            "rerank_backend": rerank_backend,
            "rerank_version": RERANK_VERSION, "first_stage_depth": FIRST_STAGE_DEPTH,
            "fused_candidates": len(fused), "final_depth": FINAL_DEPTH,
            "fused_ranking": [list(key) for key in fused],
            "rerank_scores": [{"chunk": list(key), "score": round(score, 6)} for key, score in reranked]}
    if model_query is not None:
        retrieval["submitted_query"] = query
        retrieval["model_query"] = model_query
        retrieval["query_mode"] = "original_first_with_rewrite_variant"
    return [by_key[key] for key in keys], retrieval


def _mirror_index(scope, doc_id, version, model, index_version, mapped, chunks_meta=None):
    """索引双写：Qdrant 向量（有向量时）+ ES BM25 文档（始终按 chunks_meta 全量）。

    ES 侧不依赖向量——早先把它的写入放进「遍历向量」的循环里，没有 embedding
    key 的部署就永远索引不到知识：ES 为空、BM25 检索必然落空，客服只能答
    "没有资料"（2026-10-08 线上事故）。所以 ES 走全量切片、Qdrant 只写有向量的那份。
    任一失败不阻塞发布（审计已有 attempt 台账）。
    """
    try:
        import asyncio
        from smartlect import hybrid_search
        async def write_all():
            results = []
            if mapped:
                results.append(await hybrid_search.upsert_vectors(scope, doc_id, version, model, index_version, mapped))
            for chunk_id, meta in (chunks_meta or {}).items():
                results.append(await hybrid_search.index_chunk(
                    scope, doc_id, version, chunk_id, (meta or {}).get("heading"),
                    (meta or {}).get("content"), index_version=index_version))
            return results
        hybrid_search.run_sync(write_all())
    except Exception as error:
        # 静默吞掉的代价：任务报 DONE、台账全绿，但 ES/Qdrant 没有这份文档 →
        # "已发布却检索不到"，且无任何失败痕迹（2026-10-16 审计）。
        # 发布语义仍是"不阻塞"，但失败必须留痕：日志 + 指标 + 返回 False 由调用方记入元数据。
        INDEX_MIRROR_FAILURES.inc()
        log.warning("知识索引双写失败 scope=%s doc=%s v=%s：%s（发布继续，但检索侧可能缺该文档）",
                    scope, doc_id, version, error)
        return False
    return True


def mirror_failure_counter():
    """供索引任务读取（Prometheus Counter 的计数快照）。"""
    return INDEX_MIRROR_FAILURES._value.get()


class BackendHealth:
    """检索后端滑动窗口健康度（monitor→路由闭环的最小实现，ADR-0012）。

    连续失败达到阈值的后端在 retry_after 窗口内被主动跳过（走既有降级路径：
    ES→内存 BM25、Qdrant→纯词法、vendor rerank→RRF 序），窗口过后放行一次
    真实请求作为半开探测——成功即恢复。不是熔断器：无状态机、无额外探测调用，
    只是把「失败才回退」升级为「按健康度主动降权且跳过决策可追溯」。
    线程安全：_search_uncached 跑在 to_thread 工作线程，用一把小锁保护。
    """

    def __init__(self, window=8, failure_threshold=3, retry_after_seconds=60.0):
        self._lock = threading.Lock()
        self._window = window
        self._failure_threshold = failure_threshold
        self._retry_after = retry_after_seconds
        self._outcomes: dict[str, list] = {}
        self._skipped_at: dict[str, float] = {}

    def record(self, name, ok):
        with self._lock:
            outcomes = self._outcomes.setdefault(name, [])
            outcomes.append(bool(ok))
            if len(outcomes) > self._window:
                del outcomes[:len(outcomes) - self._window]
            if ok:
                self._skipped_at.pop(name, None)

    def should_skip(self, name, now=None):
        now = now if now is not None else time.monotonic()
        with self._lock:
            outcomes = self._outcomes.get(name) or []
            tail = outcomes[-self._failure_threshold:]
            if not (len(tail) == self._failure_threshold and not any(tail)):
                return False
            last_skip = self._skipped_at.get(name)
            if last_skip is None:
                return True  # 首次降级：开始跳过
            if now - last_skip < self._retry_after:
                return True  # 跳过窗口内
            # 窗口已过：放行一次真实请求探测（半开）。清除过期标记——若探测失败，
            # 下一次评估重新视为「首次降级」回到跳过态，避免探测风暴（每次请求都打故障后端）。
            self._skipped_at.pop(name, None)
            return False

    def note_skipped(self, name):
        # 只在没有活动标记时落时间戳：调用方每次跳过决策都会调本方法，
        # 若无条件刷新会让跳过窗口永不过期、后端永远得不到半开探测。
        now = time.monotonic()
        with self._lock:
            last = self._skipped_at.get(name)
            if last is None or now - last >= self._retry_after:
                self._skipped_at[name] = now

    def snapshot(self, names):
        with self._lock:
            report = {}
            for name in names:
                outcomes = self._outcomes.get(name) or []
                tail = outcomes[-self._failure_threshold:]
                degraded = (len(tail) == self._failure_threshold and not any(tail))
                report[name] = {
                    'recent_failures': len(outcomes) - sum(1 for item in outcomes if item),
                    'state': 'degraded' if degraded else 'ok',
                    'skipped': self._skipped_at.get(name) is not None,
                }
            return report


_BACKEND_HEALTH = BackendHealth()


def _recall_backends(scope, query_vector, embedding_model, index_version, query, utterance, model_query):
    """ES BM25 与 Qdrant ANN 并行召回（单次事件循环内 asyncio.gather）+ 健康度记录。

    运行在 to_thread 工作线程（无事件循环），asyncio.run 安全。健康后端并行把
    两路召回的墙钟时间从「相加」压到「取最大」；被降权的后端直接跳过不发请求。
    返回 ((dense_hits, vector_backend), (es_hits, es_backend), health_snapshot)。
    """
    import asyncio
    from smartlect import hybrid_search

    skip_ann = _BACKEND_HEALTH.should_skip('qdrant_ann')
    skip_es = _BACKEND_HEALTH.should_skip('es_bm25')
    if skip_ann:
        _BACKEND_HEALTH.note_skipped('qdrant_ann')
    if skip_es:
        _BACKEND_HEALTH.note_skipped('es_bm25')
    ann_usable = query_vector is not None and embedding_model and index_version

    async def ann():
        if not ann_usable:
            return [], "unused"
        if skip_ann:
            return [], "skipped_degraded"
        if hybrid_search.qdrant_client() is None:
            return [], "unavailable"  # 未配置是部署事实，不是健康事件
        try:
            hits, backend = await hybrid_search.ann_search(
                query_vector, scope, embedding_model, index_version, limit=FIRST_STAGE_DEPTH)
            _BACKEND_HEALTH.record('qdrant_ann', hits is not None)
            if hits is None:
                return [], "unavailable"
            return hits, backend
        except Exception:
            _BACKEND_HEALTH.record('qdrant_ann', False)
            return [], "unavailable"

    async def es_lexical():
        if skip_es:
            return None, "skipped_degraded"
        if hybrid_search.es_client() is None:
            return None, "unavailable"  # 未配置是部署事实，不是健康事件
        try:
            extras = [item for item in (utterance, model_query) if item and item != query]
            hits, backend = await hybrid_search.bm25_search(query, scope, extra_queries=extras)
            _BACKEND_HEALTH.record('es_bm25', hits is not None)
            if hits is None:
                return None, "unavailable"
            return hits, backend
        except Exception:
            _BACKEND_HEALTH.record('es_bm25', False)
            return None, "unavailable"

    async def _both():
        # gather 必须在协程内创建：Python 3.13 无运行循环时 gather 会先尝试
        # get_event_loop 绑定循环而失败。
        return await asyncio.gather(ann(), es_lexical())

    # 走检索专用循环：客户端绑定在那条循环上，跨循环复用会 "Event loop is closed"
    dense_pair, es_pair = hybrid_search.run_sync(_both())
    return dense_pair, es_pair, _BACKEND_HEALTH.snapshot(('es_bm25', 'qdrant_ann'))


def _vendor_rerank_order(query, rows, dense_hits):
    """Sync vendor call. Missing key or HTTP failure stays on RRF order."""
    from smartlect.rerank_client import configured
    if not configured() or not rows:
        return None, "rrf_only"
    if _BACKEND_HEALTH.should_skip('vendor_rerank'):
        _BACKEND_HEALTH.note_skipped('vendor_rerank')
        return None, "skipped_degraded"
    try:
        order_keys = _sync_vendor_keys(query, rows)
        _BACKEND_HEALTH.record('vendor_rerank', order_keys is not None)
        return order_keys, "vendor_http"
    except Exception:
        _BACKEND_HEALTH.record('vendor_rerank', False)
        return None, "rrf_fallback"


def _sync_vendor_keys(query, rows):
    import httpx
    from smartlect.rerank_client import RerankError
    env = __import__("os").environ
    key = (env.get("SMARTLECT_RERANK_API_KEY") or "").strip()
    if not key:
        raise RerankError("rerank_not_configured")
    base = (env.get("SMARTLECT_RERANK_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-api/v1").rstrip("/")
    model = env.get("SMARTLECT_RERANK_MODEL") or "gte-rerank-v2"
    documents = [(row.get("heading") or "") + "\n" + (row.get("content") or "") for row in rows[:FUSED_DEPTH]]
    body = {"model": model, "query": query, "documents": documents, "top_n": min(FINAL_DEPTH, len(documents))}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=15, trust_env=False) as client:
        response = client.post(f"{base}/reranks", json=body, headers=headers)
        if response.status_code >= 400:
            raise RerankError("rerank_http_error")
        payload = response.json()
    results = payload.get("results") or payload.get("output", {}).get("results") or []
    indexes = [int(item["index"]) for item in results if isinstance(item, dict) and "index" in item]
    keys = []
    for index in indexes:
        if 0 <= index < len(rows):
            row = rows[index]
            keys.append((row["doc_id"], row["version"], row["chunk_id"]))
    return keys or None


def evidence_result(rows, retrieval):
    # All retrieved text is data. A lexical warning cannot decide intent or authorize tools,
    # but it does decide admissibility: a passage carrying instructions that try to override
    # the rules is flagged per chunk, so the caller can keep it out of the citable set while
    # still knowing the document exists and what it is about.
    warned = sum(bool(INSTRUCTION_PATTERN.search(row['content'])) for row in rows)
    citations = [{**{name: row[name] for name in ("doc_id", "version", "chunk_id", "title", "source_uri", "checksum",
                 "heading", "content", "start_offset", "end_offset", "start_line", "end_line")},
                 "product_ids": parse_product_ids(row.get("product_ids_json")),
                 "source_type": row.get("source_type") or "MANUAL",
                 "carries_untrusted_instructions": bool(INSTRUCTION_PATTERN.search(row['content']))}
                 for row in rows[:4]]
    facts, conflicts = {}, set()
    for row in rows:
        values = row.get("facts_json", {})
        values = json.loads(values) if isinstance(values, (str, bytes)) else values
        for key, value in values.items():
            if key in facts and facts[key] != value:
                conflicts.add(key)
            facts[key] = value
    status = "conflicting" if conflicts else "answered" if citations else "insufficient"
    return {"answer_status": status, "citations": citations, "retrieval": retrieval,
            "conflict_keys": sorted(conflicts), "untrusted_instructions_detected": bool(warned),
            "source_trust": "untrusted_data",
            "requires_human": False,  # Retrieval cannot decide whether the task needs a human.
            "candidates": [{"doc_id": row["doc_id"], "version": row["version"], "chunk_id": row["chunk_id"]} for row in rows],
            "evidence_only": True}


class KnowledgeStore(SessionStore):
    def __init__(self, connect):
        super().__init__(connect)
        self._search_cache = TtlCache(256, 300)

    @staticmethod
    def _catalog(cursor, scope):
        cursor.execute("INSERT IGNORE INTO knowledge_catalog (execution_scope_id) VALUES (%s)", (scope,))
        cursor.execute("SELECT revision FROM knowledge_catalog WHERE execution_scope_id=%s FOR UPDATE", (scope,))
        return cursor.fetchone()["revision"]

    @staticmethod
    def _document(cursor, scope, doc_id, version):
        cursor.execute("SELECT * FROM knowledge_document WHERE execution_scope_id=%s AND doc_id=%s AND version=%s",
                       (scope, _text(doc_id, "doc_id", 128), _integer(version, "version", 1, 2147483647)))
        row = cursor.fetchone()
        if not row:
            raise StateError("document_not_found", 404)
        return row

    def create_draft(self, actor, payload):
        _merchant(actor)
        if not isinstance(payload, dict) or set(payload) - {"doc_id", "title", "source_uri", "body", "language", "acl",
                "acl_actor_id", "product_ids", "category_ids", "facts", "valid_from", "valid_until", "source_type"}:
            raise StateError("invalid_document", 422)
        source_type = payload.get("source_type", "MANUAL")
        if source_type not in {"MANUAL", "PRODUCT_AUTO"}:
            raise StateError("invalid_source_type", 422)
        scope = _actor(actor)[2]
        doc_id = _text(payload.get("doc_id", uuid.uuid4().hex), "doc_id", 128)
        title = _text(payload.get("title"), "title", 256)
        source_uri = _text(payload.get("source_uri"), "source_uri", 512)
        body = _text(payload.get("body"), "body", 300000)
        language = payload.get("language", "zh-CN")
        if language not in {"zh-CN", "en", "mixed"}:
            raise StateError("invalid_language", 422)
        acl = payload.get("acl")
        if acl not in {"PUBLIC", "USER", "MERCHANT", "ACTOR"}:
            raise StateError("invalid_acl", 422)
        acl_actor = _text(payload.get("acl_actor_id"), "acl_actor_id", 64) if acl == "ACTOR" else None
        if acl != "ACTOR" and payload.get("acl_actor_id") is not None:
            raise StateError("invalid_acl_actor_id", 422)
        start, end = _expiry(payload.get("valid_from")), _expiry(payload.get("valid_until"))
        if start >= end:
            raise StateError("invalid_validity_interval", 422)
        products = canonical(_ids(payload.get("product_ids", []), "product_ids"))
        # PRODUCT_AUTO must pin a product; empty product_ids can only be store policy.
        if source_type == "PRODUCT_AUTO" and not json.loads(products):
            raise StateError("product_knowledge_requires_product_id", 422)
        categories = canonical(_ids(payload.get("category_ids", []), "category_ids"))
        facts = _json(payload.get("facts", {}))
        parsed_facts = json.loads(facts)
        if len(parsed_facts) > 32 or any(not isinstance(k, str) or len(k) > 128 or
                not isinstance(v, str) or not v or len(v) > 256 or v not in body for k, v in parsed_facts.items()):
            raise StateError("facts_require_verbatim_evidence", 422)
        chunks = split_document(body)
        with self._transaction() as cursor:
            self._catalog(cursor, scope)
            cursor.execute("SELECT COALESCE(MAX(version),0)+1 AS version FROM knowledge_document WHERE execution_scope_id=%s AND doc_id=%s", (scope, doc_id))
            version = cursor.fetchone()["version"]
            prefix = sha256(canonical({"scope": scope, "doc_id": doc_id, "version": version}).encode()).hexdigest()[:16]
            chunks = [{**chunk, "chunk_id": prefix + "-" + chunk["chunk_id"]} for chunk in chunks]
            cursor.execute("""INSERT INTO knowledge_document (execution_scope_id,doc_id,version,title,source_uri,checksum,
                body,language,acl,acl_actor_id,product_ids_json,category_ids_json,facts_json,valid_from,valid_until,status,
                created_by,source_type,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'DRAFT',%s,%s,UTC_TIMESTAMP(6))""",
                (scope, doc_id, version, title, source_uri, sha256(body.encode()).hexdigest(), body, language, acl, acl_actor,
                 products, categories, facts, start, end, actor.actor_id, source_type))
            cursor.executemany("""INSERT INTO knowledge_chunk (execution_scope_id,doc_id,version,chunk_id,heading,content,
                start_offset,end_offset,start_line,end_line) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(scope, doc_id, version, *[chunk[key] for key in ("chunk_id", "heading", "content", "start_offset", "end_offset", "start_line", "end_line")]) for chunk in chunks])
            return _public(self._document(cursor, scope, doc_id, version))

    def publish(self, actor, doc_id, version):
        _merchant(actor)
        scope = _actor(actor)[2]
        with self._transaction() as cursor:
            self._catalog(cursor, scope)
            row = self._document(cursor, scope, doc_id, version)
            if row["status"] == "PUBLISHED":
                return _public(row)
            if row["status"] != "DRAFT":
                raise StateError("document_not_draft")
            cursor.execute("SELECT UTC_TIMESTAMP(6) AS now")
            if row["valid_until"] <= cursor.fetchone()["now"]:
                raise StateError("document_expired")
            cursor.execute("""SELECT COUNT(*) AS count FROM knowledge_chunk c JOIN knowledge_document d
                USING(execution_scope_id,doc_id,version) WHERE d.execution_scope_id=%s AND
                ((d.status='PUBLISHED' AND d.doc_id<>%s) OR (d.doc_id=%s AND d.version=%s))""", (scope, doc_id, doc_id, version))
            if cursor.fetchone()["count"] > MAX_CHUNKS:
                raise StateError("knowledge_capacity_exceeded", 422)
            cursor.execute("UPDATE knowledge_document SET status='WITHDRAWN',withdrawn_at=UTC_TIMESTAMP(6) "
                           "WHERE execution_scope_id=%s AND doc_id=%s AND status='PUBLISHED'", (scope, doc_id))
            cursor.execute("UPDATE knowledge_document SET status='PUBLISHED',published_at=UTC_TIMESTAMP(6) "
                           "WHERE execution_scope_id=%s AND doc_id=%s AND version=%s", (scope, doc_id, version))
            cursor.execute("UPDATE knowledge_catalog SET revision=revision+1 WHERE execution_scope_id=%s", (scope,))
            return _public(self._document(cursor, scope, doc_id, version))

    def withdraw(self, actor, doc_id, version):
        _merchant(actor)
        scope = _actor(actor)[2]
        with self._transaction() as cursor:
            self._catalog(cursor, scope)
            self._document(cursor, scope, doc_id, version)
            cursor.execute("UPDATE knowledge_document SET status='WITHDRAWN',withdrawn_at=UTC_TIMESTAMP(6) "
                           "WHERE execution_scope_id=%s AND doc_id=%s AND version=%s AND status<>'WITHDRAWN'", (scope, doc_id, version))
            if cursor.rowcount:
                cursor.execute("UPDATE knowledge_catalog SET revision=revision+1 WHERE execution_scope_id=%s", (scope,))
            withdrawn = _public(self._document(cursor, scope, doc_id, version))
        # 撤回是权威事实（MySQL 状态机 + 检索谓词双保险），索引清理属"尽力而为的卫生工作"：
        # 失败只记日志，不影响撤回结论（delete_doc 此前无调用方，残留旧版本长期占索引）
        try:
            from smartlect import hybrid_search
            hybrid_search.run_sync(hybrid_search.delete_doc(scope, doc_id, version))
        except Exception as error:  # noqa: BLE001
            log.warning("撤回后清理检索索引失败 scope=%s doc=%s v=%s：%s", scope, doc_id, version, error)
        return withdrawn

    def latest_product_auto(self, actor, doc_id):
        _merchant(actor, "admin:read")
        with self._transaction() as cursor:
            cursor.execute("""SELECT doc_id,version,status,checksum,source_type FROM knowledge_document
                WHERE execution_scope_id=%s AND doc_id=%s AND source_type='PRODUCT_AUTO'
                ORDER BY version DESC LIMIT 8""",
                           (_actor(actor)[2], _text(doc_id, "doc_id", 128)))
            return [_public(row) for row in cursor.fetchall()]

    def discard_auto_drafts(self, actor, doc_ids, *, source_type="PRODUCT_AUTO"):
        """Overlay semantics for auto imports: re-importing replaces the previous auto DRAFT
        (chunks included) and never touches MANUAL documents or anything already published."""
        _merchant(actor)
        ids = [_text(item, "doc_id", 128) for item in doc_ids]
        if not ids:
            return {"discarded": 0}
        with self._transaction() as cursor:
            placeholders = ",".join(["%s"] * len(ids))
            cursor.execute(f"""SELECT doc_id,version FROM knowledge_document
                WHERE execution_scope_id=%s AND source_type=%s AND status='DRAFT' AND doc_id IN ({placeholders})""",
                (_actor(actor)[2], source_type, *ids))
            rows = cursor.fetchall()
            for row in rows:
                cursor.execute("DELETE FROM knowledge_chunk WHERE execution_scope_id=%s AND doc_id=%s AND version=%s",
                               (_actor(actor)[2], row["doc_id"], row["version"]))
                cursor.execute("DELETE FROM knowledge_document WHERE execution_scope_id=%s AND doc_id=%s AND version=%s",
                               (_actor(actor)[2], row["doc_id"], row["version"]))
        return {"discarded": len(rows)}

    def list_documents(self, actor):
        _merchant(actor, "admin:read")
        with self._transaction() as cursor:
            cursor.execute("SELECT doc_id,version,title,status,acl,valid_from,valid_until,checksum,published_at,source_type "
                           "FROM knowledge_document WHERE execution_scope_id=%s ORDER BY doc_id,version DESC LIMIT 1000", (_actor(actor)[2],))
            return [_public(row) for row in cursor.fetchall()]

    def document_versions(self, actor, doc_id):
        _merchant(actor, "admin:read")
        with self._transaction() as cursor:
            cursor.execute("SELECT doc_id,version,status,source_type,created_at FROM knowledge_document "
                "WHERE execution_scope_id=%s AND doc_id=%s ORDER BY version DESC LIMIT 50",
                (_actor(actor)[2], _text(doc_id, "doc_id", 128)))
            return [_public(row) for row in cursor.fetchall()]

    def get_document(self, actor, doc_id, version):
        _merchant(actor, "admin:read")
        with self._transaction() as cursor:
            return _public(self._document(cursor, _actor(actor)[2], doc_id, version))

    def read_published_document(self, actor, doc_id, version):
        kind, _, _ = _actor(actor)
        if "shopping:read" not in getattr(actor, "permissions", ()) and kind != "merchant":
            raise StateError("permission_denied", 403)
        doc_id, version = _text(doc_id, "doc_id", 128), _integer(version, "version", 1, 2147483647)
        with self._transaction() as cursor:
            cursor.execute("SELECT d.doc_id,d.version,d.title,d.source_uri,d.body,d.checksum,d.language "
                           "FROM knowledge_document d WHERE " + VISIBLE_DOCUMENT + " AND d.doc_id=%s AND d.version=%s",
                           (*_visibility(actor), doc_id, version))
            row = cursor.fetchone()
            if not row:
                raise StateError("document_not_found", 404)
            return _public(row)

    def draft_chunks(self, actor, doc_id, version):
        _merchant(actor)
        with self._transaction() as cursor:
            self._document(cursor, _actor(actor)[2], doc_id, version)
            cursor.execute("SELECT chunk_id,heading,content FROM knowledge_chunk WHERE execution_scope_id=%s AND doc_id=%s AND version=%s ORDER BY chunk_id", (_actor(actor)[2], doc_id, version))
            return list(cursor.fetchall())

    def set_embeddings(self, actor, doc_id, version, *, model, index_version, vectors):
        _merchant(actor)
        model, index_version = _text(model, "embedding_model", 128), _text(index_version, "index_version", 128)
        if not isinstance(vectors, list) or not vectors or len(vectors) > MAX_CHUNKS:
            raise StateError("invalid_embeddings", 422)
        mapped, dimensions = {}, None
        for item in vectors:
            if not isinstance(item, dict) or set(item) != {"chunk_id", "vector"}:
                raise StateError("invalid_embeddings", 422)
            key = _text(item["chunk_id"], "chunk_id", 32)
            vector = _vector(item["vector"], dimensions)
            if key in mapped:
                raise StateError("duplicate_embedding_chunk", 422)
            mapped[key], dimensions = vector, len(vector)
        scope = _actor(actor)[2]
        with self._transaction() as cursor:
            cursor.execute("SELECT chunk_id,heading,content FROM knowledge_chunk WHERE execution_scope_id=%s AND doc_id=%s AND version=%s",
                           (scope, doc_id, version))
            chunks_meta = {row["chunk_id"]: {"heading": row["heading"], "content": row["content"]}
                           for row in cursor.fetchall()}
            self._catalog(cursor, scope)
            row = self._document(cursor, scope, doc_id, version)
            if row["status"] != "DRAFT":
                raise StateError("document_not_draft")
            cursor.execute("SELECT chunk_id FROM knowledge_chunk WHERE execution_scope_id=%s AND doc_id=%s AND version=%s", (scope, doc_id, version))
            if {row["chunk_id"] for row in cursor.fetchall()} != mapped.keys():
                raise StateError("incomplete_embeddings", 422)
            cursor.executemany("UPDATE knowledge_chunk SET embedding_model=%s,embedding_dimensions=%s,index_version=%s,vector_json=%s "
                "WHERE execution_scope_id=%s AND doc_id=%s AND version=%s AND chunk_id=%s",
                [(model, dimensions, index_version, canonical(vector), scope, doc_id, version, key) for key, vector in mapped.items()])
        _mirror_index(scope, doc_id, version, model, index_version, mapped, chunks_meta=chunks_meta)
        return {"model": model, "index_version": index_version, "dimensions": dimensions, "chunks": len(mapped)}

    def draft_chunks_with_status(self, actor, doc_id, version):
        """draft_chunks plus an embedded flag, so an index job can resume and skip done chunks."""
        _merchant(actor)
        with self._transaction() as cursor:
            self._document(cursor, _actor(actor)[2], doc_id, version)
            cursor.execute("SELECT chunk_id,heading,content,(vector_json IS NOT NULL) AS embedded FROM knowledge_chunk "
                "WHERE execution_scope_id=%s AND doc_id=%s AND version=%s ORDER BY chunk_id",
                (_actor(actor)[2], doc_id, version))
            return [dict(row) for row in cursor.fetchall()]

    def embed_batch(self, actor, doc_id, version, *, model, index_version, vectors,
                    allow_published=False):
        """Batch-wise vector write for the async index pipeline: same validation as
        set_embeddings but without the all-chunks-at-once completeness check, so a job can
        persist progress batch by batch and a resumed job only re-embeds missing chunks.

        allow_published=True 用于「给已发布文档补向量」的旁路（rebuild_vectors）——
        那些文档没走发布流程就直接写了库，状态是 PUBLISHED 而非 DRAFT，本校验会把
        它们挡在外面。旁路不放宽 chunk 归属校验，仅跳过状态门槛。
        """
        _merchant(actor)
        model, index_version = _text(model, "embedding_model", 128), _text(index_version, "index_version", 128)
        if not isinstance(vectors, list) or not vectors:
            raise StateError("invalid_embeddings", 422)
        mapped, dimensions = {}, None
        for item in vectors:
            if not isinstance(item, dict) or set(item) != {"chunk_id", "vector"}:
                raise StateError("invalid_embeddings", 422)
            key = _text(item["chunk_id"], "chunk_id", 32)
            vector = _vector(item["vector"], dimensions)
            if key in mapped:
                raise StateError("duplicate_embedding_chunk", 422)
            mapped[key], dimensions = vector, len(vector)
        scope = _actor(actor)[2]
        with self._transaction() as cursor:
            cursor.execute("SELECT chunk_id,heading,content FROM knowledge_chunk WHERE execution_scope_id=%s AND doc_id=%s AND version=%s",
                           (scope, doc_id, version))
            _rows_meta = cursor.fetchall()
            chunks_meta = {row["chunk_id"]: {"heading": row["heading"], "content": row["content"]}
                           for row in _rows_meta}
            row = self._document(cursor, scope, doc_id, version)
            if row["status"] != "DRAFT" and not allow_published:
                raise StateError("document_not_draft")
            known = {item["chunk_id"] for item in _rows_meta}
            if not set(mapped) <= known:
                raise StateError("unknown_embedding_chunk", 422)
            cursor.executemany("UPDATE knowledge_chunk SET embedding_model=%s,embedding_dimensions=%s,index_version=%s,vector_json=%s "
                "WHERE execution_scope_id=%s AND doc_id=%s AND version=%s AND chunk_id=%s",
                [(model, dimensions, index_version, canonical(vector), scope, doc_id, version, key)
                 for key, vector in mapped.items()])
        _mirror_index(scope, doc_id, version, model, index_version, mapped, chunks_meta=chunks_meta)
        return {"chunks": len(mapped), "model": model, "index_version": index_version}

    def embedding_counts(self, actor, doc_id, version):
        _merchant(actor)
        with self._transaction() as cursor:
            self._document(cursor, _actor(actor)[2], doc_id, version)
            cursor.execute("SELECT COUNT(*) AS total,COALESCE(SUM(vector_json IS NOT NULL),0) AS embedded "
                "FROM knowledge_chunk WHERE execution_scope_id=%s AND doc_id=%s AND version=%s",
                (_actor(actor)[2], doc_id, version))
            row = cursor.fetchone()
            return {"total": row["total"], "embedded": row["embedded"]}

    def search(self, actor, query, *, query_vector=None, embedding_model=None, index_version=None,
               product_id=None, category_id=None, utterance=None, model_query=None, corpus=None):
        kind, actor_id, scope = _actor(actor)
        raw_query = _text(query, "query", 1000)
        query = compose_search_query(utterance, model_query or raw_query)
        if "shopping:read" not in getattr(actor, "permissions", ()) and kind != "merchant":
            raise StateError("permission_denied", 403)
        filters, values = search_document_clause(product_id=product_id, category_id=category_id, corpus=corpus)
        with self._transaction() as cursor:
            cursor.execute("SELECT revision FROM knowledge_catalog WHERE execution_scope_id=%s", (scope,))
            catalog = cursor.fetchone()
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
        revision = catalog["revision"] if catalog else 0
        vector_key = (sha256(canonical(query_vector).encode()).hexdigest()
                      if isinstance(query_vector, list) else None)
        # ACL + valid_until belong in the key; a publish bump is not enough if the same
        # revision later hides a document by expiry.
        cache_key = (scope, kind, actor_id, query, vector_key, embedding_model, index_version,
                     product_id, category_id, corpus, utterance, model_query, revision, now[:16])
        cached = self._search_cache.get(cache_key)
        with gen_ai_span(
            "retrieve knowledge",
            kind="retrieve",
            attributes={
                "gen_ai.operation.name": "retrieve",
                "gen_ai.retrieval.name": "knowledge",
            },
        ) as span:
            if cached is not None:
                KNOWLEDGE_CACHE_REQUESTS.labels("hit").inc()
                if span is not None:
                    span.set_attribute("smartlect.cache_hit", True)
                return json.loads(cached)
            KNOWLEDGE_CACHE_REQUESTS.labels("miss").inc()
            return self._search_uncached(
                actor, query, raw_query=raw_query, query_vector=query_vector,
                embedding_model=embedding_model, index_version=index_version,
                utterance=utterance, model_query=model_query, filters=filters,
                values=values, cache_key=cache_key, span=span)

    def _search_uncached(self, actor, query, *, raw_query, query_vector, embedding_model,
                         index_version, utterance, model_query, filters, values, cache_key, span):
        _kind, _actor_id, scope = _actor(actor)
        with self._transaction() as cursor:
            cursor.execute("""SELECT c.doc_id,c.version,c.chunk_id,c.heading,c.content,c.start_offset,c.end_offset,
                c.start_line,c.end_line,d.title,d.source_uri,d.checksum,d.facts_json,d.product_ids_json,d.source_type,
                d.acl,d.valid_until
                FROM knowledge_document d
                JOIN knowledge_chunk c USING(execution_scope_id,doc_id,version)
                WHERE """ + VISIBLE_DOCUMENT + " " + filters +
                " ORDER BY d.doc_id,d.version,c.chunk_id LIMIT 5001", (*_visibility(actor), *values))
            rows = list(cursor.fetchall())
            cursor.execute("""SELECT c.content,c.heading,d.doc_id,d.title,d.acl FROM knowledge_document d
                JOIN knowledge_chunk c USING(execution_scope_id,doc_id,version)
                WHERE """ + HIDDEN_DOCUMENT + " " + filters +
                " ORDER BY d.doc_id,d.version,c.chunk_id LIMIT 5001", (*_visibility(actor), *values))
            hidden_rows = list(cursor.fetchall())
            cursor.execute("SELECT revision FROM knowledge_catalog WHERE execution_scope_id=%s", (scope,))
            catalog = cursor.fetchone()
        (dense_hits, vector_backend), (es_hits, es_backend), backend_health = _recall_backends(
            scope, query_vector, embedding_model, index_version, query, utterance, model_query)
        vendor_order, rerank_backend = _vendor_rerank_order(query, rows, dense_hits)
        backend_health.update(_BACKEND_HEALTH.snapshot(('vendor_rerank',)))
        ranked, metadata = rank_chunks(
            rows, query, query_vector=query_vector, embedding_model=embedding_model,
            index_version=index_version, utterance=utterance, model_query=model_query,
            dense_hits=dense_hits, vendor_order=vendor_order, es_hits=es_hits,
            vector_backend=vector_backend, rerank_backend=rerank_backend)
        metadata["lexical_backend"] = es_backend
        metadata["backend_health"] = backend_health
        metadata["catalog_revision"] = catalog["revision"] if catalog else 0
        metadata["parallel_queries"] = parallel_queries(utterance, model_query or raw_query)
        denied = acl_denied_documents(rows, hidden_rows, utterance, query)
        metadata["acl_denied"] = denied
        result = evidence_result(ranked, metadata)
        result["acl_denied"] = denied
        if span is not None:
            span.set_attribute("smartlect.cache_hit", False)
            if metadata.get("eligible_chunks") is not None:
                span.set_attribute("smartlect.eligible_chunks", metadata["eligible_chunks"])
            span.set_attribute("gen_ai.retrieval.document.count", len(ranked))
        self._search_cache.put(cache_key, canonical(result))
        return result

    def validate_citations(self, actor, citations):
        """Recheck fresh publication, ACL and expiry immediately before answering.

        Historical answers retain their recorded version; this gate is for new answers.
        """
        _actor(actor)
        if not isinstance(citations, list) or not 1 <= len(citations) <= 4:
            return False
        with self._transaction() as cursor:
            return self._validate_citations(cursor, actor, citations)

    @staticmethod
    def _validate_citations(cursor, actor, citations):
        if not isinstance(citations, list) or not 1 <= len(citations) <= 4:
            return False
        for citation in citations:
            if not isinstance(citation, dict):
                return False
            try:
                doc_id = _text(citation.get("doc_id"), "doc_id", 128)
                version = _integer(citation.get("version"), "version", 1, 2147483647)
                chunk_id = _text(citation.get("chunk_id"), "chunk_id", 32)
            except StateError:
                return False
            # Current locking read: a prior query in the caller's REPEATABLE READ
            # transaction must not resurrect a document withdrawn before this check.
            cursor.execute("""SELECT c.content,c.start_offset,c.end_offset,c.start_line,c.end_line,d.checksum
                FROM knowledge_document d JOIN knowledge_chunk c USING(execution_scope_id,doc_id,version)
                WHERE """ + VISIBLE_DOCUMENT + " AND d.doc_id=%s AND d.version=%s AND c.chunk_id=%s FOR SHARE",
                (*_visibility(actor), doc_id, version, chunk_id))
            row = cursor.fetchone()
            if (not row or any(name in citation and citation[name] != value for name, value in row.items())
                    or "text" in citation and citation["text"] != row["content"]):
                return False
        return True
