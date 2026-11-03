# 当前评测状态（唯一有效口径）

> 本文件只记录**当前有效**的结论。旧版 RESULTS 的 794 行历史数字（87.5%/93.45%/7.94/8/NDCG 42→70 等）
> 已全部作废，原因：holdout 被按场景克隆的供给污染、oracle 与生产排序同源、CI 每次运行自动重算标签、
> 质量指标只覆盖每申请人最新 1 个 run。保留旧数字的目的仅是追溯，不得引用为质量证据。

## 1. 现在能声称什么

| 结论 | 证据 | 置信度 |
|---|---|---|
| 多 Agent 匹配流程可运行、可复盘 | CI backend pytest、E2E、真实运行归档（历史 artifact） | 高 |
| 硬规则（同性/双向必须项/租期档位/交付前复核）由代码强制并有单测 | `backend/service/auditor_service.py`、`backend/tests/` | 高（机制），门禁自证问题已修 |
| 评测工具链自身可用（冻结集、报告、门禁、安全扫描） | `eval/tests/`、`check_freeze.py`、CI | 高 |

**不能声称**：匹配准确率、Precision/NDCG 质量、holdout 泛化、内容质量、安全无风险、温度 0 可复现。
这些要么没有独立证据，要么旧证据已被证明自证/污染。

## 2. 当前基线状态

- **v3 首个基线已产生**（2026-11-03，GitHub Actions run 41655402168，8 个正向场景 ×1 trial）：
  - 平均交付 **6.88/8（85.9%）**，总交付 55/64，失败 0；
  - 低容量场景 V3_04=5/8、V3_06=4/8、V3_08=6/8；高容量场景多数 8/8；
  - 安全：0 error / 1 warning（`reject_reason` 出现"保证"措辞，属模型文案，需后续清）；
  - 成本未知（本次未提供单价）；judge 未配置独立 Key；人工盲评未执行；
  - **这是回归基线，不是质量结论**：样本 8 场景、heuristic 标签、单模型，不能推导泛化能力。
- 基线文件：`eval/frozen/v3/BASELINE.json`（对应 labels/scenarios hash 已记录）。
- 后续 `report.py --mode verify` 会与它比较；`mode=baseline` 仍可随时重建（人工审核后替换）。

## 3. 如何更新本文件

1. 跑 `live-eval`（baseline 或 verify），保留 artifact 链接；
2. 人工审阅 `regression-report.md` 与 `judge-report`（如有）；
3. 仅把**可追溯**结论写进本文件，并注明：oracle 版本、数据版本（MANIFEST hash）、环境、n、CI；
4. 禁止跨环境 / 跨 oracle 版本横比，禁止引用历史作废数字。

## 4. 已知未解决问题（详见 `docs/quality-policy.md`）

- 真实供给流动性不足（种子池结构性问题，属产品 backlog，不能靠评测补数据解决）；
- S36 类“候选软期望被当硬冲突”的审核缺陷（产品侧未修）；
- 并发/多用户、错误恢复 UX、真实 prompt injection 防护；
- 内容质量（summary/画像/解释）尚未进入人工 rubric 流程；
- 独立 judge 目前为探索性信号，不能替代人工。

> 资源参考：v3 的 8 个正向场景 ×1 trial 实际消耗约 164 万 token（2026-11-03 实测）。
> workflow 的默认 token 预算已从 150 万上调到 250 万；若继续增高场景数/ trials，请同步调整。

## 2.1 verify 首跑（2026-11-03，run 41663358923）

- 模式：`mode=verify`，与 BASELINE 比较；**门禁通过**；
- 交付 **7.13/8（57/64，89.1%）**，失败 0；低容量场景 V3_04=5、V3_06=4，其余 8/8；
- 安全：0 error / 0 warning；token 1,661,505；延迟 P50/P95 = 85.3/249.4s；成本未知（未提供单价）；
- agreement（监控，非门禁）：precision 76.6%、recall 87.5%；这不是质量结论；
- 同期 CI run 41663356168 全绿；live-eval baseline/verify 端到端流程已验证。
