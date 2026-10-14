# 2026-10-15 改动索引

本日主题：昨夜七批次（ADR-0018~0023）交付后全面自查——真库实证发现并修复 2 个致命 + 2 个高危 + 1 个中等问题，新增 Outbox SQL 真库回归网。

| 功能点 | 状态 |
| --- | --- |
| [七批次自查修复.md](七批次自查修复.md) | 完成：①Outbox 认领 SQL MILLISECOND 方言错误（生产必瘫，容器实证 1064）改 MICROSECOND + 新增 OutboxLeaseSqlIT 真库回归；②网关 Sentinel 默认部署丢规则/BlockHandler（插入错位）恢复 init 结构；③Dubbo 规则数据源被 loadRules 覆盖；④gallery 退款复核 403 回归（V4 补 TRIAL_OPERATOR 授权）；⑤发券时间字段裸 500 转业务异常。全量单测+IT 复测绿 |
