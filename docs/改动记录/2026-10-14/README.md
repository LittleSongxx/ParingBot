# 2026-10-14 改动索引

本日主题：三批次中间件改造（IK/RocketMQ/Dubbo）在 ECS 三节点集群上线——批次三 Dubbo 在
Linux 服务器上全链路跑通（本机 WSL2 未通过的最后一环）。

| 功能点 | 状态 |
| --- | --- |
| [ECS集群部署.md](ECS集群部署.md) | node1 全栈上线（IK/RocketMQ 5.3/Dubbo 3.3），线上完整闭环实证：下单(Dubbo)→15min 定时消息→支付事件→PAID→物流 1h 定时链→SHIPPED；部署过程修复 9 项部署缺陷（全部入库）；DLedger 多副本与从机应用副本两个未竟项如实记录（MQ 暂单机收敛） |
