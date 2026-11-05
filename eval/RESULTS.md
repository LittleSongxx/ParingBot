# 当前评测状态（唯一有效口径，2026-11-05 审计后修订）

> 本文件只记录**当前有效**的结论。旧版 RESULTS（含 794 行历史数字、pairwise 100%、
> κ=0.933、内容 4.875/5 等）已全部作废，原因见 §7。
> 有效口径 = 冻结 v3 协议 `v3-2026-11-04` + BASELINE v2 + 2026-11-05 之后产生的 artifact。

## 1. 现在能声称什么

| 结论 | 证据 | 置信度 |
|---|---|---|
| 多 Agent 匹配流程可运行、可复盘 | CI backend pytest、E2E、真实运行归档 | 高 |
| 硬规则（同性/双向必须项/租期档位/交付前复核）由代码强制并有单测 | `backend/service/auditor_service.py`、`backend/tests/` | 高（机制） |
| 评测工具链自身可用（冻结/供给池指纹/target 归一/负向断言/门禁） | `eval/tests/` 135 tests、`check_freeze.py`、CI | 高 |
| v3 冻结集上，baseline 交付 **7.125/8（57/64）**，达到结构上限 **57/57 target（100%）** | run 41985813976 artifact + 本地回放 | 中高（n=8，single trial） |

**不能声称**：匹配准确率/Precision/NDCG 质量、泛化、内容质量达标、安全无风险、
温度 0 可复现、成本可控；任何旧 pairwise/κ/内容质量结论。
**质量真值仍缺**：没有 E3 人工盲评；v4 labels 仍 pending。

## 2. v3 当前基线（BASELINE v2，2026-11-05 重跑）

- 文件：`eval/frozen/v3/BASELINE.json`（schema_version=2）；
- 来源：live-eval run `41985813976`（code_commit `b6f3d74`，2026-11-05 15:32 +08），
  经 `report.py --mode baseline` 生成、人工提交；labels/scenarios sha 与当前冻结文件一致，protocol `v3-2026-11-04`；
- 交付：57/64 = **89.06% raw**；`target` 合计 57（V3_04 最多 5、V3_06 最多 4），
  **target 达成率 57/57 = 100%**；failures=0、runs=8；
- regression：`max_failures_delta=0`、`target_margin=2/57≈0.0351`；任一场景由“有交付”退化为 0 直接失败。
- 归档历史基线（run 41655402168 / 6.88、target 96.49%）只作追溯，不再作为当前 baseline。

> v3 结构上限 = 57/64；当前 baseline 已经打满上限（100% target）。
> 这意味着：**v3 交付指标不再有提升空间，也不适合用来证明质量提升**；
> 后续主回归只能依赖硬规则/安全/失败数/负向断言/成本，质量变化必须等 E3 人工或校准 judge。
> 任何“7.13 → 更高”的叙事都不成立（最大值就是 7.125/8）。

## 3. verify 回放（2026-11-05 新门禁）

- 归档 run `41663358923`（code `7637a5e`）：交付 57/64 = 89.06% raw，**target 100%**；failures 0；
  用新 BASELINE v2 回放：通过（baseline hash/protocol、负向断言、bundle 指纹、freeze、safe/quality 全绿）；
- run `41659345552` 交付 56/64（87.5% raw，target 98.2%），因 token 1,640,673 > 1,500,000 被预算门禁判失败；
  这是 fail-closed 的预期行为，不再作为“质量回退”；
- run `41997348370`（最新干净 verify，code `a0ef5c9`）：交付 57/64、**target 100%**、failures 0、
  token 1,222,026、P50/P95 103.6/169.2s；**新门禁通过**（baseline hash/protocol、负向断言、bundle 指纹、
  freeze、safe/quality 全绿）。
- run `41991751431`：同一代码栈上 V3_07 单次运行失败（438.97s、10 轮、交付 7），门禁按 `failures 1 > 0` 正确拦下；
  复跑 `41997348370` 通过。说明该失败是**间歇性**，首跑还没留下异常栈；已给 `execute_task` 加 `logger.exception`
  并让 CI 始终归档 backend 日志，后续失败可归因。

## 4. v4 评测集（设计冻结，尚未接门禁）

- protocol `v4-2026-11-05`；48 场景（40 正向 + 8 负向：4 缺动态、4 缺自我介绍）；
- sha256 `31863a65c3da215995aaa97176b4c5268d1db0e1cd21bb8ea8e751002cf67967`；
- 层配额 16/12/12；性别 20/20；门店 19/20；租期 5 档；`expect.target=min(8, eligible_unbounded)`；
- MANIFEST 记录 base SQL 指纹 + pool digest；`supply_additions=0`；labels **pending**（human/judge 0–3）；
- 本轮修复：slot 计数/昵称（不再“第 208 次”）、文本级宠物矛盾（清洗 tags 后重建 self_intro/moments）、
  负向跨层跨性别、脚本生成 MANIFEST/COVERAGE、`--check` 只读 fail-closed；
- **新协议 pilot（run `41991262897`，9 场景×3 trials）**：交付率 85.65%（95% CI 71.3–96.8%）、
  target 达成率 99.38%、pass³(target)=0.889、failures=1、墙钟 76 分钟（V4_29 单次 483s + 低容量场景约 300s）；
  `V4_29` 在 full pilot 交付 [6,5,6]（run1 失败），但定向复跑 `42002328618` 同一场景交付 **[1,2,6]**、无失败——
  **同一冻结场景跨 run 波动极大**，说明 pilot 的 pass^k 不能当作稳定质量结论；低容量场景的候选发现/通过率不稳定，
  需产品侧排查（不在本轮评测修复范围）。
