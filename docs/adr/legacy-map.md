# 旧 ADR 映射与退役说明

2026-10-16 之前的 ADR 已整体删除；本文件只保留“旧编号 → 新决策/退役”的索引，避免代码和历史文档继续指向不存在的文件。

旧 ADR 的共同问题：一个编号混多个主题、把批次/Step/旧实现对比写进正文、把临时取舍写成永久禁令、正文与后记冲突。新 ADR 不再沿用这些编号，也不恢复旧文。

## Java 后端

| 旧编号 | 主题 | 处置 | 新 ADR |
| --- | --- | --- | --- |
| ADR-0006 | 移除 Seata，改本地事务 + Outbox | Superseded | 0001 |
| ADR-0011 | Sa-Token 四步迁移 | Superseded | 0008 |
| ADR-0016 | RabbitMQ → RocketMQ、延迟消息/Outbox 列 | Superseded | 0004 |
| ADR-0017 | OpenFeign → Dubbo3、内部 HTTP 双通道 | Superseded | 0008 |
| ADR-0018 | 订单一致性修复（孤儿单/库存回补/支付对账/claim-first/幂等/索引） | Split | 0001 / 0002 / 0003 / 0004 / 0007 |
| ADR-0019 | 订单结构重构（门面 + 三领域服务 + 短事务 + 秒杀统一） | Superseded | 0002 |
| ADR-0020 | 整单全额退返券 | Superseded | 0006 |
| ADR-0021 | Trace/MDC/脱敏/分页/校验 + Sentinel/CORS | Split | 0009 |
| ADR-0022 | 登录锁/枚举缓解/权限粒度/生产校验/SKU 指纹 | Split | 0007 / 0008 / 0009 |
| ADR-0023 | Outbox DB 时钟、Sentinel/CORS、死代码卫生 | Split | 0001 / 0004 / 0009 |

## Assistant / 已退役

以下旧 ADR 属于非 Java 后端范围，或已被后续实现取代。本次不重写 AI 决策；只保留映射，避免代码注释出现悬空编号。

| 旧编号 | 主题 | 处置 |
| --- | --- | --- |
| ADR-0001 | final-integration | 退役 |
| ADR-0002 | decision-compile | assistant 历史；见 `assistant/README.md` |
| ADR-0003 | agent-control-plane | 退役 |
| ADR-0004 | shopping-retrieval-observability | assistant 历史 |
| ADR-0005 | ai-asset-ops-surface | 退役 |
| ADR-0007 | hybrid-retrieval-es-qdrant | assistant 历史 |
| ADR-0008 | retire-recommendation-line | 退役 |
| ADR-0009 | agent-runtime-choices | assistant 历史 |
| ADR-0010 | subagent-dispatch | assistant 历史 |
| ADR-0012 | echomind-patterns | assistant 历史 |
| ADR-0013 | guard-chain-layering | assistant 历史 |
| ADR-0014 | context-prefix-stability | assistant 历史 |
| ADR-0015 | memory-bitemporal-conflicts | assistant 历史 |

## 代码引用处理

- Java 代码里的活跃旧编号已按上下文改到 0001–0009；历史叙述直接删除旧编号。
- Assistant 代码里的旧编号不再指向不存在的文件；保留的引用只能通过本文件解析，不新增 AI ADR。
- `scripts/check_adr_refs.py` 会检查每个引用：要么是新 ADR 文件，要么是本文件中的旧编号；否则失败。
