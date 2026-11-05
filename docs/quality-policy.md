# ParingBot 质量政策（Quality Policy，2026-11-05 审计后修订）

> 目的：定义“什么算质量证据、什么不算”，以及冻结集、oracle、门禁、变更与对外口径的纪律。
> 适用：所有涉及匹配质量、评测、发布说明、对外材料的改动。

## 1. 证据分级

| 级别 | 类型 | 可信度 | 用途 |
|---|---|---|---|
| E0 | 工程事实（CI 通过、运行完成、单测/E2E、规则代码） | 高 | 可以对外 |
| E1 | 冻结协议测量（v3 交付/target 归一/完成率/成本/延迟，固定 oracle/数据/环境） | 中高 | 可对内部/发布说明，需附四要素 |
| E2 | 独立 judge（跨模型族、成对/校准；材料必须去系统元数据） | 探索性 | 只能作为补充信号 |
| E2.5 | 独立 LLM 子 Agent 面板盲评（多评者，同族/跨族必须拆开报告） | 探索性（同族有回声风险） | 仅补充；不得替代人工 kappa |
| E3 | 人工盲评（双人 rubric + kappa ≥0.6） | 高（质量真值） | 唯一可支撑“匹配质量”结论 |
| X | heuristic agreement / NDCG / 交付数单指标 / 旧 RESULTS 数字 | 不可用 | 只能做回归监控，禁止对外 |

## 2. 冻结集与供给池规则

1. `eval/frozen/v3/` 为只读资产：`scenarios.json`、`labels.json`、`MANIFEST.json`、`BASELINE.json`。
2. MANIFEST 同时记录：
   - `scenarios/labels` 的 sha256；
   - `pool.base_sql_sha256`：eval profile 实际加载的全部 `deploy/mysql/sql/base/*.sql` 指纹；
   - `pool.pool_digest`：从 base SQL 解析出的成员/偏好最终状态指纹；
   - `supply_additions`：eval 专属 SQL 目录中的供给写语句数量，必须为 0。
3. 任何 base SQL / eval SQL / 场景 / 标签改动，都必须重跑 `python eval/build_frozen_labels.py` 升 MANIFEST，
   并在 PR 说明里写“为什么不是评测调优”；`check_freeze.py` 在 CI 中 fail-closed。
4. 禁止对 v3 任何场景补候选供给、按场景改规则/排序/阈值；`deploy/mysql/sql/eval/` 只允许空目录/README。
5. 新评测集（v4+）只能新建，不得改 v3；场景定义前固定供给池；新协议必须 bump `protocol_version`。
6. eval profile 只加载 `sql/base`；产品 demo profile 加载 `sql/demo`，两者不得混用。

## 3. Oracle 规则

- v3 frozen labels 是 `heuristic-offline-v1`，由仓库种子 SQL + 场景离线生成；它是**规则基线，不是真值**。
- 只用于 `heuristic_agreement_*` 监控；**永不作为质量门禁或对外数字**。
- CI 只读、不重算；重算只能离线、显式升版本、记录 diff。
- 禁止 consensus/Borda 等“同源多评分器”冒充独立验证。

## 4. 指标口径与门禁

| 指标 | 门禁 | 口径 |
|---|---|---|
| delivery / target_attainment | 是（相对 BASELINE v2） | raw delivered/requested 仅监控；`target=min(requested, eligible_unbounded)`，主口径是 `min(delivered,target)/target` |
| completion/failures | 是 | failures 不得超过 baseline + 0；交付不足不算失败但计入 target |
| catastrophic delivery | 是 | 任一场景由“有交付”退化为 0 直接失败 |
| negative_assertions | 是（verify） | v3 两个 readiness 负向必须实际被 API/readiness 阻断；缺失/误放行失败 |
| safety errors | 是 | PII/secret/承诺/注入（error 阻断，warning 报告） |
| cost | publish 是 | 真实单价必填；无单价必须报 unknown，禁止 0.0 |
| judge | publish 是 | 不同模型族；材料不得含系统排名/分数/证据/角色；pairwise 需交换位置且 consistency ≥0.8 |
| human | 对外质量声称必填 | 双人盲评 + kappa ≥0.6 |
| heuristic_agreement/NDCG | 否 | 按 delivered_rank；precision 分母=requested；NDCG 短交付补零 |

**BASELINE v2 要求**：`schema_version>=2`、`protocol_version`、`labels_sha256`、`scenarios_sha256`、
`source.code_commit`、`model_configs`、`db_profile=eval`、`per_scenario`（含 delivered/target/target_attainment）。
缺任一字段或与当前冻结文件不一致 → verify 失败。