- **旧 v4 pilot 结果作废**（旧 sha `f52ad089…`、旧 target 口径）：72.2%→71.3%、pass^3 1.0→0.778、
  target 达成率 98.61% 等数字只保留在历史段落，不得引用。
- 全量 40×3 尚未跑；v4 labels 完成前只能做流程/成本/稳定性试点，不接门禁。

## 5.5 2026-11-05 首轮探索性质量结果（E2.5/E2，不是人工真值）
- 对象：run `41997348370` 的 quality bundle（8 申请方 / 57 交付候选 / 对照组来自截断或否决候选）。
- 内容质量（Qwen 异族代理，n=20：8 申请方 + 12 交付候选）：
  - faithful **4.65**（95% CI 4.15–5.0）、coherent 4.85、readable 4.90、respectful 5.00、overall **4.75**（4.45–5.0）；
  - 规则 warning **8/20**：候选画像提到养宠但 `has_pet=无`（种子候选数据自相矛盾），说明“内容质量”与
    “数据一致性”必须分开报告；天花板检测未触发（非全满分，有区分度）；
  - 这只是代理评审（E2.5），不能当作内容质量达标的证据；warning 指向的是候选数据质量问题。
- 成对 judge（Qwen 异族，对照组=截断/否决候选；E2）：
  - 21 对，20 对有效；delivered 胜率 **75%**（95% CI 53.1–88.8%），位置一致性 **0.85**（95% CI 64.0–94.8%）；
  - 这是判官材料去泄漏后的第一份新 pairwise 结果；n 小、对照来自同 pool 的 near-miss，只能作为
    “交付组相对优于对照”的弱-中等探索信号，不能声称匹配质量。
- 结论：本轮能给出的是“流程/容量 + 内容质量代理 + 相对 judge”的**探索性**结果；
  E3 人工盲评仍是唯一可对外质量真值。

## 5. 2026-11-05 审计修复摘要（代码层）

| 类别 | 修复 |
|---|---|
| 测量仪器 | report：target 归一 + baseline v2 provenance/hash 校验 + 负向断言 + 灾难/target 门禁 + publish 成本/judge；stats：Wilson/pass^k 全子集/配对 MDE/P95 插值 |
| 冻结 | MANIFEST 增加 base SQL 指纹 + pool digest；check_freeze 扫描多行语句、base 中 TEST_SCENARIO 引用、eval SQL 目录缺失 fail-closed |
| bundle/runner | `EVAL_BUNDLE_TRIALS` 多 trial 导出 + prompts_sha256；负向场景记录 expectation_ok/negative_observed；pilot 输出 target CI/哈希/source |
| 判官 | pairwise/ranking 材料白名单（去除 delivered_rank/screen_score/evidence/A_role/B_role）；位置一致性 + Wilson CI；content 确定性抽样/真实 n；rubric 面板同族/跨族分解 |
| 数据 | v4 重冻（见 §4）；v3 scenarios/labels 字节未变；free-text 宠物矛盾识别加入 data_consistency |
| 产品 | 回退 65d011a 的“代理评分排序惩罚”（保留 QUALITY_GATE 默认 off 的实验开关）；短交付补筛保留但仅作为未全量验证机制 |
| 文档 | 本文件、README/RUNBOOK/quality-policy/release-checklist、v4 DESIGN/DATASHEET/COVERAGE 全部同步 |

## 6. 已知未解决问题

- 无 E3 人工盲评（双人、κ≥0.6）；所有质量结论仍不可对外；
- v4 labels pending，全量 40×3 未跑；v4 与 v3 不是独立验证集（共享 generator/seed/pool 与部分格子）；
- v3 n=8、单 trial、上限饱和，只能做“灾难回退”回归，不能证明质量提升；
- 独立 judge 需跨模型族并在发布模式强制；当前 CI 未配置 `EVAL_JUDGE_API_KEY`，judge/content 在非 publish 下跳过；
- 真实供给流动性、S36 软期望误拒、种子档案矛盾、并发/注入对抗仍属产品 backlog（见 quality-policy §8）；
- HEAD 无 live-eval artifact；合并后需重跑 baseline/verify；本机无 Docker，无法本地跑真实评测。

## 7. 明确作废的旧结论

| 旧结论 | 作废原因 |
|---|---|
| pairwise delivered 胜率 100%（12/12、30/30） | judge 材料含 `A_role/B_role`，pairwise_ranking 还含 delivered_rank/screen_score/evidence；无 artifact、不可复算 |
| 排序 top 100% / adjacent 60–65% / tidy mismatch 7 条归因 | 同上；judge 跟随系统元数据，tidy tie-break 依据不可用 |
| κ 0.417→0.832→0.896→0.933 | 4/5 评者与生产同族（DeepSeek），整体一致主要来自确定性汇总；v1 κ 口径被误用；无 CI/无人工 |
| 内容质量 4.875/5、warning 2/20 | 20×4.875 非整数；CI bundle 候选 portrait 全 null；样本来源/产物不可核 |
| target 达成率 98.61%、补筛有效 | 旧 v4 协议、补筛前单次 9 场景、只在触发场景验证；v4 重冻后作废 |
| v3 “7.13/8 比 6.88 提升” | 容量饱和；差异 2 个交付位在噪声内；新门禁不再比较 raw delivery |

## 8. 如何更新本文件

1. 跑 `live-eval`（baseline 或 verify），保留 artifact 链接与 run id；
2. 人工审阅 `regression-report.md` 与 `judge-report`（如有）；
3. 仅把**可追溯**结论写进本文件，注明：oracle/protocol 版本、MANIFEST hash、环境、n、CI；
4. 禁止跨环境/跨 oracle 版本/跨 v4 协议横比；禁止引用旧 QUALITY 数字；
5. 任何质量类结论必须等待 E3 人工盲评；代理评审只能写“探索性”。