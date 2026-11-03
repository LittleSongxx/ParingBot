# 评测运行手册（v3 冻结集）

> 前提：Docker Desktop + Compose v2；`.env` 已配置数据库/JWT；`.env.eval` 含真实模型 Key。
> 本手册只覆盖当前体系（`run_matrix` / `build_bundle` / `report` / `judge` / `check_freeze`）。
> 本地无法起 DB/模型时，用 GitHub Actions 的 `live-eval` workflow 执行同样的步骤。

## 0. 环境

```bash
cp .env.eval.example .env.eval     # 填 EVAL_API_KEY（以及可选 EVAL_JUDGE_API_KEY）
docker compose -f docker-compose.yml -f docker-compose.eval.yml up -d --build
curl -s http://127.0.0.1:8080/api/ | head -c 200
```

eval profile = 只用 `deploy/mysql/sql/base`，不加载任何演示候选供给。
`MATCH_TIMEOUT_SECONDS=600`（与生产一致，不要为了少失败而放宽）。

## 1. 配置模型

```bash
python eval/configure_models.py --env-file .env.eval          # 写四用途配置 + 连通测试
python eval/configure_models.py --env-file .env.eval --dry-run
```

四个用途：调度 / 画像 / 筛选 / 审核。Key 只写进数据库 `ai_model_config`（不入库版本控制）。

## 2. 检查冻结集

```bash
python eval/check_freeze.py                 # MANIFEST 哈希 + eval profile 无供给
python eval/build_frozen_labels.py --verify # 标签可由仓库种子 + 场景重建
```

## 3. 跑 v3（一次 trial 先跑通）

```bash
python eval/run_matrix.py --suite v3 --trials 1 --label v3-smoke
# 产出：eval/reports/scenario-matrix-<stamp>/matrix.json|md
```

首次跑会创建 `TEST_SCENARIO_V3_*` 账号并写入申请档案/偏好/动态；
账号保持「待审核」，不会进入候选池。

## 4. 导出 bundle 与报告

```bash
docker compose exec -T backend python - < eval/build_bundle.py > quality-bundle.json

python eval/report.py --bundle quality-bundle.json --matrix eval/reports \
  --labels eval/frozen/v3/labels.json --manifest eval/frozen/v3/MANIFEST.json \
  --mode baseline --baseline-out /tmp/v3-baseline.json \
  --out regression-report.md --json regression-report.json

python eval/safety_checks.py --bundle quality-bundle.json \
  --out safety-report.md --json safety-report.json
```

`--mode baseline` 只产基线、不比较；把 `/tmp/v3-baseline.json` 人工审核后提交为
`eval/frozen/v3/BASELINE.json`。

## 5. 日常验证模式

```bash
python eval/report.py --bundle quality-bundle.json --matrix eval/reports \
  --labels eval/frozen/v3/labels.json --manifest eval/frozen/v3/MANIFEST.json \
  --mode verify --require-cost --price-input-per-m 0 --price-output-per-m 0 \
  --out regression-report.md --json regression-report.json
```

`--mode verify` 缺 BASELINE、缺必需场景、交付回退超阈值、失败数增加、安全 error 都会失败；
发布模式再加 `--require-judge`。成本单价必须由发布负责人提供，不允许默认 0。

## 6. 独立 judge（可选，探索性）

```bash
# 必须是不同模型族/供应商；同模型会被拒绝（除非 --allow-same-model）
python eval/judge.py --bundle quality-bundle.json --mode pointwise \
  --sample-not-delivered 8 --out judge-report.md --json judge-report.json

python eval/judge.py --bundle quality-bundle.json --mode pairwise \
  --sample-not-delivered 8 --out judge-report.md --json judge-report.json
```

有带人工标注的 CSV 时加 `--human-labels eval/human_eval/annotations.csv`，输出一致性。

## 7. 人工盲评

见 `human_eval/PROTOCOL.md` 与 `human_eval/RUBRIC.md`；
`sample_pairs.py` 抽样、`kappa.py` 计算双人 kappa（目标 ≥0.6）。
在拿到人工结果前，对外只能声称“工程可运行”，不能声称“匹配质量”。

## 8. 故障排查

| 现象 | 处理 |
|---|---|
| 401 / invalid key | 检查 Key、base_url、地域是否一致 |
| 404 / model not found | 核对供应商控制台模型名；自定义网关用 EVAL_PROVIDER=custom |
| 429 / rate limit | 一次只跑一个 trial；降低并发 |
| readiness 被拦 | 按页面 blocker 补档案/偏好/动态/模型 Key |
| 运行长时间不结束 | 默认 600s 超时；看管理端调度时间线定位卡点 |
| report 缺场景/缺 BASELINE 失败 | 这是 fail-closed 预期，先补齐再重跑 |
| judge 被拒绝 | judge 模型与生产模型相同；换不同模型族或加 --allow-same-model（仅探索） |
| 报告没有生成 | 查看终端错误；`eval/reports/` 已 gitignore |

## 9. 安全收尾

- `.env.eval` 与 `eval/reports/` 均被 gitignore；
- Key 会写入演示库 `ai_model_config`（后端调用用），不再需要时到管理端停用/清空，或重建数据卷；
- 报告只写模型名/供应商/base_url，不写 Key。
