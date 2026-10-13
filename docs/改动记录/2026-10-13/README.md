# 2026-10-13 改动索引

本日主题：中间件栈对齐主流大厂选型的三批次改造（用户决策：RocketMQ 5.x 任意定时消息
路线、分三批交付、集群编排同步切换；Sa-Token 经评估不换）。

| 功能点 | 状态 |
| --- | --- |
| [IK分词切换.md](IK分词切换.md) | 批次一：ES 中文分词 smartcn/cjk → ik_max_word。澄清两个历史误记（商品索引 smartcn_zh 实为 standard tokenizer；插件从未随容器安装、线上按 cjk 建）；自建镜像 + compose 切 build；商品索引 87469 条与知识索引 store scope 34 chunks 以 IK 重建；双侧全量测试通过；support-eval 检索面离线隔离对比 **Recall@5 0.9783→0.9855、MRR 持平、无回归题** |
| [RabbitMQ迁移RocketMQ.md](RabbitMQ迁移RocketMQ.md) | 批次二：RabbitMQ 4.2 → RocketMQ 5.3（gRPC 5.0.8 客户端）。6 交换机/45 队列收敛为 6 Topic+Tag；5 组 TTL+死信延迟队列改任意精度定时消息（定时专用 Topic，规避 5.3.2 message.type 多值坑）；27 个重试派生队列由容器统一定时回投取代；消费骨架上收容器模板；Canal 切 rocketMQ 直投；单机三容器+Topic 预建 init、集群 DLedger 三副本全套编排。全量单测绿 + 端到端实证（下单→定时消息 SENT→支付事件消费 PAID→链式物流排程→Canal→ES 同步） |
| [OpenFeign迁移Dubbo3.md](OpenFeign迁移Dubbo3.md) | 批次三：OpenFeign → Dubbo 3.3.6。7 契约 59 方法 + 7 provider（委托 internal controller）+ Support 门面内部换 @DubboReference（签名不变测试零改动）+ 双端鉴权 Filter（SPI attachment 传令牌）+ ThreadLocal 委托用户通道 + Sentinel Dubbo 资源名 + 15 DTO 序列化；全量单测绿、provider 注册与鉴权已通；**本机 WSL2 联调卡 Dubbo Netty 网络层未通（如实记录，不部署线上），排查方向见文档** |
