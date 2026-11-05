# ParingBot 评测体系（2026-11-05 审计后版本）

> 本目录是**评测工具**，不是质量证明。当前对外**不声称匹配质量**。
> 旧 RESULTS 的 87.5%/93.45%/7.94/8/NDCG 42→70 等数字已全部作废（数据集被污染、oracle 与产品同源、
> 每次 CI 自动重算）。有效质量基线只有一种：在冻结 v3 集上跑出、经人工提交的 `frozen/v3/BASELINE.json`
> （schema v2，含 provenance 与每场景交付）。

## 目录

```text
eval/
├── suites/demo.json            # S1–S20 演示 smoke（demo profile，非质量证据）
├── frozen/v3/                  # 冻结评测集：scenarios + labels + MANIFEST + BASELINE(v2)
├── frozen/v4/                  # 设计冻结：40 正向 + 8 负向；labels pending；protocol v4-2026-11-05
├── lib/                        # env / api / seed / rules / metrics / render / freeze
│   └── freeze.py               # base SQL/pool digest、SQL 供给扫描（MANIFEST/check_freeze 共用）
├── run_matrix.py               # 真实 API + 真实模型跑场景矩阵（含负向断言记录）
├── build_bundle.py             # bundle 导出（delivered 按交付上限截断，支持多 trial）
├── warm_candidate_portraits.py # 给交付候选补画像（content_quality 输入）
├── quality_checks.py           # 硬规则 / 数据一致性 / 字段存在率（非质量）
├── safety_checks.py            # PII / 承诺 / 注入 扫描
├── judge.py                    # 独立 judge（跨模型族、pointwise/pairwise、位置一致性）
├── build_bundle.py             # bundle 导出（meta 含 code_commit/labels/scenarios hash/prompts_sha256）
├── report.py                   # 一键报告 + fail-closed 门禁（target 归一 + baseline v2）
├── build_v3_scenarios.py       # v3 场景生成（产物已冻结，脚本仅用于复现）
├── build_frozen_labels.py      # 离线生成/校验 v3 labels + MANIFEST（含 pool 指纹）
├── check_freeze.py             # 冻结守护 + base/eval 供给扫描
├── build_v4_scenarios.py       # v4 场景/MANIFEST/COVERAGE 生成与 --check
├── check_v4_freeze.py          # v4 冻结守护（场景/协议/target/文本自洽/labels 状态）
├── build_v4_labels.py          # v4 标签工具（人工 CSV / judge JSON / --check）
├── quality_scorecard.py        # 多次 artifact 汇总：失败率 CI / target / 不稳定场景 / 代理质量信号
├── configure_models.py         # 写四用途模型配置
├── phase0/                     # 资料教练/解读官 schema 评测（功能未实现，非质量证据）
├── human_eval/                 # 人工盲评协议、rubric、抽样与 kappa 脚本
└── tests/                      # unittest + 合成 fixture（离线）
```

## 两套数据 profile

| profile | 内容 | 用途 |
|---|---|---|
| `demo` | `deploy/mysql/sql/base` + `sql/demo` | 页面演示 / E2E / pytest |
| `eval` | 仅 `sql/base`（900 名种子成员，**不追加候选供给**） | live-eval 唯一允许的环境 |

## 两个场景集

- **v3（V3-01..V3-10）**：冻结评测集，8 正向 + 2 readiness 负向；候选池固定为 base 种子
  （841 名 approved+enabled），从不补供给；按先天容量分层（高 3 / 中 3 / 低 2），容量在场景定义前确定。
  结构交付上限 = 57/64（V3_04 最多 5、V3_06 最多 4）；主口径是 `target=min(8, eligible_unbounded)`。
- **v4（V4-01..V4-48）**：40 正向 + 8 负向，protocol `v4-2026-11-05`；供给池与 v3 相同、无供给追加；
  labels **pending**，完成前只用于流程/成本/稳定性试点，不接质量门禁。旧 v4 pilot（protocol v4-2026-11-04）已作废。

## 指标：能证明什么 / 不能证明什么

