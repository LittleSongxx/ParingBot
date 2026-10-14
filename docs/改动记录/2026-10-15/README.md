# 2026-10-15 改动索引

本日主题：昨夜七批次（ADR-0018~0023）交付后全面自查——真库实证发现并修复 2 个致命 + 2 个高危 + 1 个中等问题，新增 Outbox SQL 真库回归网；同日凌晨推送全部改动并在三台 ECS 完成线上部署验证（CI 解锁三修 + 部署期六缺陷修复 + 定时消息时间轮驻留）。

| 功能点 | 状态 |
| --- | --- |
| [七批次自查修复.md](七批次自查修复.md) | 完成：①Outbox 认领 SQL MILLISECOND 方言错误（生产必瘫，容器实证 1064）改 MICROSECOND + 新增 OutboxLeaseSqlIT 真库回归；②网关 Sentinel 默认部署丢规则/BlockHandler（插入错位）恢复 init 结构；③Dubbo 规则数据源被 loadRules 覆盖；④gallery 退款复核 403 回归（V4 补 TRIAL_OPERATOR 授权）；⑤发券时间字段裸 500 转业务异常。全量单测+IT 复测绿 |
| [七批次线上部署验证.md](七批次线上部署验证.md) | 完成：三机部署上线（终版 `8234d2f`）。CI 解锁三修（assistant aiohttp 锁漏项/预算测试漏同步/代码卫生）；部署期六缺陷：A sync 覆盖节点特有 env（ES/QDRANT 回 127.0.0.1 致 product 健康超时）、B Sentinel Nacos 数据源裸构造 403（挂接成功规则为空）、C xxl-job-admin OOMKilled 停摆 19 小时（全部 @XxlJob 任务静默停摆）、D **定时消息 24h 时间轮上限——7 天确认收货消息必被拒必转 EXHAUSTED（本项目级缺陷，Outbox 驻留修复）**、E **node1 根分区被 14G 历史暂存 JAR 撑满→MySQL 临时表分配失败→冒烟永久挂起、部署撞 job 超时（三层修复：回收/截止/门禁；含冒烟死锁自伤与 terminate-first 迭代）**、F 副本 xxl-job 执行器从未注册（调度中心地址默认 127.0.0.1）。终态：三机 5~9 服务健康、Nacos/执行器注册达标、8 库 Flyway、13 索引、站点与 X-Trace-Id、驻留生产验证（next_retry_time=10-20 07:34:50）。证据 `eval/verification/2026-10-15/` |
