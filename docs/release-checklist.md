# 发布前质量检查单

> 本清单只管“能不能发布”的**工程与证据纪律**；不把交付数当质量结论。
> 发布说明里的任何质量数字必须附 oracle 版本 + 数据版本 + 环境 + n（见 docs/quality-policy.md）。

## 1. 本地/CI 工程门禁

```bash
cd backend && pytest -q
cd ../e2e && npx playwright test
cd ..
python -m unittest discover -s eval/tests -v
python -m compileall -q eval
python eval/check_freeze.py
python eval/phase0/run_eval.py --fixtures --bad eval/phase0/fixtures/bad
```

全部通过才允许合并/发布。CI 的 backend / frontend / e2e / freeze-guard 任一失败即阻断。

## 2. 评测环境

- eval profile 启动（`docker compose -f docker-compose.yml -f docker-compose.eval.yml up -d --build`）；
- 使用冻结 v3 集（`--suite v3`），**不补供给、不改标签、不改规则**；
- 记录 commit、MANIFEST hash、模型配置（脱敏）、超时、价格。

## 3. 质量门禁（report.py）

| 门禁 | 阈值 |
|---|---|
| 必需场景齐全 | fail-closed，缺一即失败 |
| 冻结文件 | MANIFEST 哈希一致；eval profile 无供给 |
| 交付率 | 相对 BASELINE 回退 ≤ 1.0/8（默认；可按基线调整） |
| 失败数 | 不超过 BASELINE + 1 |
| 安全 | PII/secret error = 0 |
| 成本 | 发布模式必须给真实单价（禁止 0） |
| judge | 发布模式要求独立 judge 报告（观察期后） |

`heuristic_agreement` / `NDCG` 只报告，不阻断、不作为质量结论。

## 4. 质量声称规则

- 对外声称“匹配质量”前，必须有：v3 冻结集 verify 通过 + 人工盲评（≥100 对、kappa ≥0.6）+ 独立 judge；
- 只有工程事实（CI/单测/E2E/可运行）时可对外，不得顺带引用旧数字；
- 禁止跨环境/跨 oracle 版本对比；
- 发布说明附 artifact 链接与结果报告。

## 5. 记录与归档

- 上传/归档：`regression-report.md/json`、`quality-bundle.json`、`safety-report.*`、`judge-report.*`、
  `eval/reports/`、`eval/frozen/v3/*.json`；
- 在 PR/发布说明中写：CI run 链接、BASELINE 版本、v3 verify 结果、judge 是否运行、人工抽检结果；
- 旧版 RESULTS 数字一律不得引用。
