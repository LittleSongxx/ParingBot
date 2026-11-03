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

- **v3 质量基线：尚未产生**。本机无法启动 DB/模型；需在 GitHub Actions 手动触发
  `live-eval`、`mode=baseline`，下载 artifact 后人工提交 `eval/frozen/v3/BASELINE.json`。
- 在 BASELINE 提交之前，`report.py --mode verify` 会 fail-closed，这是预期行为。
- 首次基线预计明显低于旧数字（冻结池不补供给），这不是退步，是第一次真实测量。

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
