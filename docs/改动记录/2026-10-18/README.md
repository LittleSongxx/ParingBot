# 2026-10-18 改动索引

| 功能点 | 状态 |
| --- | --- |
| [ECS三节点部署与压测.md](ECS三节点部署与压测.md) | 完成：部署 `d1365cc` 到 node1 并同步 node2/node3；补 HMAC 密钥、数据库备份、V7/V5 迁移、18 个调度任务；浏览/订单压测与 JVM、限流、MySQL 连接数调优。详见 `docs/verification/ecs-loadtest.md`。最终部署 run `39053891614` 成功；深度排查修复了 node3 热路径、RocketMQ proxy/namesrv OOM、loadgen seed、对账口径与 systemd 停止超时；整机重启后已核对三节点恢复与 Redis Sentinel 故障转移。 |
