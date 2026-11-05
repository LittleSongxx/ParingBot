# 评测运行手册（v3 冻结集，2026-11-05 审计后修订）

> 前提：Docker Desktop + Compose v2；`.env` 已配置数据库/JWT；`.env.eval` 含真实模型 Key。
> 本手册覆盖 `run_matrix` / `build_bundle` / `report` / `judge` / `content_quality` / `check_freeze`。
> 本地无法起 DB/模型时，用 GitHub Actions 的 `live-eval` workflow 执行同样的步骤。

## 0. 环境

```bash
cp .env.eval.example .env.eval     # 填 EVAL_API_KEY（发布模式还需要 EVAL_JUDGE_API_KEY）
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

## 2. 检查冻结集与供给池

```bash
python eval/check_freeze.py                 # MANIFEST + base SQL/pool digest + eval SQL 扫描
python eval/build_frozen_labels.py --verify # 标签可由 base 种子 + 场景复算
python eval/check_v4_freeze.py              # v4 场景/协议/target/文本自洽（labels pending）
python eval/build_v4_scenarios.py --check   # v4 生成器可复现、不写文件
```

## 3. 跑 v3（一次 trial 先跑通）

```bash
python eval/run_matrix.py --suite v3 --trials 1 --label v3-smoke
# 产出：eval/reports/scenario-matrix-<stamp>/matrix.json|md
```

首次跑会创建 `TEST_SCENARIO_V3_*` 账号并写入申请档案/偏好/动态；账号保持「待审核」，不进入候选池。
负向场景（V3_09/V3_10）会记录 `expectation_ok` / `negative_observed`，report 会按它门禁。

## 4. 导出 bundle 与报告

```bash
# 先给交付名单里的候选补画像（content_quality 需要；没有公开动态的候选会跳过）
docker compose exec -T -e EVAL_BUNDLE_TRIALS=1 -e EVAL_WARM_PORTRAITS=40 \
  backend python - < eval/warm_candidate_portraits.py

# EVAL_BUNDLE_TRIALS 必须与 --trials 一致，保证 quality/safety/judge/token 覆盖全部 trial
docker compose exec -T -e EVAL_BUNDLE_TRIALS=1 backend python - < eval/build_bundle.py > quality-bundle.json

# 首次或重基线：产出 BASELINE v2 候选（人工审阅后提交）
python eval/report.py --bundle quality-bundle.json --matrix eval/reports \
  --matrix-stamp v3-smoke --mode baseline --source-run "$RUN_ID" \
  --baseline-out /tmp/v3-baseline.json \
  --out regression-report.md --json regression-report.json

# 日常 verify
python eval/report.py --bundle quality-bundle.json --matrix eval/reports \
  --matrix-stamp v3-smoke --mode verify --max-tokens 2500000 \
  --out regression-report.md --json regression-report.json
```

`--mode verify` 缺 BASELINE、缺场景、负向断言失败、bundle 指纹不符、失败数增加、场景交付归零、
target 配对回退超阈值、安全 error 都会失败。`BASELINE.json` 必须是 schema v2。

## 5. 发布模式（成本 + 独立 judge 缺一不可）

```bash
python eval/judge.py --bundle quality-bundle.json --mode pairwise \
  --sample-not-delivered 8 --out judge-report.md --json judge-report.json

python eval/content_quality.py --bundle quality-bundle.json --limit 20 --min-items 12 \
  --env-file .env.eval --out content-report.md --json content-report.json

python eval/report.py --bundle quality-bundle.json --matrix eval/reports \
  --matrix-stamp "$RUN_LABEL" --mode verify --publish --judge judge-report.json \
  --price-input-per-m "$PRICE_IN" --price-output-per-m "$PRICE_OUT" \
  --max-tokens 2500000 --out regression-report.md --json regression-report.json
```

`--publish` 隐含 `--require-cost --require-judge`：缺真实单价或合法 judge 报告会失败。
judge 必须跨模型族；材料里禁止携带系统排名/分数/证据/角色（脚本会 fail-closed 断言）。

## 6. v4 pilot（labels pending，不接门禁）

```bash
# 默认 9 场景 ×3 trials；keys=all 时跑全部 40 正向（成本高，注意 timeout）
python eval/run_matrix.py --suite v4 --trials 3 --label v4-pilot
python eval/analyze_pilot.py \
  --matrix eval/reports/scenario-matrix-v4-pilot/matrix.json \
  --scenarios eval/frozen/v4/scenarios.json --out v4-pilot-report.md --json v4-pilot-report.json
```

v4 标签工具（本轮只交付工具，不执行真实人工/模型标注）：

```bash
python eval/build_v4_labels.py --from-csv labels.csv --write
python eval/build_v4_labels.py --from-judge judge-labels.json --write
python eval/build_v4_labels.py --check
```

## 7. 人工盲评

见 `human_eval/PROTOCOL.md`、`human_eval/RUBRIC_V2.md`；
`sample_pairs.py` 抽样、`kappa.py` 计算双人 kappa（目标 ≥0.6）。
在拿到人工结果前，对外只能声称“工程可运行/交付达容量上限”，不能声称“匹配质量”。
同族 LLM 面板只用于发现问题，必须按同族/跨族拆分报告。

## 8. 故障排查

| 现象 | 处理 |
|---|---|
| 401 / invalid key | 检查 Key、base_url、地域是否一致 |
| 404 / model not found | 核对供应商控制台模型名；自定义网关用 EVAL_PROVIDER=custom |
| 429 / rate limit | 一次只跑一个 trial；降低并发 |
| readiness 被拦 | 按页面 blocker 补档案/偏好/动态/模型 Key |
| 运行长时间不结束 | 默认 600s 超时；看管理端调度时间线定位卡点 |
| report 缺场景/缺 BASELINE/负向断言失败 | fail-closed 预期，先补齐再重跑 |
| judge 被拒绝 | judge 模型与生产模型相同；换不同模型族或加 --allow-same-model（仅探索） |
| 报告没有生成 | 查看终端错误；`eval/reports/` 已 gitignore |

## 9. 安全收尾

- `.env.eval` 与 `eval/reports/` 均被 gitignore；
- Key 会写入演示库 `ai_model_config`（后端调用用），不再需要时到管理端停用/清空，或重建数据卷；
- 报告只写模型名/供应商/base_url，不写 Key。