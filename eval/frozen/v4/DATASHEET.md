# v4 评测集 Datasheet

## 基本信息

- 版本：v4（2026-11-05 重冻），协议 `v4-2026-11-05`，seed `20261104`，as_of `2026-11-04`；
- 规模：40 正向 + 8 负向；每个正向交付要求 8 人；
- 生成命令：`python3 eval/build_v4_scenarios.py --write`（确定性、无时间戳，可字节复现）；
- 场景文件：`eval/frozen/v4/scenarios.json`（sha256 见 `MANIFEST.json`）；
- 覆盖报告：`eval/frozen/v4/COVERAGE.md`（自动生成，不许手改）；
- 设计说明：`eval/frozen/v4/DESIGN.md`。

## 数据来源

- 供应池：`deploy/mysql/sql/base/01-paringbot.sql`（900 成员、900 偏好、841 已审核通过、20 家门店）；
- 申请人档案/偏好：由 `build_v4_scenarios.py` 按固定模板从格子统计量生成，**不复制任何种子成员文本**；
- 不含真实用户隐私数据；所有 profile/self_intro/moments 均为合成评测数据；
- 离线解析，不连数据库、不调模型。

## 构造与版本差异

- 场景是“门店 × 性别 × 租期档”格，容量按双向硬规则计算（同性、租期档差<2、双方必须项）；
- 正向 40 个按容量分层抽样：高 16 / 中 12 / 低 12；性别 20 男 / 20 女；19 家门店、5 个租期档；
- **slot/昵称**：选项阶段占位 slot=1，选中后按最终顺序赋 `slot=seq`（1..40），
  昵称 `V4场景租客01..40` 唯一；负向 slot=41..48。旧版的“第 208 次”“V3场景租客208 重复”已修复；
- **文本清洗**：`has_pet=无` 时移除养宠类兴趣标签并用中性标签补齐，再用清洗后的标签重建
  `self_intro`/`moments`，消除“不养宠物…最近常做的事是养猫、撸猫”矛盾（实际清洗 4 个场景、12 个标签）；
- **负向**：8 个从正向索引 `[0,5,10,15,20,25,30,35]` 派生（moment/intro 各 4），
  两族都跨容量层、跨性别；只清空 `moments` 或 `self_intro`，并把序号改写成本场景 slot；
- **target**：每个正向 `expect.target = min(8, eligible_unbounded)`，`target_rule` 固定；见 DESIGN §5；
- **旧 pilot 作废**：2026-11-04 的 v4 pilot（9 场景 ×3 trials）基于旧场景文件（protocol
  `v4-2026-11-04`，sha `f52ad089…`），本版场景已重冻、sha 不同，旧交付率/pass^k 不得与新场景混用。

## 污染控制

- 场景/标签/运行分离：eval profile 只有 base 数据，不补供给；
  MANIFEST 的 `supply_additions` 为扫描 `deploy/mysql/sql/eval` 的计算值（本版 0）；
- 确定性采样：seed 固定，重复构建字节一致；`--check` 复算并比对；
- 防定向供给：场景账号 `TEST_SCENARIO_V4_*` 不写入任何 SQL；base SQL 与候选池都有指纹
  （`base_sql_sha256`、`pool_digest`），候选池被改写会立刻被 `check_v4_freeze` 发现；
- 冻结：`scenarios.json` 的 sha256 记录在 `MANIFEST.json`；标签完成后经
  `build_v4_labels.py --write` 单独冻结并记录 sha256；
- 自动生成的 `COVERAGE.md` 参与 `--check` 比对，手改即失败。

## 已知限制

- 标签**尚未生成**（`labels.status=pending`），**当前不能用于质量结论或质量门禁**；
- 门店覆盖 19/20（徐家汇店未被本轮抽中；其余 19 家覆盖）；性别 20/20 已达成；
- 档案为合成数据；虽然本版修复了养宠标签与文本矛盾，仍不包含真实用户行为/在线反馈；
- 负向只覆盖两类 readiness（缺动态、缺自我介绍），不覆盖 API 异常/超时等运行失败；
- 2026-11-04 旧 pilot 结果作废，需在新场景上重跑。

## 预期用途

- 评测方法验证（pass^k、CI、target attainment、judge 校准）；
- 面试展示“评测集如何设计、如何分层、如何防污染、如何 fail-closed 冻结”；
- 不作为生产质量证书。

## 维护

- 修改生成器必须重跑 `python3 eval/build_v4_scenarios.py --write`、
  `python3 eval/build_v4_scenarios.py --check`、`python3 eval/check_v4_freeze.py` 与
  `python3 -m unittest eval.tests.test_v4_scenarios -v`，并更新 MANIFEST/协议版本；
- 标签变更必须通过 `build_v4_labels.py` 重新生成，禁止手改 `labels.json`；
- v3 冻结集（`eval/frozen/v3/*`）必须保持字节不变：v3 生成器只允许加 opt-in 参数，
  默认输出由 `test_freeze.py` / `test_v4_scenarios.py` 断言；
- v4 标签未完成前，CI 只校验场景/指纹，不接质量门禁。
