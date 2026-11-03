# 独立 LLM 子 Agent 面板（代理人工，探索性）

> 用途：在没有人工评审资源时，用多个**独立上下文**的子 Agent 对冻结集做盲评，
> 作为探索性代理信号。**它不是人工真值，不能用于对外质量声称或替代 kappa≥0.6 的人工门禁。**

## 约束

1. 评者必须是**独立子 Agent**（新上下文、不继承审计历史），同一份 blind_set；
2. 输入只给双方资料，隐藏系统结论（delivered/audit/gold/judge/运行总结）；
3. 至少 3 位评者，每位独立评分；样本建议 ≥100 对（16 对仅 smoke）；
4. 汇总 `proxy_panel.py`：报告 pairwise kappa/加权 kappa/Spearman、交付组 vs 对照组；
5. 结果只能写进 `eval/RESULTS.md` 的“探索性代理”段，并明确标注代理评审。

## 步骤

```bash
python eval/human_eval/proxy_panel.py --annotations proxy-eval/annotations \
  --key proxy-eval/key.json --out proxy-eval/report.md --json proxy-eval/report.json
```

## 风险

- 同一基座模型/供应商会产生**相关错误**，评者间 kappa 高不代表评得对；
- 提示词、位置、长度偏差会系统性影响分数；
- 与人工评分校准前，只能作为补充信号；人工盲评仍是唯一质量真值（E3）。
