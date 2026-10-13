# ADR-0007: 检索栈选型 Elasticsearch(BM25) + Qdrant(dense) + 客户端 RRF

日期：2026-10-04
状态：已接受（2026-10 收敛重构）

## 背景

知识检索此前是全自研管道：jieba 分词 + 内存全量扫描（≤5000 chunk）算 BM25 + pgvector SQL 镜像 + 自研 RRF。三个组件都是自有代码，维护面大；且「BM25 top50 + dense top50 → RRF → rerank → top5-10」正是 2026 年生产系统的默认检索管线。

## 决定

- **Elasticsearch 8.19**（smartcn 中文分词，随官方镜像分发）：承担词法 BM25 召回，服务端打分。
- **Qdrant v1.15**（HNSW，1024 维）：承担 dense 召回，payload 过滤 scope/模型/索引版本。
- **客户端 RRF**（k=60）：两路融合——RRF 是 10 行标准算法，不值得为此引入托管融合服务。
- **供应商 rerank 保留**（gte-rerank-v2，失败显式回退 RRF 序）。
- 未配置或不可达时**回退内存 BM25 单路**（小语料环境可检索，降级链不破坏）。

实现见 `assistant/src/smartlect/hybrid_search.py`（懒加载双客户端 + 幂等建索引）与 `knowledge.py` 的 `rank_chunks(es_hits=...)`。

## 后果

- 删 pgvector 镜像与 `vector_store.py` SQL 镜像；MySQL 只存 chunk 权威行。
- 索引双写（Qdrant 向量 + ES 文档）在 `attach_embeddings` 原子点完成，失败不阻塞发布（审计台账已有）。
- 代价：多两个中间件容器（ES ~1GB 内存）。语料 <100 chunk 的场景应关闭 ES 环境变量走内存路径。

## 后记（2026-10-13）

本文「smartcn 随官方镜像分发」的说法有误：smartcn 插件同样不随镜像分发，此前的自建
Dockerfile 虽写了安装但 compose 一直用 stock 镜像，线上知识索引实际按内置 cjk 分析器
建（bigram 切分）。当日已将中文分词切换为 **IK（ik_max_word）**：自建镜像预装
analysis-ik 8.19.0（社区构建源）、compose 切 build、探测候选改为 ik_max_word 优先。
商品索引 text 字段同步换 IK（该字段仅冗余快照不参与检索，谓词始终是 raw keyword 的
wildcard，语义不受分词器影响）。support-eval 检索面离线对比：Recall@5 0.9783→0.9855、
MRR 持平，无回归题。选型依据与证据见 `docs/改动记录/2026-10-13/IK分词切换.md`。
