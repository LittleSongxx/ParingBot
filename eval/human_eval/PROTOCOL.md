# 人工盲评协议

目标：给出**唯一可支撑“匹配质量”结论**的外部真值。judge/agreement 只能补充，不能替代。

## 样本

- 100+ 对：交付候选 60 对、被否决候选 20 对、未进入候选池候选 20 对（用 `sample_pairs.py` 抽样）；
- 覆盖 v3 的正常/中低容量场景与至少 2 类否决原因；
- 评者不知道系统结论与候选来源，只看到双方资料。

## 流程

1. `python eval/human_eval/sample_pairs.py --bundle quality-bundle.json --out eval/human_eval/pairs.csv`
2. 两名评者独立按 `RUBRIC.md` 打分（1–5），填写 `annotations_template.csv` 的 `annotator_a`/`annotator_b`；
3. `python eval/human_eval/kappa.py --labels eval/human_eval/annotations.csv`
4. 目标：Cohen's kappa ≥ 0.6；分歧先仲裁再进入质量结论。
5. 结果写入 `eval/RESULTS.md`，并注明样本数、场景分布、标注者、日期。

## 禁止

- 用模型评分代替人工标注；
- 只抽交付候选（必须包含否决/未进入池的对照样本）；
- 在拿到 kappa 前对外声称“匹配质量”。
