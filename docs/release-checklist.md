# 发布前质量检查单（2026-11-05 审计后修订）

> 本清单只管“能不能发布”的工程与证据纪律；不把交付数当质量结论。
> 发布说明里的任何质量数字必须附 oracle/数据版本/环境/n/CI artifact 链接。

## 1. 本地/CI 工程门禁

```bash
cd backend && pytest -q
cd ../e2e && npx playwright test
cd ..
python -m unittest discover -s eval/tests -v
python -m compileall -q eval backend
python eval/check_freeze.py                 # MANIFEST + base SQL/pool digest + eval SQL
python eval/build_frozen_labels.py --verify # 标签可由 base SQL + 场景复算
python eval/check_v4_freeze.py              # v4 场景/协议/文本自洽（labels pending 时只查场景）
python eval/build_v4_scenarios.py --check   # v4 生成器可复现
python eval/phase0/run_eval.py --fixtures --bad eval/phase0/fixtures/bad
```

CI 的 backend / frontend / e2e / freeze-guard 任一失败即阻断合并。

## 2. 评测环境

- `docker compose -f docker-compose.yml -f docker-compose.eval.yml up -d --build`（eval profile = base only，禁供给）；
- 使用冻结 v3 集（`--suite v3`），**不补供给、不改标签、不改规则**；
- 记录 commit、MANIFEST hash、模型配置（脱敏）、prompt 哈希、超时、价格；
- `EVAL_BUNDLE_TRIALS` 必须等于 `EVAL_TRIALS`，保证质量/安全/judge 覆盖全部 trial。

## 3. 质量门禁（report.py）

| 门禁 | 阈值 |
|---|---|
| 必需场景齐全 | fail-closed，缺一即失败 |
| 冻结/供给池 | scenarios+labels 哈希、base SQL 指纹、pool digest、eval SQL 目录 |
| bundle 指纹 | suite=v3、db_profile=eval、code_commit、labels/scenarios hash 一致 |
| BASELINE | schema v2（provenance/per_scenario/target），protocol 与 hash 必须匹配 |
| 负向断言 | v3 两个 readiness 负向必须实际被阻断/拒绝 |
| 失败数 | 不超过 BASELINE + 0 |
| 灾难交付 | 任一场景由“有交付”退化为 0 → 失败 |
| target 达成率 | 配对回退超 2 个 target（约 3.5pp）且 95% CI 上界 < 0 → 失败 |
| 安全 | PII/secret/承诺/注入 error = 0 |
| 成本 | publish 模式必须给真实单价（禁止 0） |
| judge | publish 模式必须独立、材料无系统元数据、pairwise 位置一致性 ≥ 0.8、有效样本 ≥ 8 |

`heuristic_agreement` / `NDCG` 只报告，不阻断、不作为质量结论。
raw delivery 仅监控；主口径是 target 归一化交付（v3 上限 57/64）。

## 4. 运行命令

```bash
# baseline（首次或重基线；随后人工审阅并提交 eval/frozen/v3/BASELINE.json）
python eval/report.py --bundle quality-bundle.json --matrix eval/reports \
  --matrix-stamp "$RUN_LABEL" --mode baseline --source-run "$RUN_ID" \
  --baseline-out /tmp/v3-baseline.json --out regression-report.md --json regression-report.json

# verify（CI 默认）
python eval/report.py --bundle quality-bundle.json --matrix eval/reports \
  --matrix-stamp "$RUN_LABEL" --mode verify --max-tokens 2500000 \
  --out regression-report.md --json regression-report.json

# 发布模式：真实成本 + 独立 judge 缺一不可
python eval/report.py ... --publish --judge judge-report.json \
  --price-input-per-m "$PRICE_IN" --price-output-per-m "$PRICE_OUT"
```

## 5. 质量声称规则

- 对外声称“匹配质量”前，必须有：v3 冻结集 verify 通过 + 人工盲评（≥100 对、kappa ≥0.6）+ 独立 judge；
- 只有工程事实（CI/单测/E2E/可运行）时可对外，不得顺带引用旧数字；
- 禁止跨环境/跨 oracle 版本/跨 v4 协议横比；
- 发布说明附 artifact 链接与结果报告；
- pairwise/代理 κ/内容质量分在修复判官泄漏后尚未重跑，不得引用旧值。

## 6. 记录与归档

- 上传/归档：`regression-report.md/json`、`quality-bundle.json`、`safety-report.*`、`judge-report.*`、
  `content-report.*`、`eval/reports/`、`eval/frozen/v3/*.json`、`eval/frozen/v4/scenarios.json`；
- artifact retention ≥ 30 天；
- 在 PR/发布说明中写：CI run 链接、BASELINE 版本、v3 verify 结果、judge/内容是否运行、人工抽检结果；
- 旧版 RESULTS 数字一律不得引用。

## 7. 角色与签字

| 角色 | 职责 |
|---|---|
| 评测 owner | 冻结集/协议/基线、门禁结果复核 |
| 产品 owner | 是否接受 v3 target 口径、是否投入人工盲评/供给治理 |
| 发布负责人 | 真实成本、judge 配置、artifact 归档与对外口径 |