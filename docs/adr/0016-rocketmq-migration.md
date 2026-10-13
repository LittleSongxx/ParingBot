# ADR-0016: 消息队列 RabbitMQ → RocketMQ 5.x

日期：2026-10-13
状态：已接受（当日实施并端到端实证）

## 背景

技术选型评审结论：国内电商核心链路（延迟/事务/顺序消息）主流为 RocketMQ，RabbitMQ
适合中小流量复杂路由。用户决策全面切换，并要求任意精度定时消息（5.x）与集群
（DLedger）同步改造。

## 决定

- RocketMQ 5.3.2（namesrv/broker/proxy 三容器）+ rocketmq-client-java 5.0.8（gRPC 经
  proxy 接入）。
- 拓扑：6 交换机/45 队列收敛为 6 Topic+Tag；**定时消息独立 Topic `smartlect-delay`**——
  5.3.2 的 mqadmin 对 message.type 多值（NORMAL,DELAY）无法表达（逗号与 -a 分隔符冲突），
  且不带属性建 Topic 会写入该非法组合默认值（proxy 校验 Enum.valueOf 直接 50001）；
  定时/即时分流到不同 Topic，Tag 语义不变。
- 消费失败三级重试（5s/30s/120s）由「定时回投原 Topic/Tag + 幂等键不变」实现，broker
  原生重试队列不使用（自管节奏）；重试耗尽落 mq_compensation_log 并归档统一失败 Topic。
- Outbox 加列 delivery_expire_at（绝对到期时间），补发按 now 折算剩余延迟。
- 集群：DLedger 三副本（Raft 自动选主）替换 RabbitMQ 三节点 quorum，cutover/revert/
  verify 脚本同步重建。

## 后果

- publisher-confirm 等待机制整体废弃（gRPC 同步 send 即确认），MqPublisherConfirmHelper
  与其集成测试删除。
- 10 个消费者的 ack/nack 骨架上收 RocketMqConsumerContainer 模板（幂等租约/重试链/审查
  表归档统一执行），业务监听器只剩业务逻辑。
- Topic 预建成为部署硬前置（订阅侧校验路由），compose 以 rocketmq-topic-init 容器承载，
  属性必须显式单值。
- 代价：内存占用 +384m（namesrv+proxy）；5.0.8 客户端无 Spring starter，生产消费封装为
  自研薄层（本就有 ReliableMessageSender 封装传统）。

## 已知边界

- **补偿重放不携带定时语义**：mq_compensation_log 的重放走 replaySend 立即投递。
  当前所有定时消息都经 Outbox（有 delivery_expire_at 列，补发折算剩余延迟）且级别为
  STANDARD，HIGH 级别仅用于即时事件，因此现状安全；若未来出现「HIGH + 定时」组合，
  需给 MqCompensationRecord 增加到期字段。
- %RETRY% broker 原生重试组未使用（消费重试由容器定时回投自管节奏）。

实施记录与端到端证据：`docs/改动记录/2026-10-13/RabbitMQ迁移RocketMQ.md`。
