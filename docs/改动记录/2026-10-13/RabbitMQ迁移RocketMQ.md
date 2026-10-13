# RabbitMQ 全面迁移 RocketMQ 5.x

日期：2026-10-13。同日批次二（批次一见 [IK分词切换.md](IK分词切换.md)），决策依据为
当日技术选型评审（用户决策：RocketMQ 5.x 任意定时消息路线、集群同步切换）。

## 需求

消息中间件由 RabbitMQ 4.2 全面切换为 RocketMQ 5.3（gRPC 客户端），延迟消息改用
5.x 任意精度定时消息，集群形态由三节点 quorum 换为 DLedger 三副本。

## 拓扑映射

| 原（RabbitMQ） | 新（RocketMQ 5.x） |
| --- | --- |
| 6 交换机 / 18 业务队列 / 27 个 .retry.N 派生队列 | 6 Topic（pay/refund/rush/canal/delay/mq-failure）+ Tag |
| 5 组 TTL+DLX 延迟队列（15min×2、1h、7d、2h） | 发送侧定时消息（`setDeliveryTimestamp` 任意精度）+ 定时专用 Topic `smartlect-delay` |
| 消费重试三级 TTL 死信拓扑（5s/30s/120s） | 消费失败定时回投原 Topic/Tag（同隔 5s/30s/120s），无派生队列 |
| publisher confirm 同步等待 | gRPC 同步 send 返回即确认 |
| mq_compensation_log 的 exchange/routing_key 字段 | 字段名不变，语义为 topic/tag；重放路由兼容新旧两种键 |

**定时专用 Topic 的由来**（关键坑）：5.3.2 对 DELAY 类型消息按 Topic 的
message.type 属性校验；`NORMAL,DELAY` 多值组合无法经 mqadmin CLI 表达（逗号与
-a 属性分隔符冲突），且不带 -a 时 mqadmin 会写入 `NORMAL,DELAY` 组合默认值——
该组合在 proxy 校验路径 `Enum.valueOf` 直接 50001。最终设计：定时消息独立
Topic `smartlect-delay`（单值 DELAY），即时消息留在业务 Topic（显式单值 NORMAL），
Tag 语义不变。

## 具体变更

### smartlect-common（基础设施层重写）

- 依赖：`spring-boot-starter-amqp`/`amqp-client` → `rocketmq-client-java` 5.0.8。
- 新增 `com.smartlect.mq` 包：`RocketMqTopics`（拓扑常量+延迟时长+旧队列名映射）、
  `SmartlectMqMessage`（中立消息模型，幂等键/重试计数走 property）、
  `SmartlectMessageListener`/`MqSubscription`（监听契约）、`RocketMqClientHolder`
  （Producer 单例）、`RocketMqConsumerContainer`（消费容器：幂等租约 → 反序列化 →
  业务回调 → 完成标记 / 失败进定时回投链，**原 10 个消费者各自维护的 ack/nack
  骨架全部上收容器模板**）。
- `ReliableMessageSender` 重写：HIGH 异步落补偿 / STANDARD 同步重试 3 次语义不变；
  新增 delay 参数；`replaySend` 增加 Outbox 补发用的剩余延迟重载。
- `MqConsumerIdempotencyHelper`：Redis 三态租约机制原样保留，载体换中立消息模型。
- `MqListenerHelper` 重写：`deferBusy`（30s 回投）与 `handleFailure`（5s/30s/120s
  定时回投，耗尽落审查表+归档失败 Topic），返回值决定容器向 broker 报 SUCCESS/FAILURE。
- 删除：`RabbitMQConfig`、`RabbitMqPersistenceConfig`、`MqPublisherConfirmHelper`
  （confirm 等待机制整体废弃）。
- Outbox：`local_message_outbox` 加列 `delivery_expire_at`（Flyway V2/V4/V3/V2/V3
  ×cart/order/pay/product/user 五库）；存绝对到期时间，dispatch 时按 now 折算剩余
  延迟（重试后自动收敛为立即投递）；`TransactionalMqSender` 新增定时重载。
- 8 个服务 application.yml：`spring.rabbitmq` 块删除，新增 `smartlect.rocketmq.endpoints`。

### 消费者（10 个监听方法 → 10 个监听器）

order：`PayTimeoutCloseListener`/`ConfirmReceiptListener`/`LogisticsStepListener`
（由原三合一类拆分，事务方法经 self 代理调用，返回即提交）、
`RabbitMQPaySuccessListenerComponent`、`RefundResultListener`、`RabbitMQOrderListenerComponent`；
coupon：`RabbitMQOrderDeadListListenerComponent`；product：`ProductIndexConsumer`
（Canal flatMessage，跳过幂等租约）；stock：`RefundStockListener`；user：临时解封监听。

### 发送点（8 处）

下单→pay-timeout-close 定时 15min（2 处）；支付成功→logistics-step 1h；
发货→confirm-receipt 7d；物流链式→下一步 1h + confirm 7d；秒杀→rush-timeout 15min；
封禁→tempban-expire（动态到期时间即列值）；支付成功即时事件、退款库存/结果即时事件。
另删除 `DiscountCouponServiceImpl` 的 RabbitTemplate 死注入。