| 指标 | 定义 | 能证明 | 不能证明 |
|---|---|---|---|
| delivery_rate | delivered/requested（按场景/trial） | 固定池上交付量 | 交付的人是否合适；v3 已饱和 |
| target_attainment | min(delivered,target)/target，target=min(requested, unbounded) | 达成容量上限的比例 | 质量；低容量场景打满不等于合适 |
| completion / failures | 运行完成数、失败数 | 流程可靠性 | 匹配质量 |
| negative_assertions | 负向场景是否被 API/readiness 真正阻断 | 前置校验有效 | 业务语义正确性 |
| judge | 独立模型对候选的合住适配评分 | 探索性外部信号 | 人工真值；材料必须无系统元数据 |
| human | 双人 rubric + kappa | 唯一质量真值 | 需真实执行 |
| heuristic_agreement/NDCG | 交付与冻结 heuristic 标签的一致率 | 排序与既有规则一致性（监控） | 规则本身正确；不能作为质量门禁 |
| cost/latency | 真实 token 成本、P50/P95 | 成本与延迟趋势 | 质量 |

**红线**：`heuristic_agreement_*`、`NDCG`、raw delivery 单指标永远不能作为质量结论或发布门禁；
交付数不能单独证明质量；pairwise/内容/κ 在判官泄漏修复前的结果全部作废。

## 运行（真实模型，需 Key + Docker）

```bash
# 1) 配置模型
python eval/configure_models.py --env-file .env.eval

# 2) 跑冻结 v3（1 trial 先跑；质量类指标需 EVAL_BUNDLE_TRIALS 同步 = trials）
EVAL_TRIALS=1 python eval/run_matrix.py --suite v3 --trials 1 --label v3-smoke

# 3) 补候选画像 + 导出 bundle（容器内；EVAL_BUNDLE_TRIALS 与 trials 对齐）
docker compose exec -T -e EVAL_BUNDLE_TRIALS=1 -e EVAL_WARM_PORTRAITS=40 \
  backend python - < eval/warm_candidate_portraits.py
docker compose exec -T -e EVAL_BUNDLE_TRIALS=1 backend python - < eval/build_bundle.py > quality-bundle.json

# 4) 报告 + 门禁
python eval/report.py --bundle quality-bundle.json --matrix eval/reports \
  --matrix-stamp v3-smoke --labels eval/frozen/v3/labels.json \
  --scenarios eval/frozen/v3/scenarios.json --manifest eval/frozen/v3/MANIFEST.json \
  --mode verify --max-tokens 2500000 --out regression-report.md --json regression-report.json
```

发布模式追加：`--publish --judge judge-report.json --price-input-per-m ... --price-output-per-m ...`。

## 冻结与门禁

- `frozen/v3/scenarios.json`、`labels.json`：sha256 入 MANIFEST；`check_freeze.py` 校验。
- MANIFEST 额外记录 `pool.base_sql_sha256` + `pool.pool_digest`；base SQL 或候选池被改即失败。
- `report.py --mode verify`：缺 BASELINE、缺场景、负向断言失败、bundle 指纹不符、失败数增加、
  场景交付归零、target 配对回退超阈值、安全 error → 直接失败；publish 额外要求真实成本 + 合法 judge。
- 首次基线流程：`live-eval mode=baseline` → 下载 artifact → 人工提交 `frozen/v3/BASELINE.json`（v2 schema）→ 之后 verify。
- v4：labels pending 前只跑 `check_v4_freeze.py` / `build_v4_scenarios.py --check` / pilot；不接门禁。

## Phase 0（独立定位）

`phase0/` 只校验“资料教练 / 匹配解读官”的输出契约与坏输出拦截；这两个功能**尚未实现**，
参考输出只验证评测器本身，**不构成产品能力或质量证据**。

## 变更纪律

- 数据（SQL）/ 代码（backend/frontend）/ 评测（eval、workflow）分 PR；
- 禁止“补供给 + 重算标签”同批；
- 不允许对 v3 补候选、不允许 CI 自动重算 oracle；
- 禁止判官材料携带 `delivered_rank/screen_score/delivered/audit_status/evidence/*_role`；
- 任何质量数字必须附：oracle 版本 + 数据版本 + 环境 + n + artifact（见 `docs/quality-policy.md`）。