## 5. 变更分类与提交纪律

| 类别 | 例子 | 要求 |
|---|---|---|
| data | SQL 种子/供给/迁移 | 与代码/评测分开提交；不得同时改标签 |
| code | backend/frontend | 常规 review + 测试 |
| eval | eval/、workflow、冻结集 | 变更即 RFC；冻结集走 MANIFEST/protocol 升版 |

红线：
- 禁止给评测集补供给；
- 禁止“补供给 + 重算标签”同批；
- 禁止跨环境/跨 oracle 版本横比；
- 禁止用 heuristic/NDCG/交付数单独作为质量门禁或对外数字；
- 禁止在评测材料里携带 `delivered_rank/screen_score/delivered/audit_status/evidence/*_role`；
- 禁止本地单次 8/8 后直接合入评测/排序/检索改动。

## 6. Artifact 必须字段

每次评测 artifact 至少包含：`code_commit`、`labels_hash`、`scenarios_hash`、`suite`、`db_profile`、
`model_configs`（脱敏）、`prompts_sha256`、`MATCH_TIMEOUT_SECONDS`、`bundle_trials/run_ids`、`n/trials`、
`prices`、生成时间。缺任一字段的实验报告不得作为发布依据。

## 7. 对外口径

**可声称**：
- 可运行、可复盘、硬规则代码强制 + 单测/E2E；
- v3 冻结集上完成率/交付达容量上限（附 target 归一化与 n）；
- eval 工具链与冻结/门禁协议存在。

**不可声称**：匹配准确率、Precision/NDCG 质量、holdout 泛化、内容质量达标、安全无风险、
温度 0 可复现、成本可控（除非当次 artifact 有真实成本）、任何 pairwise/κ/内容分质量结论。

## 8. 已知未解决缺陷（Open Defects，需产品决策）

1. 真实供给流动性不足（种子池结构问题；不得用评测补数据掩盖）。
2. 候选软期望文本被当硬冲突（S36 类）。2026-11-05 已补一层兜底：审核官判 `MISMATCH_HARD`
   时由代码双向复核，若代码未发现必须项违规则改回通过（防“加分项被当必须项”的假否决）；
   但软 `PREFERENCE_CONFLICT` 仍无代码复核，S36 类语义问题仍 open。
   同时 `search_members` 已改为“只有门店标必须时才按门店硬筛”，加分门店不再硬过滤。
3. 并发/多用户：单进程 BackgroundTasks，无队列/重试，未做并发验证。
4. 内容质量（summary/画像/解释）未进入人工 rubric 流程。
5. 安全：真实 prompt injection/越权对抗测试缺失；隐私仅日志脱敏。
6. 运行不可完全复现：已记录 prompt 哈希与模型配置，但未保存每次运行完整 Prompt 原文/seed。
7. 种子档案自相矛盾：兴趣标签/自由文本与 has_pet/宠物偏好不一致（评估器已能识别文本矛盾；
   产品侧数据清洗仍需单独排期）。
8. v4 标签仍 pending，v4 尚不能作为质量门禁；旧 v4 pilot 结果（协议 v4-2026-11-04）已作废。

## 9. 发布门禁（摘要）

见 `docs/release-checklist.md`：CI 三件套、freeze-guard、eval unittest、v3 verify（publish 模式含
真实成本 + 独立 judge）、人工抽检/E3。任何一项缺失即不得发布质量结论。

## 10. 历史数据说明

git 历史中仍保留旧版评测脚本、被污染供给 SQL 与旧 RESULTS 数字；历史数据只用于追溯，
不得引用为质量证据。当前有效口径以 `eval/RESULTS.md` 顶部“现在能声称什么”为准。

## 11. LLM 面板/代理评审（E2.5）

- 必须独立上下文、隐藏系统结论、至少 3 位评者；
- 必须报告评者间 kappa/Spearman 与交付组 vs 对照组差异，并按模型族拆分同族/跨族；
- 同族面板（如 4 个 DeepSeek 子 Agent）只能用于发现 bug/假设，不能作为质量水平证据；
- 材料必须走白名单，禁止携带系统结论/排名/分数/证据；
- **不得**把代理评审写成“人工评分/人类评审”，不得据此对外声称质量；
- 人工盲评（E3）仍是唯一质量真值；代理结果只用于发现问题与排序假设。