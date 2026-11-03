# ParingBot 质量政策（Quality Policy）

> 目的：定义“什么算质量证据、什么不算”，以及冻结集、oracle、变更与对外口径的纪律。
> 适用：所有涉及匹配质量、评测、发布说明、对外材料的改动。

## 1. 证据分级

| 级别 | 类型 | 可信度 | 用途 |
|---|---|---|---|
| E0 | 工程事实（CI 通过、运行完成、单测/E2E、规则代码） | 高 | 可以对外 |
| E1 | 冻结协议测量（v3 交付率/完成率/成本/延迟，固定 oracle/数据/环境） | 中高 | 可对内部/发布说明，需附四要素 |
| E2 | 独立 judge（跨模型族、成对/校准） | 探索性 | 只能作为补充信号 |
| E3 | 人工盲评（双人 rubric + kappa ≥0.6） | 高（质量真值） | 唯一可支撑“匹配质量”结论 |
| X | heuristic agreement / NDCG / 交付数单指标 / 旧 RESULTS 数字 | 不可用 | 只能做回归监控，禁止对外 |

## 2. 冻结集规则

1. `eval/frozen/v3/` 为只读资产：`scenarios.json`、`labels.json`、`MANIFEST.json`、`BASELINE.json`。
2. 任何修改必须走“重基线”流程：新版本号 + MANIFEST 重算 + 变更说明 + 人工 review；
   `check_freeze.py` 在 CI 中 fail-closed。
3. 禁止对 v3 任何场景补候选供给、改候选文本、按场景改规则/排序/阈值。
4. `deploy/mysql/sql/eval/` 只允许空目录/README；出现任何 `member_profile`/`roommate_preference`
   写语句即失败。
5. 新 holdout 迭代：v4 只能新建、不得修改 v3；新集必须在场景定义前生成供给池。

## 3. Oracle 规则

- frozen labels 由 `build_frozen_labels.py` 从仓库种子 SQL + 场景离线生成，版本 `heuristic-offline-v1`。
- 它是**规则基线，不是真值**；只用于 `heuristic_agreement_*`（监控，永不作为质量门禁）。
- CI 只读、不重算；重算只能离线、显式升版本、记录 diff。
- 禁止 consensus/Borda 等“同源多评分器”冒充独立验证（已删除）。

## 4. 指标口径

| 指标 | 门禁 | 口径 |
|---|---|---|
| delivery_rate | 是（相对 BASELINE） | delivered/requested；按场景均值 + bootstrap CI |
| completion/failures | 是 | 非“已完成” run；交付不足不算失败，但纳入 delivery |
| safety errors | 是 | PII/secret/承诺/注入（error 阻断，warning 报告） |
| cost | 发布模式是 | 真实单价必填；无单价必须报 unknown，禁止 0.0 |
| judge | 发布模式（观察期后） | 独立模型族；同模型拒绝；pairwise 需交换位置校准 |
| human | 对外质量声称必填 | 双人盲评 + kappa ≥0.6 |
| heuristic_agreement/NDCG | 否 | 按 delivered_rank；precision 分母=requested；NDCG 对短交付补零 |

## 5. 变更分类与提交纪律

| 类别 | 例子 | 要求 |
|---|---|---|
| data | SQL 种子/供给/迁移 | 与代码/评测分开提交；不得同时改标签 |
| code | backend/frontend | 常规 review + 测试 |
| eval | eval/、workflow、冻结集 | 变更即 RFC；冻结集走 MANIFEST 升版 |

红线：
- 禁止给 holdout/v3 补供给；
- 禁止“补供给 + 重算标签”同批；
- 禁止跨环境（CI 冷库 vs 本地暖库）或跨 oracle 版本横比；
- 禁止用 heuristic/NDCG/交付数单独作为质量门禁或对外数字；
- 禁止本地单次 8/8 后直接合入评测/排序/检索改动。

## 6. Artifact 必须字段

每次评测 artifact 至少包含：
`code_commit`、`labels_hash`、`scenarios_hash`、`suite`、`db_profile`、`model_configs`（脱敏）、
`MATCH_TIMEOUT_SECONDS`、`warm_portraits`、`n/trials`、`prices`、生成时间。
缺任一字段的实验报告不得作为发布依据。

## 7. 对外口径

**可声称**：可运行、可复盘、硬规则代码强制 + 单测/E2E、eval 工具链与冻结协议存在。
**不可声称**：匹配准确率、Precision/NDCG 质量、holdout 泛化、内容质量达标、安全无风险、
温度 0 可复现、成本可控（除非当次 artifact 有真实成本）。

## 8. 已知未解决缺陷（Open Defects，需产品决策）

1. 真实供给流动性不足（种子池结构问题；不得用评测补数据掩盖）。
2. 候选软期望文本被当硬冲突（S36 类）；审核官误拒无代码兜底，只复核对“通过”。
3. 并发/多用户：单进程 BackgroundTasks，无队列/重试，未做并发验证。
4. 内容质量（summary/画像/解释）未进入人工 rubric 流程。
5. 安全：真实 prompt injection/越权对抗测试缺失；隐私仅日志脱敏。
6. 运行不可完全复现：未保存每次运行使用的 Prompt 内容/版本与完整模型参数快照。

## 9. 发布门禁（摘要）

见 `docs/release-checklist.md`：CI 三件套、freeze-guard、eval unittest、v3 verify（发布模式含 judge/cost）、
人工抽检。任何一项缺失即不得发布质量结论。
