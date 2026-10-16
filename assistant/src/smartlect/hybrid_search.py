"""混合检索后端：Elasticsearch(BM25, IK 分词) + Qdrant(dense ANN)。

2026-10 收敛重构：取代自研 jieba 内存 BM25 与 pgvector 双写。两个后端都懒加载，
未配置或不可达时返回各自的 unavailable 信号——调用方沿用既有降级链
（单路可检索、双缺失退 lexical-only/503），不把基础设施可用性耦合进检索语义。

环境变量：
  SMARTLECT_ES_URL / SMARTLECT_ES_API_KEY（可选）
  SMARTLECT_QDRANT_URL / SMARTLECT_QDRANT_API_KEY（可选，缺省本地 127.0.0.1:6333）
"""
import asyncio
import logging
import os
import threading

log = logging.getLogger(__name__)

ES_INDEX = "smartlect-knowledge"
QDRANT_COLLECTION = "smartlect_knowledge"
FIRST_STAGE = 50

_es = None
_qdrant = None

# 检索专用事件循环。
#
# 为什么需要它（2026-10-16 审计实测）：ES/Qdrant 的异步客户端在**创建时**绑定当时的
# 事件循环；而检索路径跑在 `asyncio.to_thread` 工作线程里（每次都新建循环）。此前
# 客户端在 lifespan 的主循环里创建、在工作线程的循环里复用，实测直接抛
# `RuntimeError: Event loop is closed` → 每个后端都被记成失败 → 健康度连续失败后
# 进入跳过窗口，60s 半开探测同样失败 → **检索平面永久退化为内存 BM25**，而日志/指标不体现。
#
# 现在把两个客户端固定在一条常驻循环上，所有检索协程经 run_sync 提交过去执行：
# 客户端永远只在一个循环里被使用，且连接可复用。
_retrieval_loop = None
_retrieval_loop_lock = threading.Lock()


def _retrieval_loop_or_create():
    global _retrieval_loop
    with _retrieval_loop_lock:
        if _retrieval_loop is None or _retrieval_loop.is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, name="smartlect-retrieval", daemon=True)
            thread.start()
            _retrieval_loop = loop
        return _retrieval_loop


def run_sync(coro):
    """在检索专用循环上执行协程并等待结果（检索路径的唯一入口）。"""
    loop = _retrieval_loop_or_create()
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


def _env(name, default=None):
    value = os.getenv(name)
    return value if value else default


