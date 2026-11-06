# v4 评测集设计（2026-11-05 重冻）

> 状态：**场景已重新冻结（protocol `v4-2026-11-05`），标签 pending（人工/judge 0-3）**；
> v4 尚未替换 v3 门禁，也**不能**用于任何质量结论。
>
> **2026-11-04 的旧 v4 pilot（9 场景 ×3 trials，run 41771579066 等）结果作废**：
> 旧场景文件（protocol `v4-2026-11-04`，sha `f52ad089…`）存在 slot/昵称/文本矛盾/
> 负向不跨层等缺陷，本次已重冻，场景 sha 已变；旧 pilot 只能当作“运行链路验证”的历史记录，
> 不得与新场景的交付率/pass^k 混用或对外引用。

## 1. 本次重冻修了什么（审计 A4）

| # | 缺陷（旧版） | 修复（本版） |
|---|---|---|
| 1 | 选项阶段 `slot = 已收集选项数 + 1`，生成“我第 208 次来这座城市工作”、昵称 `V3场景租客208` 且重复 | 选项阶段只用占位 slot=1 算容量；选中后按最终顺序赋 `slot=seq`（1..40），昵称 `V4场景租客01..40`（唯一），自我介绍/室友期望同步使用最终序号 |
| 2 | 先按原始 tags 生成 `self_intro` 再 `_clean_tags`，出现“不养宠物…最近常做的事是养猫、撸猫”矛盾 | 先清洗 tags（`has_pet=无` 时移除养宠类标签、补中性标签），再用清洗后 tags 重建 `self_intro`/`moments`；文本自洽用 `data_consistency.assess_person` + 本地 fail-closed 规则双重校验 |
| 3 | 负向 8 个复制前 8 个正向，全是高容量层 | 负向固定从正向索引 `[0,5,10,15,20,25,30,35]` 派生（moment/intro 各 4），切分保证两族都跨容量层、跨性别 |
| 4 | `MANIFEST.json` 手工维护、无 pool digest / base SQL 指纹 / protocol 约束 | 由脚本生成：scenarios sha256、protocol、seed/as_of、pool `{source,members,approved,base_sql_sha256,pool_digest}`、`supply_additions`（计算值）、`labels{status,method}`、`created_at`；`--check` 只读复算 |
| 5 | 标签 pending 但没有落标签的工具/校验 | 新增 `eval/build_v4_labels.py`：`--from-csv` / `--from-judge` / `--check`，生成 `labels.json` 并更新 MANIFEST，不调用任何模型 API |
| 6 | 正向没有可执行的交付目标口径 | 每个正向加 `expect.target = min(8, eligible_unbounded)` 与固定 `target_rule`（见 §5） |

## 2. 规模与分层

| 项 | v3 | v4（本版） |
|---|---|---|
| 正向场景 | 8 | **40** |
| 负向/异常场景 | 2 | **8**（4 缺动态 + 4 缺自我介绍） |
| trials | 1 | **3（运行协议，不在场景文件里）** |
| 容量层 | 高 3 / 中 3 / 低 2 | **高 16 / 中 12 / 低 12** |
| 性别 | 4/4 | **20/20（目标达成）** |
| 门店 / 租期 | 8 / ≥4 | **19 个门店（seed 池 20 家）/ 5 个租期档全覆盖** |

## 3. 构造规则

- 场景来自种子数据 `deploy/mysql/sql/base/01-paringbot.sql`（900 名成员、841 已审核通过）；
- 每个场景是“门店 × 性别 × 租期档”格：容量 = `approved_candidates + 同性 + 租期档差<2 + 双向必须项`；
  - `eligible`（scoped）= 申请方门店范围内硬可匹配人数；
  - `eligible_unbounded` = 忽略门店范围后硬可匹配人数；
- 分层配额：高容量（≥8）16 个、中容量（4–7）12 个、低容量（1–3）12 个；
- 必须项计划：高容量“年龄+作息”；中容量交替加“门店/预算”；低容量交替加“预算/宠物”；
- 确定性：`seed=20261104`，`python3 eval/build_v4_scenarios.py` 可字节复现（无时间戳）；
- **slot 与容量奇偶**：v3 的 `_make_applicant` 会按 slot 奇偶改变整洁度（整洁/一般）与
  作息接受范围（偶数 slot 多接受“正常作息”），因此容量与 slot 奇偶有关。本版在选项阶段
  同时算 slot=1/2 两套容量，选中后按最终 `seq` 的奇偶取对应值，再重算一遍写入
  `expect.ex_ante_eligible/ex_ante_unbounded`，保证“档案 ↔ 记录容量”一致；
- **选择顺序**：先选中容量层（格子最少、最紧张），再高容量层，最后低容量层；层内按性别目标
  挑选（男目标数优先、再女），不足时任意性别补齐，所有格子全局去重；
- **负向派生**：从固定索引取 8 个正向场景，再在满足“两族各 4 个、都跨性别、都跨 ≥2 个容量层”
  的切法里选层分布最均衡的一种：moment 族来自 `V4_01/V4_06/V4_26/V4_31`，
  intro 族来自 `V4_11/V4_16/V4_21/V4_36`。负向档案复制来源申请方，只清空
  `moments` 或 `self_intro`，并把文本里的序号改写成自己的 slot（41–48），保持内部一致。

## 4. 覆盖矩阵（实际生成值）

| 维度 | 覆盖 |
|---|---|
| 门店 | 19 个（seed 池 20 家；徐家汇店未被本轮抽中） |
| 性别 | 男 20 / 女 20 |
| 租期 | 5 档全覆盖（1 / 7 / 13 / 14 / 5） |
| 容量 | 高 16 / 中 12 / 低 12 |
| 必须项 | age 40、schedule 40、store 6、budget 12、pet 6 |
| 负向 | moment 4 / intro 4；moment 来源跨 high/medium/low、男女；intro 同 |
| target | 8×31、7×1、6×1、5×1、4×5、3×1 |