### 部署

- compose：rabbitmq 容器 → namesrv/broker/proxy 三容器 + `rocketmq-topic-init`
  预建 Topic（**必须显式 `-a "+message.type=NORMAL|DELAY"`，见上文坑**）；broker
  `user: "0:0"`（命名卷属主）+ `storePathRootDir` 显式指向卷（root 运行时 JVM
  user.home=/root 会把 store 写进容器文件系统）。
- Canal：`serverMode=rocketMQ`、`canal.mq.servers/topic`；startup.sh 移除交换机
  预声明（Topic 由 init 建），增加 namesrv 探活等待。
- 集群（deploy/cluster）：`rabbit/` → `rocketmq/`（每节点 namesrv+DLedger broker+proxy
  host 网络）；`build-rabbit.sh` → `build-rocketmq.sh`（生成各节点 DLedger 配置、
  分发、三节点拉起、副本断言，含显式 Topic 预建）；cutover/revert/verify/gen-cluster-env/
  distribute/business-check 同步改造；`nodes.env` 端口表换 RocketMQ。
- `scripts/runtime.py`：端口表/bootstrap 模板/infra 服务清单/集群探活键全部换
  `SMARTLECT_ROCKETMQ_ENDPOINTS`（gRPC 8081）。

### 测试

- 重写：`MqConsumerIdempotencyHelperTest`（同用例语义换新 API）、`MqListenerHelperTest`
  （定时回投/审查表断言）、`MqConsumeReplayRouterTest`（新旧双键解析）、
  `RefundStockListenerTest`、`RabbitMQOrderDeadListListenerComponentTest`、
  `UserTempBanServiceTest`、`PayChannel4MockTest`、`ProductIndexServiceTest` 适配。
- 删除：`MqPublisherConfirmHelperTest`、`MqPublisherConfirmRabbitIntegrationTest`、
  `RabbitMQRetryTopologyTest`、旧 `RabbitMQPayOrderDeadListenerComponentTest`
  （registerAckSync 机制已由容器模板取代）。
- `MiddlewareIT`：RabbitMQContainer 段改为本机门禁集成（`SMARTLECT_RUN_ROCKETMQ_INTEGRATION=1`
  时连本机 proxy 做 Producer/PushConsumer 端到端断言；RocketMQ 5.x 无官方
  Testcontainers 模块）。

## 验证与证据

- backend 全量单测通过（mvn test，BUILD SUCCESS）。
- 本机全栈：12 进程健康、9 Nacos 注册、启动冒烟通过；10 个消费者按新拓扑全部启动
  （日志 grep「RocketMQ 消费者已启动」10 条，topic/tag/group 与设计一致）。
- 交易链路端到端（演示买家真实下单，幂等键 e2e-final-*）：
  1. 下单成功（orderId 202610132349528355ihrPw4oyf9EU7H，6849 元）；
  2. **定时消息**：Outbox `pay:timeout` 状态 SENT、到期 00:04:53（15 分钟任意精度）；
  3. **即时事件**：mock 支付成功 → `pay-success` 事件被 order 消费（日志
     「支付成功事件收到 payOrderId=9244...」）→ 订单 order_status=1（PAID）；
  4. **链式定时**：支付成功自动排程 logistics-step 定时消息（到期 00:50:42）；
  5. **Canal CDC**：UPDATE 商品名 → canal 经 RocketMQ 投递 → ProductIndexConsumer
     消费（日志「canal 商品索引同步 type=UPDATE rows=1」）→ ES 文档同步更新。
- 阶段失败记录（保留）：初版在 NORMAL Topic 上直接发定时消息，被
  `message type not match` 拒绝；topics.json 手改 `NORMAL,DELAY` 引发 proxy
  `Enum.valueOf` 50001；均由「定时专用 Topic + 显式单值属性」方案根治，过程详见
  本节与上文「定时专用 Topic 的由来」。

## 未完成项

- 定时消息到期后的实际消费（关单/物流推进）于到期时刻复验——SENT+到期时间+
  timer wheel 机制已证明投递，消费侧骨架与即时事件共用同一容器模板。
- 三节点 DLedger 集群演练（kill 选主/零丢失）：编排与脚本已就绪，集群机器在
  部署窗口执行（与 ha-cluster.md 演练流程合并）。
- 线上 smartlect.cn 切换：待三批次完成后统一经 CI deploy 网关上线。
- `%RETRY%` broker 原生重试组未使用（我们自管回投节奏），行为差异已知。

## 启用与回滚

- 启用：`docker compose build` 无需（stock 镜像）——直接 `dev.sh infra-up`（init
  容器自动建 Topic）→ `dev.sh up`；集群按 cluster/README 的 build-rocketmq.sh 流程。
- 回滚：git revert 本批 → 恢复 rabbitmq 服务定义（git 历史中有完整 compose 段）→
  `docker compose up rabbitmq`（数据卷 `smartlect_rabbit` 若未删除即恢复旧队列）→
  重新 build+up。Outbox 新列对旧代码无影响（不读该列）。

## 关联代码版本

分支 main，本文件同日 commit（批次二）。