def es_client():
    """单例 AsyncElasticsearch；未配置返回 None。"""
    global _es
    if _es is not None:
        return _es
    url = _env("SMARTLECT_ES_URL")
    if not url:
        return None
    from elasticsearch import AsyncElasticsearch
    kwargs = {"request_timeout": 10}
    api_key = _env("SMARTLECT_ES_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
    _es = AsyncElasticsearch(url, **kwargs)
    return _es


def qdrant_client():
    """单例 AsyncQdrantClient；未配置返回 None（本地默认端口）。"""
    global _qdrant
    if _qdrant is not None:
        return _qdrant
    from qdrant_client import AsyncQdrantClient
    url = _env("SMARTLECT_QDRANT_URL", "http://127.0.0.1:6333")
    kwargs = {"url": url, "timeout": 10}
    api_key = _env("SMARTLECT_QDRANT_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
    _qdrant = AsyncQdrantClient(**kwargs)
    return _qdrant


# 中文默认分析器的候选：ik_max_word 最细粒度切分（IK 插件随自建镜像预装，
# 支持自定义词典，国内电商搜索主流）；smartcn/cjk 作为未装 IK 时的回退，
# cjk 是 ES 内置的中日韩 bigram 分析器。逐个探测而不是写死，避免在没装
# 对应插件的 ES 上让建索引直接 400、索引只能由 dynamic mapping 兜底、
# 中文按 standard 切分（2026-10-08 线上就是这个后果）。
ANALYZER_CANDIDATES = ("ik_max_word", "smartcn", "cjk")


async def _default_analyzer(es):
    """挑一个当前 ES 真正支持的默认分析器；都不支持时返回 None，交给内置 standard。"""
    for kind in ANALYZER_CANDIDATES:
        try:
            await es.indices.analyze(analyzer=kind, text="中文分词探测")
            return kind
        except Exception:
            continue
    return None


async def ensure_schema():
    """幂等建索引/集合；任一后端缺失时跳过对应部分。

    在检索专用循环上执行（见模块头注释）：客户端一旦创建就固定在那条循环上，
    避免"主循环创建、工作线程使用"的跨循环错误。
    """
    return await asyncio.wrap_future(
        asyncio.run_coroutine_threadsafe(_ensure_schema_impl(), _retrieval_loop_or_create()))


async def _ensure_schema_impl():
    es = es_client()
    if es is not None:
        if not await es.indices.exists(index=ES_INDEX):
            settings = {"number_of_shards": 1, "number_of_replicas": 0}
            analyzer = await _default_analyzer(es)
            if analyzer:
                settings["analysis"] = {"analyzer": {"default": {"type": analyzer}}}
            await es.indices.create(index=ES_INDEX, body={
                "settings": settings,
                "mappings": {
                    "properties": {
                        "scope": {"type": "keyword"},
                        "doc_id": {"type": "keyword"},
                        "version": {"type": "long"},
                        "chunk_id": {"type": "keyword"},
                        "index_version": {"type": "keyword"},
                        "heading": {"type": "text"},
                        "content": {"type": "text"},
                        "valid_until": {"type": "date", "format": "strict_date_optional_time||epoch_millis||yyyy-MM-dd HH:mm:ss||yyyy-MM-dd'T'HH:mm:ssZ||yyyy-MM-dd'T'HH:mm:ss.SSSSSS'Z'"},
                    }
                },
            })
    qdrant = qdrant_client()
    if qdrant is not None:
        from qdrant_client import models
        if not await qdrant.collection_exists(QDRANT_COLLECTION):
            await qdrant.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=models.VectorParams(size=1024, distance=models.Distance.COSINE),
            )


def es_doc_id(scope, doc_id, version, chunk_id):
    return f"{scope}:{doc_id}:{version}:{chunk_id}"


async def index_chunk(scope, doc_id, version, chunk_id, heading, content,
                      index_version=None, valid_until=None):
    """写一条 ES 文档；失败返回 False（调用方按既有审计口径记录）。"""
    es = es_client()
    if es is None:
        return False
    body = {"scope": scope, "doc_id": doc_id, "version": int(version),
            "chunk_id": chunk_id, "heading": heading or "", "content": content}
    if index_version:
        body["index_version"] = str(index_version)
    if valid_until:
        body["valid_until"] = str(valid_until)
    await es.index(index=ES_INDEX, id=es_doc_id(scope, doc_id, version, chunk_id),
                   document=body, refresh="wait_for")
    return True


async def delete_doc(scope, doc_id, version=None):
    """撤回文档：按 (scope, doc_id[, version]) 删除 ES 文档。"""
    es = es_client()
    if es is None:
        return False
    query = {"bool": {"filter": [{"term": {"scope": scope}}, {"term": {"doc_id": doc_id}}]}}
    if version is not None:
        query["bool"]["filter"].append({"term": {"version": int(version)}})
    await es.delete_by_query(index=ES_INDEX, query=query, refresh=True,
                             conflicts="proceed")
    return True


async def bm25_search(query, scope, limit=FIRST_STAGE, *, extra_queries=()):
    """ES BM25 top-limit。返回 [(key, score)]，key=(doc_id, version, chunk_id)。
    未配置/不可达返回 (None, 'unavailable')——调用方回退单路。"""
    es = es_client()
    if es is None or not (query or extra_queries):
        return None, "unavailable"
    should = []
    for text in [query, *[q for q in extra_queries if q]]:
        should.append({"multi_match": {"query": text, "fields": ["heading^2", "content"], "operator": "or"}})
    body = {"bool": {"filter": [{"term": {"scope": scope}}], "should": should, "minimum_should_match": 1}}
    response = await es.search(index=ES_INDEX, query=body, size=limit, _source=["doc_id", "version", "chunk_id"])
    hits = []
    for hit in response["hits"]["hits"]:
        source = hit["_source"]
        hits.append(((source["doc_id"], int(source["version"]), source["chunk_id"]), float(hit["_score"] or 0.0)))
    return hits, "es_bm25"


def qdrant_point_id(scope, doc_id, version, chunk_id):
    """Qdrant point id 必须是 UUID 或无符号整数，不能直接用 es_doc_id 那种
    'scope:doc_id:version:chunk_id' 字符串。用 UUID5 从同一字符串确定性派生：
    同一切片总是同一个点（幂等 upsert），且 payload 里保留完整标识用于回查。"""
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"smartlect:{scope}:{doc_id}:{version}:{chunk_id}"))


