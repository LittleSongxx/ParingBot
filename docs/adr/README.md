# Smartlect ADR 索引

本目录记录“已经做过的、会影响后续实现的取舍”。目标是让新读者理解为什么这样设计，而不是把历史批次、实施步骤和验证日志堆进来。

## 写作规则

- 一篇 ADR 只回答一个决策；标题写成决策陈述。
- 状态只用 `Proposed / Accepted / Superseded / Deprecated`。
- 正文只保留：背景（约束/力量）、决策、备选方案、后果（正/负/风险）、何时重审、证据。
- 不写批次号、Step、旧实现对比、硬编码阈值；配置默认值放代码/配置，证据放测试或 `eval/verification/`。
- “不做 X”必须写清边界、证据和重审条件。
- 决策变化时新建 ADR 并 `Supersedes` 旧文，不修改旧文正文。
- 代码注释只在引用“稳定决策”时写 `ADR-000x`；临时实现细节引用测试/配置，不引用 ADR。

## 当前 ADR

| 编号 | 决策 | 状态 | 范围 |
| --- | --- | --- | --- |
| [0001](0001-transaction-consistency.md) | 交易一致性采用本地事务 + Outbox | Accepted | order / stock / coupon / pay |
| [0002](0002-order-write-path.md) | 订单写路径采用五阶段与短本地事务 | Accepted | order |
| [0003](0003-stock-conditional-update.md) | 库存扣减采用条件更新 + 变更账本 | Accepted | stock |
| [0004](0004-reliable-messaging.md) | 可靠消息采用 Outbox + 消费幂等 + 延迟驻留 | Accepted | common / order / pay / coupon |
| [0005](0005-order-state-machine.md) | 订单状态机用 CAS，支付生命周期另加锁 | Accepted | order |
| [0006](0006-refund-saga.md) | 退款采用持久化 Saga，退券只在整单全退 | Accepted | order / pay / stock / coupon |
| [0007](0007-data-boundaries.md) | 每服务一个 schema，读模型与交易事实分离 | Accepted | 全部业务服务 |
| [0008](0008-auth-and-internal-calls.md) | 会话、权限与内部调用分三层校验 | Accepted | gateway / common / user / admin |
| [0009](0009-observability-and-security.md) | 可观测性与安全基线先做“能定位” | Accepted | gateway / common / 各服务 |
| [0010](0010-hot-stock-evolution.md) | 热点库存原型默认关闭，DB 仍是事实源 | Accepted（默认关闭） | stock |

## 旧编号映射

旧 ADR 在 2026-10-16 已整体下线；它们混合了批次、实施步骤和临时取舍，不能继续作为稳定决策引用。旧编号不再复用，映射如下：

| 旧编号 | 旧主题 | 去向 |
| --- | --- | --- |
| ADR-0001 | final-integration | 退役；assistant 历史 |
| ADR-0002 | decision-compile | assistant 历史（见 `assistant/README.md`） |
| ADR-0003 | agent-control-plane | 退役；思想并入旧 0002/0013 |
| ADR-0004 | shopping-retrieval-observability | assistant 历史 |
| ADR-0005 | ai-asset-ops-surface | 退役 |
| ADR-0006 | remove-seata | → 0001 |
| ADR-0007 | hybrid-retrieval-es-qdrant | assistant 历史 |
| ADR-0008 | retire-recommendation-line | 退役 |
| ADR-0009 | agent-runtime-choices | assistant 历史 |
| ADR-0010 | subagent-dispatch | assistant 历史 |
| ADR-0011 | sa-token-migration | → 0008 |
| ADR-0012 | echomind-patterns | assistant 历史 |
| ADR-0013 | guard-chain-layering | assistant 历史 |
| ADR-0014 | context-prefix-stability | assistant 历史 |
| ADR-0015 | memory-bitemporal-conflicts | assistant 历史 |
| ADR-0016 | rocketmq-migration | → 0004 |
| ADR-0017 | dubbo-migration | → 0008 |
| ADR-0018 | order-consistency-fixes | 按上下文拆到 0001 / 0002 / 0003 / 0004 / 0007 |
| ADR-0019 | order-structure-refactor | → 0002 |
| ADR-0020 | refund-coupon-return | → 0006 |
| ADR-0021 | observability-and-dynamic-rules | → 0009 |
| ADR-0022 | security-hardening | 按上下文拆到 0007 / 0008 / 0009 |
| ADR-0023 | reliability-and-cleanup | 按上下文拆到 0001 / 0004 / 0009 |

旧编号的完整主题与去向见 [legacy-map.md](legacy-map.md)。代码/文档中不再新增旧编号引用；assistant 里的历史引用只做映射，不重写 AI 决策。

## 校验

```bash
python3 scripts/check_adr_refs.py
```

脚本会扫描全仓 `ADR-\d{4}` 引用：必须能解析到本目录的 `000x-*.md`，或出现在 `legacy-map.md` 的旧编号表中。
