# MQ 拓扑改名 runbook（growth → assistant）

服务目录改名 `growth/` → `assistant/` 的同时，MQ durable 拓扑做了两处改名：

| 旧名 | 新名 | 归属 |
|---|---|---|
| `smartlect.growth.commerce.queue` | `smartlect.assistant.commerce.queue` | Java 声明，Python worker 消费（成交账本） |
| `smartlect.user.growth.exchange` / `.queue` / `.dead.queue` / 两个 routing key | `smartlect.user.member.*` | Java 声明+发布（order）+消费（user，订单成长值） |

派生队列：重试拓扑会为每个 RETRYABLE 队列生成 `{queue}.retry.{1,2,3}`，旧 `user.growth.queue` 的派生队列随迁移一并删除。

不变的层（有意保留，历史命名）：
- 数据库名 `smartlect_growth`（MySQL/Postgres）与库账号；
- `.env` 环境变量前缀 `SMARTLECT_GROWTH_*`（`SMARTLECT_GROWTH_PORT`、`SMARTLECT_GROWTH_MYSQL_PASSWORD` 等）；
- 幂等键值 `order:growth:<orderId>`（成长值事件幂等键，线上已写入）。

## 为什么安全

- **commerce.outcome**：发布走 `TransactionalMqSender`（本地消息表 outbox），投递失败有 5s 补投；消费端（Python worker）按 `commerce_event.event_id` 唯一键幂等，重复投递无害。exchange 名未变（`smartlect.commerce.outcome.exchange`），只有队列与绑定换了名字——Java 新版启动时声明新队列并绑定，消息从部署那一刻起进新队列。
- **user.member（成长值）**：发布方 order 与消费方 user 同批部署（common 常量共享），无跨版本窗口；消费幂等靠 `user_order_growth` 表主键，重复投递无害。
- **残留消息**：改名前落在旧队列里的消息必须搬空再删队列，脚本用 shovel 搬运到新队列（消费端幂等兜底）。

## 生产切换步骤（T 窗口）

1. **前置**：新版代码已构建（`assistant/` 目录、Java 新常量）；`run/processes.json` 与 systemd/compose 单元已按新服务名更新；`.env` 不动。
2. **停旧进程**：`scripts/runtime.py stop`（按 processes.json 停全部），保证发布方先停，避免旧代码继续向旧交换机发布。
3. **启动新版**：`scripts/dev.sh up`（或 runtime.py apps-up）。Java 启动即声明新拓扑；`assistant-worker` passive 声明新队列消费。
4. **搬运残留**：`RABBIT_CONTAINER=rabbit-c1 bash scripts/migrate-mq-topology.sh`（先 `--dry-run` 看残留量）。若 shovel 子命令在该 rabbitmqctl 版本不可用，用一次性 Python 搬运：pika 从旧队列 `basic_get` 循环取出、按原 routing key 发布到新队列、直到取空。
5. **删旧拓扑**：脚本自动删除旧队列/retry 派生队列/旧交换机。
6. **验证**：
   - `run/cloud/recon.sh` 对账 Java 支付 vs assistant 账本金额一致；
   - 下一笔确认收货订单的成长值落库（`user_order_growth` 有新行）；
   - Prometheus `assistant-api` / `assistant-worker` 目标 up，Grafana 面板有数据。

## 回滚

回滚代码即可：旧常量指向旧名字，Java 启动会重新声明旧拓扑并恢复消费；被删除前未搬运的消息若已丢失，靠 outbox 重投/业务幂等对账补偿（recon.sh 会暴露缺口）。因此步骤 4 必须在步骤 5 之前完成且退出码为 0。
