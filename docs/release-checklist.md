# 发布前质量检查单

每次模型、Prompt、规则或前后端改动后，按下面顺序跑一遍。全部通过才合并/发布。

## 1. 本地确定性检查

```bash
cd backend
pytest -q                                  # 当前基线 357 passed

cd ../e2e
npx playwright test                        # 只读 E2E，不触发真实匹配

cd ..
python eval/run_eval.py --fixtures --bad eval/fixtures/bad
python eval/quality_checks.py --bundle eval/fixtures/quality_bundle_sample.json
python eval/golden_matching.py --bundle eval/fixtures/quality_bundle_sample.json
python eval/golden_matching.py --bundle eval/fixtures/quality_bundle_sample.json \
  --labels eval/golden/consensus_labels.json --min-precision 0.7
python eval/regression_report.py --bundle eval/fixtures/quality_bundle_sample.json \
  --out /tmp/regression-report.md --min-precision 0.7 --min-consensus 0.7
python eval/safety_checks.py --bundle eval/fixtures/quality_bundle_sample.json
```

## 2. 真实模型评测（本地或 GitHub Actions）

人工 Key 不落仓库。两个入口二选一：

- 本地：`.env.eval` 已配置 DeepSeek Key，执行
  ```bash
  python eval/scenario_matrix.py --env-file .env.eval \
    --only S1,S3,S5,S6,S14,S16,S20 --trials 1 --label release-check
  ```
- GitHub：Actions → `live-eval` → Run workflow，选择场景/trials；
  需要仓库 secret `DEEPSEEK_API_KEY`。

跑完后下载/生成 `regression-report.md`、`safety-report.md`、`quality-bundle.json`。

## 3. 质量门禁

| 门禁 | 阈值 |
|---|---|
| 硬规则违规 | 0 |
| summary 不一致 | 0 |
| 交付缺证据 | 0 |
| PII / secret | 0 |
| heuristic Precision@K | ≥ 0.60（fixture ≥0.70） |
| consensus Precision@K | ≥ 0.60 |
| 压力场景 S6/S14/S16/S20 | 已完成且交付 ≥7 人 |

## 4. 产物与归档

- `regression-report.md/json`：统一回归报告（质量检查 + 安全 + 两种 golden + 场景摘要 + 压力门禁）
- `safety-report.md/json`：安全 / 隐私扫描
- `quality-bundle.json`：本次真实运行数据，便于复现
- `eval/reports/scenario-matrix-*`：场景原始数据（gitignore）

## 5. 发布记录

在 PR/发布说明里附：

- CI run 链接（backend / frontend / e2e-smoke）
- `regression-report.md` 的关键数字
- 压力场景是否 4/4 通过
- 安全扫描是否 0 error

> 没有人工评审时，以上自动门禁 + 共识 gold 是唯一发布依据；不把单次 8/8 当质量结论。
