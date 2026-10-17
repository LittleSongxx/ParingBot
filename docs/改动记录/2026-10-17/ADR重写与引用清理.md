# ADR 重写与引用清理

## 需求

旧 ADR 一文多主题、混入批次/步骤/历史实现，且被代码引用 100+ 次后形成“文档比代码更难维护”的状态。重写为一篇一个决策、编号 0001–0010，并清理全仓引用；不能改已应用的 Flyway 迁移（校验和不可变）。

## 变更

- 新增 `docs/adr/0001`–`0010`：一致性、订单写路径、库存条件更新、可靠消息、订单状态机、退款 Saga、数据边界、鉴权/内部调用、可观测性与安全、热点库存演进。
- `docs/adr/README.md`：索引、状态、写作规则、旧→新编号映射；`docs/adr/legacy-map.md`：旧 0001–0023 的归属，assistant 相关只指向 `assistant/README.md`/测试，不新增 AI ADR。
- 活跃 Java 注释/文档中的旧编号改为新编号；历史叙述直接删旧号；`docs/改动记录/`、`assistant/`、`db/migration/` 中的历史引用保留。
- 新增 `scripts/check_adr_refs.py`：扫描 `ADR-\d{4}`，无法解析到新 ADR 或 legacy-map 即失败；允许历史证据与不可变迁移。
- 迁移文件不改：清理脚本一度改了 V3/V4 的 SQL 注释，导致本地 Flyway 校验和失败；已 `git checkout --` 恢复全部迁移，并把“迁移是不可变历史”写进检查脚本豁免。

## 关键源码/文档

- `docs/adr/README.md`、`docs/adr/legacy-map.md`、`docs/adr/0001`–`0010`
- `scripts/check_adr_refs.py`
- ADR-0009 补充了 mock 支付 HMAC/nonce/流水对账；ADR-0010 从 Proposed 改为 Accepted（默认关闭）。

## 验证

- `python3 scripts/check_adr_refs.py` 通过：活跃引用全部解析；仅 `docs/adr/README.md`、`legacy-map.md` 与历史记录保留 LEGACY 命中。
- `mvn -Pintegration verify` 能通过 Flyway 真库迁移（order V1–V7、pay V1–V5）。
- ADR 图片/链接检查见 `docs/verification/` 与本次全量验证。

## 未完成/边界

- 旧 ADR 原文不恢复；`legacy-map` 只做索引，不保留过时结论。
- 检查脚本只校验编号引用，不校验 ADR 内容与代码事实是否一致；这部分靠实现、测试和改动记录。

## 关联版本

工作区基于 `cc73bba`，本次改动未提交。
