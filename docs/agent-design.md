# Agent 设计

> 单一领域 Agent（Shopping）+ 确定性交易外围 + 按需并行子智能体。
> 覆盖 ADR-0001/0003/0008/0009/0010 的落地形态。

## 形态

系统里只有一个领域 Agent——**Shopping**。没有总指挥 Supervisor，没有把检索或记账再包装成 Agent。

```
用户消息 → Shopping Agent（有界 ReAct，手写三节点 LangGraph StateGraph）
              │
              ├── 20 个工具（读 / 提案 / 记忆 / 证据 / 人工 / 派发）
              │      │
              │      ├── task_dispatch ──→ 1–3 个子智能体并发（create_react_agent）
              │      │                      各自独立上下文，只回传结论
              │      │
              │      └── propose_order ──→ 持久化提案（WAIT_USER）→ 人点确认 → Java 落单
              │
              └── 终答（结构化 JSON 契约 + 引用逐 chunk 复核）
```

**为什么不用 create_react_agent 做主循环**：ADR-0009——持久化提案 HITL 优于进程内 interrupt，27 版评测合同锁定手写节点语义。子智能体已用 prebuilt 验证了可行性，主循环迁移为「暂缓」而非「保留」。

## 运行时预算

| 边界 | 值 | 说明 |
|---|---|---|
| 模型调用 | ≤6/轮 | 含 embedding、重试、修复 |
| 工具调用 | ≤10/轮 | |
| 检索调用 | ≤2/轮 | 第 3 次按覆盖率给空观测或拒绝 |
| 轮 deadline | 90s（图用 85s） | 超限走确定性降级收口 |
| 图步数 | recursion_limit 25 | LangGraph 硬界 |
| 上下文窗口 | 14400 token / 43200 字节 | `langchain_core.trim_messages`（ADR-0010） |
| 轮 token 预算 | 60000（env 可调，0=关闭） | 四档分层：main / lite（注入简洁提示）/ minimal（强收口提示）/ fallback（`turn_token_budget` 走降级链）；lite 起拒绝 task_dispatch |
| 终止原因 | close_reason 枚举 | completed/handoff/recovered_*/budget_exceeded/repair_exhausted/deadline/provider_fault/retrieval_empty/guard_violation/degraded，`assistant_close_reason_total{reason}` 可统计降级率 |
| 终答修复 | ≤1 次 | GuardViolation 后单次重写 |

超限不无限循环：`BudgetExceeded` → `close_degraded_turn()` 确定性收口（诚实空集 / 转人工 / 模板答案），终态记录在 run 结果里。

## 工具面（20 个）

> 贴着 OpenAI 的 <20 软上限：新增能力优先做成 Skill（load_skill 延迟加载）；
> 工具合并（如 6 个订单查询工具收敛）属第三批结构性改动，独立 PR + 评测关卡。

| 类别 | 工具 | 权限 | 说明 |
|---|---|---|---|
| 检索 | `search_knowledge` | shopping:read | RAG 检索（ES BM25 + Qdrant dense → RRF → rerank） |
| 检索 | `search_skus` / `recommend_skus` / `compare_skus` | shopping:read | 约束检索，价格库存每次实时查 Java |
| 检索 | `get_product_offer` | shopping:read | Java 商品级介绍 |
| 证据 | `lookup_conversation_evidence` | shopping:read | 按 result_ref/关键词回查本会话历史工具回执；返回历史观察值，当前价格/库存/状态必须实时工具复核 |
| 派发 | `task_dispatch` | shopping:read | 1–3 个独立只读检索任务并行交子智能体（ADR-0010） |
| 订单只读 | `get_my_orders` / `get_order_status` / `get_refund_status` / `get_payment_status` / `list_my_coupons` / `get_my_addresses` | orders:read | 查询本人交易事实 |
| 提案 | `propose_order` / `propose_cancel` / `propose_refund` | orders:write | 先向 Java 要报价 → 落库为待确认提案 |
| 记忆 | `get_conversation_memory` / `remember_preference` | shopping:read / orders:write | 偏好写入须逐字引用本轮用户原话 |
| 人工 | `request_handoff` | shopping:read | 转人工工单 |
| Skill | `load_skill` | shopping:read | 按需加载业务 Skill |

## 提案确认闭环（HITL）

