#!/usr/bin/env python3
"""商品搜索谓词 A/B：substring（与 SQL LIKE 逐字等价）vs hybrid（叠加分词打分腿）。

为什么需要这个脚本：`smartlect.search.mode` 的两条腿行为差异（召回是子串的超集）在功能测试里
看不出来，必须用真实索引量化。结论无论偏向哪边都如实写入证据文件。

口径
- 数据源：线上索引 `smartlect-products`（样本来自真实商品名），查询由商品名机械派生；
- 两种谓词的 DSL 与 `ProductIndexService#searchIdsByKeyword` 保持一致（形状由单测
  ProductIndexQueryShapeTest 锁定，本脚本是其"
  离线镜像"）；排序都按 createTimeMillis desc，size 取 top-10；
- 三组查询：
  1) 子串可命中（取标题里的一段连续文本）——两模式都应命中，用来验证 hybrid 不丢召回；
  2) 词序打乱（把标题按空格切分后重排）——只有分词腿可能命中，用来量化打分腿的增益；
  3) 宽松语义探针（取标题里的单个高频词）——量化"放宽资格语义"的规模（结果里有多少条
     其实并不逐字包含查询串）。

输出：控制台表格 + `--out` 指定的证据文件。

用法：python3 scripts/eval_product_search.py [--sample 40] [--out eval/verification/<date>/product-search-ab.txt]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import statistics
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = "smartlect-products"


def env_value(key: str, default: str) -> str:
    env_file = ROOT / "run/runtime.env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1]
    return default


ES = env_value("SMARTLECT_ES_URL", "http://127.0.0.1:9200").rstrip("/")


def es(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{ES}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def escape(value: str) -> str:
    """与 Java 侧 escapeWildcard 一致：用户输入按字面处理。"""
    return value.replace("\\", "\\\\").replace("*", "\\*").replace("?", "\\?")


def text_leg(query: str) -> dict:
    """substring 模式的文本谓词（Java 侧形状：单条 should = productName.raw 大小写不敏感 wildcard）。

    注意：leg 必须落在 should 里——把 wildcard 放进 must 再声明 minimum_should_match=1
    会得到"零个 should 子句却要求至少命中一个"的恒假查询（本脚本第一版踩过，全组 0 命中）。
    """
    return {"bool": {"should": [{"wildcard": {"productName.raw": {
        "value": "*" + escape(query) + "*", "case_insensitive": True}}}],
        "minimum_should_match": 1}}


def hybrid_text_leg(query: str) -> dict:
    """hybrid 模式的文本谓词（子串腿 + 商品名/描述分词腿，minimumShouldMatch=1）。"""
    return {"bool": {
        "should": [
            {"wildcard": {"productName.raw": {
                "value": "*" + escape(query) + "*", "case_insensitive": True, "boost": 1.0}}},
            {"match": {"productName": {"query": query, "boost": 2.0}}},
            {"match": {"productDesc": {"query": query, "boost": 1.0}}},
        ],
        "minimum_should_match": 1,
    }}


def search(query: str, hybrid: bool, top: int = 10) -> tuple[list[dict], float]:
    body = {
        "size": top,
        "query": {"bool": {
            "must": [hybrid_text_leg(query) if hybrid else text_leg(query)],
            "filter": [
                {"term": {"status": 1}},
                {"bool": {"must_not": [{"term": {"catalogScope": "eval"}}]}},
            ],
        }},
        "sort": [{"createTimeMillis": {"order": "desc"}}],
        "_source": ["productName"],
    }
    started = time.perf_counter()
    result = es("POST", f"/{INDEX}/_search", body)
    elapsed_ms = (time.perf_counter() - started) * 1000
    hits = [{"id": h["_id"], "name": h["_source"].get("productName", "")} for h in result["hits"]["hits"]]
    return hits, elapsed_ms


def sample_titles(count: int) -> list[dict]:
    body = {
        "size": count,
        "query": {"bool": {"filter": [
            {"term": {"status": 1}},
            {"bool": {"must_not": [{"term": {"catalogScope": "eval"}}]}},
        ]}},
        "_source": ["productName"],
    }
    result = es("POST", f"/{INDEX}/_search", body)
    return [{"id": h["_id"], "name": h["_source"].get("productName", "")}
            for h in result["hits"]["hits"] if h["_source"].get("productName")]


def build_queries(samples: list[dict], rng: random.Random) -> dict[str, list[dict]]:
    families: dict[str, list[dict]] = {"substring": [], "reordered": [], "loose": []}
    for item in samples:
        name = item["name"]
        parts = [p for p in name.replace("/", " ").split() if len(p) >= 2]
        if len(parts) >= 2:
            head = max(parts, key=len)          # 取最长片段当"型号/描述"词
            if len(head) >= 4:
                families["substring"].append({"query": head, "expect": item["id"]})
            if len(parts) >= 3:
                shuffled = parts[:]
                rng.shuffle(shuffled)
                families["reordered"].append({"query": " ".join(shuffled[:3]), "expect": item["id"]})
        if parts:
            short = sorted(parts, key=len)[0]
            if 2 <= len(short) <= 4:
                families["loose"].append({"query": short, "expect": None})
    return families


def evaluate(queries: list[dict], hybrid: bool, top: int = 10) -> dict:
    hits_at = 0
    loose_total = 0
    loose_queries = 0
    latencies = []
    for item in queries:
        hits, elapsed = search(item["query"], hybrid, top)
        latencies.append(elapsed)
        if item["expect"] and any(h["id"] == item["expect"] for h in hits):
            hits_at += 1
        if item["expect"] is None:
            extra = [h for h in hits if item["query"] not in h["name"]]
            loose_total += len(extra)
            if extra:
                loose_queries += 1
    return {
        "hit@10": hits_at,
        "n": len([q for q in queries if q["expect"]]),
        "loose_results": loose_total,
        "loose_queries": loose_queries,
        "p50_ms": round(statistics.median(latencies), 1) if latencies else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=40)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    rng = random.Random(20261016)
    samples = sample_titles(args.sample)
    families = build_queries(samples, rng)
    if not any(families.values()):
        print("采样为空：确认 smartlect-products 索引有 status=1 的商品", flush=True)
        return 2

    lines: list[str] = []
    def emit(text: str) -> None:
        print(text, flush=True)
        lines.append(text)

    total_docs = es("GET", f"/{INDEX}/_count")["count"]
    emit(f"# 商品搜索谓词 A/B（ES {ES} · 索引 {INDEX} · {total_docs} 条文档）")
    emit(f"# 采样 {len(samples)} 条商品名；三组查询：子串可命中 / 词序打乱 / 宽松语义探针；top-{args.top}\n")

    header = f"{'组':<12}{'模式':<10}{'命中@10':<12}{'命中率':<10}{'宽松结果(前10条里不逐字包含的)':<34}{'p50(ms)':<8}"
    emit(header)
    emit("-" * len(header))
    summary = {}
    for family in ("substring", "reordered", "loose"):
        queries = families[family]
        if not queries:
            continue
        for hybrid in (False, True):
            stats = evaluate(queries, hybrid, args.top)
            mode = "hybrid" if hybrid else "substring"
            rate = f"{stats['hit@10'] / stats['n'] * 100:.0f}%" if stats["n"] else "—"
            hits = f"{stats['hit@10']}/{stats['n']}" if stats["n"] else "—"
            loose = (f"{stats['loose_results']} 条 / {stats['loose_queries']} 个查询"
                     if family == "loose" else "—")
            emit(f"{family:<12}{mode:<10}{hits:<12}{rate:<10}{loose:<34}{stats['p50_ms']:<8}")
            summary[f"{family}:{mode}"] = stats

    emit("")
    emit("## 结论口径（如何读这张表）")
    emit("- substring 组：两模式命中率应当一致——hybrid 的子串腿保证不丢召回（超集性质）。")
    emit("- reordered 组：只有分词腿可能命中；若 hybrid 明显更高，说明打分腿对『词序不同』的问法有增益。")
    emit("- loose 组：量化的是『放宽资格语义』的规模（前 10 条里有多少条并不逐字包含查询串）；")
    emit("  这正是 v16 评测把分词检索回退掉的原因——若本表显示宽松结果显著，则默认保持 substring 是有据的。")
    emit("- 注意：本索引只当 ID 集过滤器用（排序/分页在 DB），分数不改最终顺序——所以打分腿的收益只体现在")
    emit("  『命中/不命中』，不体现在排序上。要用分数换相关性，需要把排序权整体交给 ES（另一档重构）。")

    if args.out:
        out = ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n已写入 {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