详见自动生成的 `COVERAGE.md`（`build_v4_scenarios.py --write` 重写，`--check` 比对，不许手改）。

## 5. target 口径

- 每个正向场景：`expect.target = min(8, eligible_unbounded)`，
  `expect.target_rule = "min(8, eligible_unbounded)"`；
- 为什么不是 scoped：`eligible` 只统计“申请方门店偏好范围”内的人；当门店只是加分项
  （`store_required=加分`）时，真实可交付候选可以来自范围外，scoped 人数不是交付上限。
  `eligible_unbounded` 是硬规则下真正可匹配的人数，target 取它与 8 的较小值；
- `eval/report.py` 的 `_scenario_target` 优先读 `expect.target`，`analyze_pilot` 同口径回退；
- 这样 `target_attainment = min(delivered/target, 1)` 才是“交付覆盖”的正确分母，
  不再把“容量层 4 人却要交 8 人”误判为系统缺陷。

## 6. 数据质量与文本自洽

- 若 `has_pet=无`：从兴趣标签里删掉养宠类标签（养猫/撸猫/养狗/遛狗/养仓鼠/爬宠/养鱼/
  宠物摄影/猫咖/狗咖），用中性标签补到 3 个，再用清洗后标签重建 `self_intro`/`moments`；
- 本版实际清洗 4 个场景（`V4_08/V4_18/V4_28/V4_38`，各移除 3 个养宠类标签，共 12 个）；
- 文本级 fail-closed 校验（本仓库 + CI 双份规则）：
  - 自由文本同时出现“养猫/撸猫/…活动词”与“不养宠物/过敏”表述 → 失败；
  - `has_pet=无` 的档案兴趣标签含养宠类标签 → 失败；
  - 调用 `eval/human_eval/data_consistency.assess_person`，要求所有正向 `score > 0`；
  - 顺手规范化模板里相邻句号重复（“。。”）——v3 冻结文本有该历史瑕疵，v4 新文本不再保留；
- 申请档案全部由固定模板按格子统计量生成，不复制任何种子成员文本。

## 7. MANIFEST 与冻结

`eval/frozen/v4/MANIFEST.json` 由 `build_v4_scenarios.py --write` 生成，记录：

- `version` / `protocol_version`（`v4-2026-11-05`）/ `seed` / `as_of`；
- `scenario_count=48` / `positive_count=40` / `negative_count=8` / `deliver_count=8`；
- `scenarios {file, sha256}`：`scenarios.json` 的字节 sha256；
- `labels {status: "pending", method: "human/judge 0-3"}`（标签生成后由标签工具改为 ready 并记录 sha256）；
- `pool {source, members, approved, base_sql_sha256, pool_digest}`：base SQL 字节指纹由
  `eval/lib/freeze.py` 计算，pool digest 覆盖全部成员/偏好字段（证明候选池未被改写）；
- `supply_additions`：扫描 `deploy/mysql/sql/eval` 得到的供给写语句数，必须为 0；
- `created_at`：冻结时间（不参与 `--check` 的比较，其余字段逐项复算）。

`--check` 只读校验：`build()` 输出与 frozen 字节一致、MANIFEST sha 一致、40+8、层配额、
无重复格子、target 口径、全部正向文本自洽、负向覆盖、COVERAGE 未被手改；失败退出码 1。
`eval/check_v4_freeze.py` 是独立守卫（CI 调用），额外校验 pool 指纹与 labels 状态。

## 8. 标签（pending）

- **不使用 heuristic gold**；v4 标签必须来自人工或经校准的 judge：
  - 相关性分级 0–3（0=硬冲突，1=勉强，2=合适，3=非常合适）；
  - 覆盖全部 40 个正向场景；每条至少记录 `pair_id/applicant/candidate/delivered/score/annotator`；
- 工具：`python3 eval/build_v4_labels.py --from-csv labels.csv --write` 或
  `--from-judge judge.json --write`；`--check` 只读校验 schema/覆盖/分布；
- 标签文件 `eval/frozen/v4/labels.json` 与场景文件分开冻结，MANIFEST 记录其 sha256；
- **标签 pending 期间**：v4 只用于流程/成本/稳定性试点，不能作为质量门禁，也不能对外声称质量提升。

## 9. 运行协议

- 先做 **12 个场景 ×3 trials** 的方法验证（成本约 1/4），确认 pass^k 与 CI 可用；
- 再全量 40×3；每次运行记录 MANIFEST hash、模型配置、artifact；
- 对照候选不进入生产供给，不写 eval profile；
- **旧 pilot 结果作废**（场景已变），重跑后以新场景 sha 为准。

## 10. 验收标准

1. `python3 eval/build_v4_scenarios.py --write` 后 `--check` 通过；
2. `python3 eval/check_v4_freeze.py` 通过；
3. `python3 -m unittest eval.tests.test_v4_scenarios -v` 全绿（含 v3 冻结字节不变）；
4. MANIFEST 的 `scenarios.sha256` 与 frozen 文件字节一致且可复现；
5. 人工/judge 标签覆盖 40 正向、记录 sha256 后，才允许讨论把 v4 接入门禁。

## 11. 明确不做

- 不按结果补供给；
- 不用 heuristic 标签伪装成 v4 gold；
- 不在 v4 标签完成前对外声称“质量提升”；
- 不复用旧 pilot 的“9 场景”子集做新结论。
