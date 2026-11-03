# ParingBot 评测体系

> 本目录是**评测工具**，不是质量证明。当前仓库对外**不声称匹配质量**；旧版 RESULTS 中的
> 87.5%/93.45%/7.94/8/NDCG 42→70 等数字已全部作废（数据集被污染、oracle 与产品同源、每次 CI 自动重算）。
> 有效质量基线只有一种：在冻结的 v3 集上由 `live-eval` 跑出、经人工提交的 `frozen/v3/BASELINE.json`。

## 目录

```text
eval/
├── suites/demo.json            # S1–S20 演示 smoke（demo profile，非质量证据）
├── frozen/v3/                  # 冻结评测集：scenarios + labels + MANIFEST (+ BASELINE)
├── lib/                        # env / api / seed / rules / metrics / render
├── run_matrix.py               # 真实 API + 真实模型跑场景矩阵
├── build_bundle.py             # 在 backend 容器内导出 quality-bundle（含 meta 指纹）
├── quality_checks.py           # 硬规则 / 数据一致性 / 字段存在率（非质量）
├── safety_checks.py            # PII / 承诺 / 注入 扫描
├── judge.py                    # 独立 judge（跨模型、pointwise/pairwise）
├── report.py                   # 一键报告 + fail-closed 门禁
├── build_v3_scenarios.py       # v3 场景生成（产物已冻结，脚本仅用于复现）
├── build_frozen_labels.py      # 离线生成/校验 frozen/v3/labels.json
├── check_freeze.py             # 冻结守护 + eval profile 供给扫描
├── configure_models.py         # 写四用途模型配置
├── phase0/                     # 资料教练/解读官的 schema 评测（功能未实现，非质量证据）
├── human_eval/                 # 人工盲评协议、rubric、抽样与 kappa 脚本
└── tests/                      # unittest + 合成 fixture
```

## 两套数据 profile

| profile | 内容 | 用途 |
|---|---|---|
| `demo` | `deploy/mysql/sql/base` + `sql/demo`（演示候选供给） | 页面演示 / E2E / pytest |
| `eval` | 仅 `sql/base`（900 名种子成员，**不追加任何候选供给**） | live-eval 唯一允许的环境 |

启动 eval profile：

```bash
docker compose -f docker-compose.yml -f docker-compose.eval.yml up -d --build
```

## 两个场景集

- **demo（S1–S20）**：演示用 smoke，只回答“流程还能不能跑”；其结果不进入质量结论。
- **v3（V3-01..V3-10）**：冻结评测集，8 个正向 + 2 个 readiness 负向；
  候选池固定为 base 种子（841 名 approved+enabled），**从不补供给**。
  按先天供给容量分层抽样（高/中/低），在定义场景前确定，避免按结果挑场景。

## 指标：能证明什么 / 不能证明什么

| 指标 | 定义 | 能证明 | 不能证明 |
|---|---|---|---|
| delivery_rate | delivered / requested（按场景/全量） | 在冻结池上能交付多少人 | 交付的人是否合适 |
| completion / failures | 运行完成数、失败数 | 流程可靠性 | 匹配质量 |
| judge（pointwise/pairwise） | 独立模型对候选的合住适配评分 | 探索性外部信号 | 人工真值；需校准 |
| human（人工盲评） | 双人 rubric 评分 + kappa | 唯一的质量真值来源 | 需真实执行 |
| heuristic_agreement_* | 交付与冻结 heuristic 标签的一致率（按 delivered_rank；precision 分母=requested；NDCG 对短交付补零） | 排序与既有规则是否一致 | 规则本身正确；不能作为质量门禁 |
| cost / latency | 真实 token 成本、P50/P95 | 成本与延迟趋势 | 质量 |

**红线**：`heuristic_agreement_*`、`NDCG` 永远不能作为质量结论或发布门禁；交付数不能单独证明质量。

## 运行（真实模型，需 Key + Docker）

```bash
# 1) 配置模型（写库 + 连通性测试）
python eval/configure_models.py --env-file .env.eval

# 2) 跑冻结 v3（1 trial 先用）
python eval/run_matrix.py --suite v3 --trials 1 --label v3-smoke

# 3) 导出 bundle（容器内）
docker compose exec -T backend python - < eval/build_bundle.py > quality-bundle.json

# 4) 报告 + 门禁
python eval/report.py --bundle quality-bundle.json --matrix eval/reports \
  --labels eval/frozen/v3/labels.json --manifest eval/frozen/v3/MANIFEST.json \
  --mode baseline --out regression-report.md --json regression-report.json
```

## 冻结与门禁

- `frozen/v3/scenarios.json`、`labels.json`、`MANIFEST.json` 修改必须走 MANIFEST 升版流程；
  `python eval/check_freeze.py` 校验哈希，并扫描 `deploy/mysql/sql/eval/` **禁止任何成员供给写语句**。
- `report.py --mode verify` 与 `BASELINE.json` 比较：缺 BASELINE、缺必需场景、交付回退超阈值、
  失败数增加、安全 error → 直接失败；发布模式额外要求成本单价与 judge 报告。
- 首次基线流程：`live-eval` 手动触发 `mode=baseline` → 下载 artifact → 人工提交
  `eval/frozen/v3/BASELINE.json` → 之后默认 `mode=verify`。

## Phase 0（独立定位）

`phase0/` 只校验“资料教练 / 匹配解读官”的输出契约与坏输出拦截；这两个功能**尚未实现**，
用例参考输出只验证评测器本身，**不构成产品能力或质量证据**。

## 变更纪律

- 数据（SQL）/ 代码（backend/frontend）/ 评测（eval、workflow）分 PR；
- 禁止“补供给 + 重算标签”同批；
- 不允许对 holdout/v3 补任何候选；不允许 CI 自动重算 oracle；
- 任何质量数字必须附：oracle 版本 + 数据版本 + 环境 + n（见 `docs/quality-policy.md`）。
