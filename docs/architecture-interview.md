# Smartlect 架构说明与源码追问

更新：2026-10-04（收敛重构后）。本文按面试追问的粒度解释当前实现与取舍。

## 一句话主线

一个 Java 微服务商城（交易权威），上面跑一个有界 ReAct 导购 Agent（只建议不成交），配一套带分母的评测。

## 业务主线：一次下单的完整链路

```
用户提交订单（Idempotency-Key）
→ Java 条件 UPDATE 扣库存（幂等键 = order-deduct:{payOrderId}）
→ 本地事务：订单+明细+物流+幂等账本原子提交
→ Outbox 事件（事务内落库，afterCommit 投递）
→ pay 服务创建支付意图（intent 权威，金额不可篡改）
→ 延迟队列超时关单（RabbitMQ TTL + 死信）
→ 支付成功 → PAY_SUCCESS MQ 事件 → order 消费推进状态
→ 金额分摊：按原价权重分摊到 item.paid_amount（DB CHECK 约束校验）
```

## 事务策略（ADR-0006）

| 层 | 做法 | 为什么不用 Seata |
|---|---|---|
| 单库原子性 | 订单+明细+物流+幂等账本一个本地事务 | 单库不需要全局事务 |
| 库存 | 条件 UPDATE + 幂等键 + 失败显式回补 | "先锁后扣"有中间态悬挂风险 |
| 跨服务事件 | Outbox + 消费幂等 + 定时对账 | AT 与手工补偿双轨使回滚边界不可推理 |
| 秒杀券 | Redis Lua 预扣 + 失败 releaseRushCouponReserve | releaseStockAfterDbRefund 已含 addStock 回补 |

## 鉴权（ADR-0011）

| 层 | 组件 |
|---|---|
| 用户登录 | Sa-Token `StpUtil`（tokenName=token，isConcurrent=true） |
| 管理登录 | Sa-Token 多账号 `StpAdminLogic`（loginType=admin，tokenName=adminToken，isConcurrent=false 单设备） |
| 网关 | SCG GlobalFilter 读 Redis `token:login:token:{t}` / `adminToken:login:token:{t}` |
| 服务端用户 | `SaInterceptor` + `@SaCheckLogin`（29 处） |
| 服务端管理 | `SaInterceptor` admin 链 + `@SaCheckPermission(orRole=SUPER_ADMIN)`（5 处） |
| 权限数据源 | `SmartlectStpInterface` 从 Sa-Token session 的 adminPrincipal 加载 |
| 内部 API | `X-Internal-Token` HMAC 校验（fail-closed） |

## Agent 设计追问

| 问题 | 答案 |
|---|---|
| 为什么只有一个 Agent | 店里只有一个领域（导购）；检索/记账是确定性服务不是 Agent |
| 为什么手写 ReAct 不用 create_react_agent | 27 版评测合同锁定节点语义；持久化提案 HITL 优于进程内 interrupt（ADR-0009） |
| 子智能体怎么工作 | `task_dispatch` 工具 → 1–3 个 `create_react_agent` 子智能体并发，各自独立上下文/预算，只回传结论（ADR-0010） |
| 模型怎么防幻觉成交 | 无成交工具；`propose_order` 只生成待确认提案（DB 落库 + version 乐观锁），确认走独立 HTTP 端点 |
| RAG 怎么做 | ES IK BM25 top50 ‖ Qdrant dense top50 → RRF → gte-rerank → top8；未配置回退内存 BM25（ADR-0007） |
| 上下文怎么管理 | `langchain_core.trim_messages`（strategy=last, start_on=human），14400 token 硬界 + fail-closed |

## 电商核心设计保留清单

| 功能 | 状态 | 位置 |
|---|---|---|
| 库存条件更新（不超卖） | ✅ | `stock` 服务 `changeStock` |
| 秒杀 Redis Lua 预扣 | ✅ | `coupon_rush_reserve_v1.lua` |
| 命令幂等账本 | ✅ | `order_request_idempotency` |
| Outbox 可靠消息 | ✅ | `local_message_outbox` + 租约重试 |
| 金额分摊 CHECK 约束 | ✅ | `ck_order_item_paid/refunded` |
| 退款持久化 Saga | ✅ | `refund_request` 状态机 + `RefundSagaService.reconcile()` |
| mock 支付（intent 权威） | ✅ | `PayChannel4Mock` |
| 分布式锁 | ✅ | Redisson `RLock`（事务提交后释放） |
| 限流 | ✅ | Redisson `RRateLimiter` |
| 分页 | ✅ | PageHelper 物理分页 |
| 提案确认 HITL | ✅ | `confirm_proposal`（version + recover_only） |

## 重构期关键决策（面试故事）

| ADR | 问题 | 决策 | 关键理由 |
|---|---|---|---|
| [0006](adr/0006-remove-seata.md) | Seata AT 与手工补偿并存 | 删 Seata，统一本地事务+Outbox | 双轨使回滚边界不可推理 |
| [0007](adr/0007-hybrid-retrieval-es-qdrant.md) | 自研 jieba BM25 + pgvector | ES smartcn + Qdrant + RRF（2026-10-13 起分词器为 IK） | 2026 生产默认检索管线 |
| [0008](adr/0008-retire-recommendation-line.md) | 推荐/归因/worker 稀释主线 | 整体退役（−4300 行） | 项目聚焦 Agent+RAG+提案 |
| [0009](adr/0009-agent-runtime-choices.md) | openai SDK / 手写 ReAct / 守卫 | SDK 替换 httpx；ReAct 暂缓；守卫保留 | 评测合同锚定 + 测试锁定 |
| [0010](adr/0010-subagent-dispatch.md) | 多 Agent / 并行 | SubAgent-as-Tool + create_react_agent | 单干优先，按判据派发 |
| [0011](adr/0011-sa-token-migration-plan.md) | 自研鉴权三件套 | Sa-Token 四步迁移 | 国内主流，代码删除 ~200 行 |
