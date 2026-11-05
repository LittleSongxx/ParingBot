# 独立 LLM 子 Agent 面板（代理人工，探索性）

> 用途：在没有人工评审资源时，用多个**独立上下文**的子 Agent 对冻结集做盲评，
> 作为探索性代理信号。**它不是人工真值，不能用于对外质量声称或替代 kappa≥0.6 的人工门禁。**

## 约束

1. 评者必须是**独立子 Agent**（新上下文、不继承审计历史），同一份 blind_set；
2. 输入只给双方资料，隐藏系统结论（delivered/audit/gold/judge/运行总结）；
3. 至少 3 位评者，每位独立评分；样本建议 ≥100 对（16 对仅 smoke）；
4. 汇总 `proxy_panel.py`：报告 pairwise kappa/加权 kappa/Spearman、交付组 vs 对照组；
5. 结果只能写进 `eval/RESULTS.md` 的“探索性代理”段，并明确标注代理评审。

## 同族/跨族分解（2026-11-05 审计补充）

> 审计发现：代理面板里 4 个 DeepSeek 评者与生产模型同族，Qwen 只有 1 个。
> 同基座模型/供应商会产生**相关错误**，评者间 κ 会被同族回声抬高，不能当作独立一致性。

`rubric_v2_panel.py` 因此支持 `--models` 并把一致性拆成同族/跨族：

```bash
python eval/human_eval/rubric_v2_panel.py --annotations proxy-eval/annotations \
  --models proxy-eval/models.json --json proxy-eval/report.json
# models.json 例：{"annotator_a":"deepseek","annotator_qwen":"qwen"}
```

输出约定：

- `same_family_kappa` / `cross_family_kappa`：同族、跨族评者对 overall κ 的均值；
- `same_family_only`：为 true 表示面板全部评者同族（此时没有跨族信号，不能声称独立一致性）；
- `ci95.overall_kappa`：按 pair 重采样的 bootstrap 95% CI；
- `annotator_models` / `families` / `family_counts`：每个评者的模型族元数据。

报告口径：样本 <100 对时只能写“探索性代理信号”，且必须同时给 `n`、`cross_family_kappa` 与 CI；
`same_family_only=true` 时不得给出“跨族一致”的结论。

## 步骤

```bash
# 1) 异族模型盲评（只读 blind_set，信息隔离）
python eval/human_eval/llm_annotator.py --blind proxy-eval/blind_set.json \
  --out proxy-eval/annotations/annotator_qwen.json --env-file .env.eval

# 2) 汇总多位评者（建议同时给 --models，分解同族/跨族）
python eval/human_eval/proxy_panel.py --annotations proxy-eval/annotations \
  --key proxy-eval/key.json --out proxy-eval/report.md --json proxy-eval/report.json
python eval/human_eval/rubric_v2_panel.py --annotations proxy-eval/annotations \
  --models proxy-eval/models.json --out proxy-eval/rubric-report.md --json proxy-eval/rubric-report.json
```

## 风险

- 同一基座模型/供应商会产生**相关错误**，评者间 kappa 高不代表评得对；只看同族 κ 会系统性高估；
- 提示词、位置、长度偏差会系统性影响分数；
- 与人工评分校准前，只能作为补充信号；人工盲评仍是唯一质量真值（E3）。
