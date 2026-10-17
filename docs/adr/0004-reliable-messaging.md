# ADR-0004：可靠消息采用 Outbox + 消费幂等 + 延迟驻留

- 状态：Accepted
- 日期：2026-10-17
- 范围：common / order / pay / coupon / user
- 相关代码：`backend/smartlect-common/src/main/java/com/smartlect/service/impl/OutboxMessageServiceImpl.java`、`backend/smartlect-common/src/main/java/com/smartlect/mq/RocketMqConsumerContainer.java`、`backend/smartlect-common/src/main/java/com/smartlect/mq/RocketMqTopics.java`、`backend/smartlect-common/src/main/java/com/smartlect/task/OutboxDispatchTask.java`

## 背景

“数据库提交成功，但消息没发出去”是跨服务一致性的常见裂缝。项目需要可靠地产生支付成功、关单、退款、物流推进、券回补等事件，还要支持 15 分钟、1 小时、7 天三档延迟。直接“写库后发 MQ”无法保证两者同生共死；RocketMQ 事务消息可以，但会强绑定 MQ。

## 决策

1. **同事务写 Outbox**：`TransactionalMqSender#sendAfterCommit` 在业务事务内写 `local_message_outbox`，提交后异步触发投递；同键同载荷复用，同键不同载荷报错。
2. **数据库租约投递**：`claimForDispatch` 用 SQL 抢租约，`markSent` 校验租约仍在；多实例不会无脑双投，租约/退避时间用数据库 `NOW()`，避免应用时钟漂移。
3. **延迟驻留**：超过 broker 时间轮上限（默认 24 小时）的消息先按 `delivery_expire_at` 驻留，`outboxDispatch` 每 5 秒扫描，在剩余延迟进入窗口后重投。
4. **消费幂等**：`RocketMqConsumerContainer` + `MqConsumerIdempotencyHelper` 用 Redis `processing` 租约 + `done` 标记；BUSY 30 秒后回投；业务异常按 5s/30s/120s 回投；耗尽写 `mq_compensation_log`，由 xxl-job 自动重放或管理端手工重放。
5. **延迟档位**：`RocketMqTopics` 定义 15 分钟关单、1 小时物流、7 天确认收货；Topic/Tag 与消费组集中管理。

## 备选方案

- **RocketMQ 事务消息**：半消息 + 本地事务 + 回查，减少 DB 消息表；但强绑定 RocketMQ，回查接口仍需业务实现。项目选择 Outbox 保持 MQ 可替换。
- **直接发送 + 本地重试**：业务成功/消息失败无法原子，不采用。
- **CDC 替代 Outbox**：适合读模型（商品索引），不适合“业务事件必须与本地提交同生共死”的场景。
- **纯定时扫描 + 无租约**：多实例会重复投递；DB 租约解决了这一点。

## 后果

**正向**

- 事件不会因为 MQ 短暂不可用而丢失；恢复后自动投递。
- 消费重复、顺序抖动、失败重试都有确定处理；补偿表提供人工出口。
- 支持远未来延迟消息，不依赖 broker 的固定档位。

**代价**

- 消息是 at-least-once，消费必须幂等；不能把 Outbox 当 exactly-once。
- Outbox 与业务同库，扫描/写入会占用业务库资源；单表扫描在大量消息时需要分片/归档。
- 延迟驻留和租约逻辑增加理解成本；需要监控积压、租约冲突和 EXHAUSTED。

## 何时重审

- 单库 Outbox 扫描成为瓶颈，或消息量需要跨库统一中继；
- 深度绑定 RocketMQ 后，事务消息的运维成本低于自建 Outbox；
- 需要严格顺序消息或跨地域消息复制。

## 证据

- Outbox：`OutboxMessageServiceImpl#savePending/tryDispatch`、`OutboxDispatchTask`。
- 消费：`RocketMqConsumerContainer`、`MqConsumerIdempotencyHelper`、`MqListenerHelper`。
- 延迟：`RocketMqTopics` 的 `PAY_TIMEOUT/LOGISTICS_STEP/CONFIRM_RECEIPT`。
- 演练：`scripts/drills/fault_drills.py` 的 `mq-down`。
