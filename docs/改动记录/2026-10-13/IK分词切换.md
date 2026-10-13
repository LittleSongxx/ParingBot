# IK 分词切换（smartcn/cjk → ik_max_word）

日期：2026-10-13（Asia/Shanghai）。本文件是当日「中间件栈对齐改造」三批次的第一批，
后续批次（RabbitMQ→RocketMQ、OpenFeign→Dubbo）见同日目录。

## 需求

将 Elasticsearch 中文分词从现状切换为 IK 分词，对齐国内电商搜索的主流选型
（IK 支持自定义词典与热更新）。选型评估结论：smartcn 无词典能力，切换为 IK。

## 现状澄清（本次调研发现，与既有文档说法不一致）

1. **商品索引从未真正使用 smartcn 插件**：`ProductIndexService` 中名为 `smartcn_zh`
   的分析器实际是 custom + standard tokenizer；商品检索走 `productName.raw` keyword
   子字段的 wildcard（与 SQL LIKE 逐字等价），分词器不参与检索谓词。
2. **线上/本地 ES 容器是 stock 镜像**（`docker.elastic.co/...:8.19.0`），
   `deploy/elasticsearch/Dockerfile` 虽写了安装 smartcn 但未被 compose 引用，
   插件从未装进容器；assistant 知识索引经探测回退实际按内置 cjk（bigram）建。
3. assistant 进程环境缺 `SMARTLECT_ES_URL`（runtime.env 由旧版模板生成），
   ES 检索通道在本地一直关闭——本次一并补齐。

## 具体变更

| 文件 | 变更 |
| --- | --- |
| `deploy/elasticsearch/Dockerfile`（及 backend 下副本） | 插件 `analysis-smartcn` → `analysis-ik` 8.19.0（社区构建源 get.infini.cloud，与 ES 严格同版） |
| `deploy/compose.yaml` | elasticsearch 服务 stock 镜像 → `build: ./elasticsearch`（`smartlect/elasticsearch-ik:8.19.0`），否则插件不会进容器 |
| `assistant/src/smartlect/hybrid_search.py` | `ANALYZER_CANDIDATES = ("ik_max_word", "smartcn", "cjk")`，IK 优先、smartcn/cjk 探测回退；模块 docstring 同步 |
| `assistant/src/smartlect/knowledge.py` | 注释「ES 是服务端 BM25（smartcn 分词）」→（IK 分词） |
| `assistant/tests/test_retrieval_health.py` | mock backend 标签 `es_bm25_smartcn` → `es_bm25_ik`（3 处） |
| `backend/.../search/ProductIndexService.java` | 分析器改为 custom + `ik_max_word` tokenizer；新增 IK 插件缺失时的降级重建（text 字段仅冗余快照，降级不影响 wildcard 谓词）；修正名不副实的日志与 javadoc |
| `run/runtime.env` | 补 `SMARTLECT_ES_URL`（本地文件，不入库） |
| 文档 | README（2 处）、docs/runtime.md、docs/agent-design.md、docs/architecture-interview.md（2 处，ADR 索引行加时点注）；ADR-0007 加后记（修正「smartcn 随官方镜像分发」的错误说法并记录本次切换） |

## 验证与证据

- **插件**：容器 `_cat/plugins` 显示 `analysis-ik 8.19.0`。
- **分词对比**（`_analyze`，样例「无线蓝牙机械键盘支持全键无冲」）：
  ik_max_word = 无线/蓝牙/机械/键盘/支持/全/键/无/冲（词级）；
  cjk（旧）= 无线/线蓝/蓝牙/牙机/…（bigram 滑窗）。
- **商品索引**：DELETE 后由 Initializer 重建，87469 条全量完成；mapping
  `zh_text = custom(ik_max_word)`；wildcard 检索「键盘」命中 831（LIKE 等价语义保持）。
- **知识索引**：assistant 重启后 ensure_schema 以 `default=ik_max_word` 建；
  store scope 33 篇 34 chunks 重写入（一次性脚本，注意不能逐篇调 `_mirror_index`
  ——其内部每次 `asyncio.run` 新建事件循环，ES 客户端单例绑定首个循环后静默失败，
  须单循环内写）。BM25「退货」正确命中「退货条件与期限」。
- **测试**：backend 全量单测通过（product 35 项含 ProductIndexServiceTest 全绿）、
  assistant 全量单测通过。
- **评测回归（检索面离线隔离对比）**：support-eval 77 题 × 47 篇语料、同一份
  chunk、生产同构查询，只变默认分词器。结果（69 个有金标题）：
  ik_max_word Recall@5 **0.9855** / MRR 0.8780；cjk（旧）Recall@5 0.9783 / MRR 0.8809。
  翻转题仅 1 个且为改善（r-061：0→0.50），无回归题。
  证据：[retrieval-ik-vs-cjk.txt](../../eval/verification/ik-analyzer-switch-20261013/retrieval-ik-vs-cjk.txt)。
  说明：此对比隔离了分词器单变量；Faithfulness/Relevancy 等 judge 指标依赖
  live 模型 key，本次未跑，官方双跑均值待具备条件时复测。

## 索引重建操作记录（本地）

1. `docker compose build elasticsearch && docker compose up -d elasticsearch`。
2. `DELETE /smartlect-products` → 重启 product 服务（Initializer 全量重建 87469 条，
   约 6 秒）。
3. `DELETE /smartlect-knowledge`（如有）→ 重启 assistant（ensure_schema 以 IK 建）
   → store scope 34 chunks 重写入。

## 启用与回滚

- 启用：以上变更即生效路径；线上部署需重建 ES 镜像并重放步骤 2/3。
- 回滚：git revert 本批文件 → Dockerfile 恢复 smartcn → `docker compose build` →
  按同步骤重建索引。assistant 探测链保留 smartcn/cjk 回退，回滚无需改代码。

## 未完成项

- knowledge 索引向量侧（Qdrant）不受本次影响，未动。
- 3600+ 个 demo scope 的知识副本未灌入 ES（demo 场景激活时按需索引，主链路
  store scope 已就绪）。
- support-eval 官方双跑（含 judge 指标）待 live key 具备时复测。
- 顶层架构图/图集的 smartcn 字样在收尾批次统一再生成。

## 关联代码版本

- 分支 main，提交见本文件同日 commit（批次一）。
