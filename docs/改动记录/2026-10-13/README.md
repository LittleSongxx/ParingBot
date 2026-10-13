# 2026-10-13 改动索引

本日主题：中间件栈对齐主流大厂选型的三批次改造（用户决策：RocketMQ 5.x 任意定时消息
路线、分三批交付、集群编排同步切换；Sa-Token 经评估不换）。

| 功能点 | 状态 |
| --- | --- |
| [IK分词切换.md](IK分词切换.md) | 批次一：ES 中文分词 smartcn/cjk → ik_max_word。澄清两个历史误记（商品索引 smartcn_zh 实为 standard tokenizer；插件从未随容器安装、线上按 cjk 建）；自建镜像 + compose 切 build；商品索引 87469 条与知识索引 store scope 34 chunks 以 IK 重建；双侧全量测试通过；support-eval 检索面离线隔离对比 **Recall@5 0.9783→0.9855、MRR 持平、无回归题** |
| 批次二：RabbitMQ → RocketMQ 5.x | 进行中（含 Canal serverMode 切换、compose 单机三容器、cluster 三节点 DLedger 同步改造） |
| 批次三：OpenFeign → Dubbo 3 | 未开始（契约层 7 api 模块、双通道保留 HTTP /internal 给 assistant、Sentinel Dubbo 规则） |