async def upsert_vectors(scope, doc_id, version, model, index_version, mapped):
    """Qdrant 批量 upsert（mapped: chunk_id -> vector）。失败返回 False。"""
    qdrant = qdrant_client()
    if qdrant is None or not mapped:
        return False
    from qdrant_client import models
    points = [
        models.PointStruct(
            id=qdrant_point_id(scope, doc_id, version, chunk_id),
            vector=vector,
            payload={"scope": scope, "doc_id": doc_id, "version": int(version),
                     "chunk_id": chunk_id, "embedding_model": model,
                     "index_version": str(index_version or "")},
        )
        for chunk_id, vector in mapped.items()
    ]
    await qdrant.upsert(collection_name=QDRANT_COLLECTION, points=points, wait=True)
    return True


async def ann_search(query_vector, scope, embedding_model, index_version, limit=FIRST_STAGE):
    """Qdrant ANN top-limit。返回 [(hit dict with score/doc_id/version/chunk_id)]。
    未配置/不可达返回 (None, 'unavailable')。"""
    qdrant = qdrant_client()
    if qdrant is None or query_vector is None:
        return None, "unavailable"
    from qdrant_client import models
    must = [models.FieldCondition(key="scope", match=models.MatchValue(value=scope))]
    if embedding_model:
        must.append(models.FieldCondition(key="embedding_model", match=models.MatchValue(value=embedding_model)))
    if index_version:
        must.append(models.FieldCondition(key="index_version", match=models.MatchValue(value=str(index_version))))
    response = await qdrant.query_points(
        collection_name=QDRANT_COLLECTION,
        query=query_vector,
        query_filter=models.Filter(must=must),
        limit=limit,
        with_payload=True,
    )
    hits = []
    for point in response.points:
        payload = point.payload or {}
        hits.append({"doc_id": payload.get("doc_id"), "version": payload.get("version"),
                     "chunk_id": payload.get("chunk_id"), "score": point.score})
    return hits, "qdrant_hnsw"


def shutdown():
    """应用停机时回收：关闭客户端并停掉检索专用循环（此前 close() 定义了但没有调用方）。"""
    global _es, _qdrant, _retrieval_loop
    loop = _retrieval_loop
    if loop is not None and not loop.is_closed():
        async def _close_clients():
            global _es, _qdrant
            if _es is not None:
                await _es.close()
                _es = None
            if _qdrant is not None:
                await _qdrant.close()
                _qdrant = None
        try:
            asyncio.run_coroutine_threadsafe(_close_clients(), loop).result(timeout=10)
        except Exception as error:  # noqa: BLE001 - 停机路径尽力而为
            log.warning("检索客户端关闭失败（忽略）：%s", error)
        loop.call_soon_threadsafe(loop.stop)
        _retrieval_loop = None
