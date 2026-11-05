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
| v3 冻结集上，verify 交付 **7.125/8（57/64）**，达到结构上限 **57/57 target（100%）** | run 41663358923 artifact + 本地回放 | 中高（n=8，single trial） |

**不能声称**：匹配准确率/Precision/NDCG 质量、泛化、内容质量达标、安全无风险、
温度 0 可复现、成本可控；任何旧 pairwise/κ/内容质量结论。
**质量真值仍缺**：没有 E3 人工盲评；v4 labels 仍 pending。

## 2. v3 当前基线（BASELINE v2）

- 文件：`eval/frozen/v3/BASELINE.json`（schema_version=2）；
- 来源：归档 run `41655402168`（code_commit `bebf56c`，bundle generated_at 2026-11-03 22:58），
  原 run 的 report 步骤曾失败（旧 `quality_checks` 字符串偏好 bug），本基线由修复后代码从同一 artifact 复算；
- labels/scenarios sha 与当前冻结文件一致；protocol `v3-2026-11-04`；
- 交付：55/64 = **85.94% raw**；`target` 合计 57（V3_04 最多 5、V3_06 最多 4），
  **target 达成率 55/57 = 96.49%**；failures=0、runs=8；
- regression：`max_failures_delta=0`、`target_margin=2/57≈0.0351`；任一场景由“有交付”退化为 0 直接失败。

> v3 结构上限 = 57/64；verify 的 57/64 已打满上限。**7.13/8 不是质量分，也不支持“比 6.88 提升”**：
> 差异只来自 V3_08 的 6→8 两个交付位，在 n=8、MDE≈1.6–2 的噪声内。

## 3. verify 回放（2026-11-05 新门禁）

- run `41663358923`（code `7637a5e`）：交付 57/64 = 89.06% raw，**target 100%**；failures 0；
- token 1,661,505；延迟 P50/P95 85.3/249.4s（artifact；stats 队友复算一致）；
- 新门禁回放：通过（baseline v2 校验、负向断言、bundle 指纹、freeze、safe/quality 全绿）；
- run `41659345552` 交付 7.0/8（56/64 = 87.5%，target 98.2%），因 token 1,640,673 > 1,500,000 被旧预算门禁判失败；
  这是 fail-closed 的预期行为，不再作为“质量回退”。
- **HEAD 目前没有 live-eval artifact**：最后一次 live-eval 跑在 24a364c（tidy tie-break，已被回退）；
  本轮代码合并后需重新跑 baseline/verify。

## 4. v4 评测集（设计冻结，尚未接门禁）

- protocol `v4-2026-11-05`；48 场景（40 正向 + 8 负向：4 缺动态、4 缺自我介绍）；
- sha256 `31863a65c3da215995aaa97176b4c5268d1db0e1cd21bb8ea8e751002cf67967`；
- 层配额 16/12/12；性别 20/20；门店 19/20；租期 5 档；`expect.target=min(8, eligible_unbounded)`；
- MANIFEST 记录 base SQL 指纹 + pool digest；`supply_additions=0`；labels **pending**（human/judge 0–3）；
- 本轮修复：slot 计数/昵称（不再“第 208 次”）、文本级宠物矛盾（清洗 tags 后重建 self_intro/moments）、
  负向跨层跨性别、脚本生成 MANIFEST/COVERAGE、`--check` 只读 fail-closed；
- **旧 v4 pilot 结果作废**（旧 sha `f52ad089…`、旧 target 口径）：72.2%→71.3%、pass^3 1.0→0.778、
  target 达成率 98.61% 等数字只保留在历史段落，不得引用。
- 全量 40×3 尚未跑；v4 labels 完成前只能做流程/成本/稳定性试点，不接门禁。

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