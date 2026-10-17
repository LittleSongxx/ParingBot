# ADR-0001：交易一致性采用本地事务 + Outbox

- 状态：Accepted
- 日期：2026-10-17
- 范围：order / stock / coupon / pay / user address
- 相关代码：`backend/smartlect-order/app/src/main/java/com/smartlect/biz/impl/OrderCreationService.java`、`backend/smartlect-common/src/main/java/com/smartlect/service/impl/OutboxMessageServiceImpl.java`、`backend/smartlect-common/src/main/java/com/smartlect/constants/TransactionalMqSender.java`

## 背景

一次下单至少涉及订单、库存、优惠券、支付四个库，还要读用户地址。它们分属不同服务、不同 schema，没有任何一个本地事务能覆盖全部写入。项目曾评估 Seata，但跨库协调者会把所有服务绑在同一套回滚边界上，连接占用、故障面和推理成本都上升；本项目最终选择不引入分布式事务框架。

## 决策

每个服务只在自己的库内使用本地事务，把“业务事实”和“要发出的消息”写在同一个事务里；跨服务结果通过以下组合收敛：

1. **Outbox**：业务事务内写 `local_message_outbox`，提交后异步投递；投递失败由定时扫描、租约和补偿表兜底。
2. **幂等账本**：下单等命令用 `(user_id, command_type, idempotency_key)` 唯一键记录状态和响应；重复请求返回确定结果。
3. **业务补偿**：下单 P4 失败回补库存、解锁券；退款 Saga 按阶段重试。
4. **对账任务**：支付轮询、退款续跑、券秒杀库存对齐、Outbox 重投。

不追求“所有库同时成功/失败”，只要求每个中间态都能被下一步收敛。

## 备选方案

- **XA/2PC**：强一致，但同步阻塞、协调者单点，不适合跨多个 Spring Boot 服务的下单链路。
- **Seata AT/TCC**：AT 依赖全局锁且默认读未提交；TCC 需要业务实现 Try/Confirm/Cancel，复杂度和侵入性都高。当前单店规模不需要。
- **RocketMQ 事务消息**：能把本地事务和消息绑定，但会强绑定 RocketMQ，且仍需要回查与消费幂等；项目选择 Outbox，保持 MQ 可替换。
- **直接写库后发 MQ**：会出现“库成功、消息失败”的裂缝，不可接受。

## 后果

**正向**

- 服务之间没有全局锁，单服务可独立演进；下单请求不会因为跨库事务长时间占用连接。
- 消息与业务事实同生共死；失败路径有明确补偿点。
- 每个中间态都有测试/演练可验证。

**代价**

- 系统接受短暂不一致：订单可能已支付但券未核销，退款可能已通过但库存未回补。
- 需要长期维护幂等、补偿、对账三套代码；Outbox 会占用业务库写入和扫描资源。
- 读路径可能看到中间态，前端/管理端需要按状态展示，而不是假设“已支付=全部完成”。

## 何时重审

- 单服务写入量或跨服务事务频率增长到本地事务/Outbox 扫描成为瓶颈；
- 业务要求资金/库存强一致且不能接受中间态；
- 引入跨地域多活，单写点无法满足 RTO/RPO。

出现以上情况时，优先评估 TCC/事务消息/单元化，而不是直接上全局 2PC。

## 证据

- 下单五阶段与事务边界：`OrderCreationService` 的 Phase 1–5 注释与实现。
- Outbox 租约/驻留/重投：`OutboxMessageServiceImpl`、`OutboxDispatchTask`。
- 故障演练：`scripts/drills/fault_drills.py` 的 `duplicate-order`、`mq-down`、`redis-down`。
- 相关测试：`OrderCreationIntegrityTest`、`OrderRequestIdempotencyServiceTest`、`OrderConsistencyFixIT`。