`propose_*` 生成提案 → SSE 推送确认卡 → 前端独立向 Java 复核商品/地址 → 用户点确认（CSRF + version 乐观锁）→ 幂等执行（`recover_only` 查状态恢复）→ SUCCEEDED / FAILED / UNKNOWN。

**没有任何模型工具可以直接成交。** 提案 5 分钟过期，过期后可一键重新生成。

## 子智能体（ADR-0010）

- 每个子智能体 = `langgraph.prebuilt.create_react_agent`（框架预构建 ReAct 循环）
- 工具面收窄为 7 个只读工具（`StructuredTool` 包装既有 REGISTRY）
- `asyncio.gather` 并发，各自独立上下文与预算（25s 超时 + recursion_limit 12）
- **模型与工具调用计入主循环同一预算与审计**：子智能体每次模型调用过主会话 `before_attempt` 闸（计入 MODEL_CALL_LIMIT、落 `model_attempts`），子工具调用过 `tool_tick`（计入 TOOL_CALL_LIMIT）；预算耗尽按单任务失败降级披露
- 只回传最终结论文本——中间工具事件不进主上下文
- 派发判据写进系统提示词：**可并行 / 需上下文隔离 / 调用链深**，其一成立才用

## 上下文拼装与前缀缓存（ADR-0014）

system 只承载会话内逐字恒定的五段（角色契约 + 冻结策略 + Skills 目录 + 已加载
流程 + 主体类别）；所有每轮可变载荷（Skill 预告、澄清闸、只读上下文、焦点块、
待决提案提示）进「本轮材料」user 消息，插在最后一条用户消息之后——ReAct 步间
严格前缀。三不变量由 `tests/test_prompt_prefix.py` 钉死；缓存命中经
`assistant_prompt_cache_read_tokens_total` 与 decision 的 `cache_read_ratio` 观测
（上游不报 cached 为 None，未知不当 0）。检索词遵循「原话为主」合同
（`compose_search_query`），指代式短问句由 `query_understanding.anaphora_expand`
做确定性补全（失败回落原句；独立完整问句原样透传）。

## RAG 检索管道

```
知识发布流：DRAFT → 异步索引任务 → PUBLISHED → 才可检索
             ↓
双写：ES 文档（IK BM25）+ Qdrant point（1024 维 HNSW）
             ↓
检索：ES BM25 top50 ‖ Qdrant dense top50
      → RRF 融合（k=60）
      → gte-rerank（失败回退 RRF 序）
      → top8 → 引用 ≤4 + 相似度拒答阈值
```

- **价格库存不进向量**：每次实时查 Java（`search_skus` → `searchOnSale` → `snapshotBatch` → `stock/getBatch`）
- 撤回后不再被新的引用；引用提交前 `FOR SHARE` 锁读复核发布/ACL/有效期
- 未配置 ES/Qdrant 时回退内存 BM25 单路（小语料环境仍可检索）

## 模型接入

`openai` SDK（3.14.1）走 OpenAI 兼容端点。端点白名单（dashscope / 智谱 compatible-mode）+ 模型白名单（qwen3.7-plus / glm-5.3）。模型热切换走 MySQL `model_runtime_config` 表（5s TTL 异步加载）。

## 行为守卫

守卫分两层治理（[ADR-0013](adr/0013-guard-chain-layering.md)）：证据契约校验（确定性不变量，永久保留）与意图帧启发式（评测驱动逐条降级改判权）。

| 守卫 | 机制 |
|---|---|
| 选择门 | 强制先选规格再收口 |
| 回退授权 | "按可售来"确定性替代收口，不消耗模型修复轮 |
| 引用复核 | 提交前 `FOR SHARE` 锁读重验发布/ACL/有效期 |
| 注入隔离 | 检索内容只露标题不复述正文；`quarantined` 不可引用 |
| 契约修复 | 终答 JSON 校验失败后单次重写 |
| 偏好写入 | 须逐字引用本轮用户原话 |

## 覆盖路径

- 代码：`assistant/src/smartlect/agents/shopping/`（policy · contract · guardrails · compile · observations · session · graph · model_adapter · dispatch）
- ADR：[0001 最终融合](adr/0001-final-integration.md) · [0003 控制面](adr/0003-agent-control-plane.md) · [0008 推荐线退役](adr/0008-retire-recommendation-line.md) · [0009 runtime 选型](adr/0009-agent-runtime-choices.md) · [0010 子智能体](adr/0010-subagent-dispatch.md)
