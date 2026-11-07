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

## 无人工时的代理（可选，探索性）

可用多个独立 LLM 子 Agent 做盲评，方法见 `PROXY.md`；结果只能作探索性信号，
不得替代本协议的人工 kappa 门禁，也不得写成“人工评审”。

## 禁止

- 用模型评分代替人工标注；
- 只抽交付候选（必须包含否决/未进入池的对照样本）；
- 在拿到 kappa 前对外声称“匹配质量”。

## quality-v1 工具链（人工只做校准/裁决/验收）

角色说明：人工只负责**校准**（judge 是否可信）、**裁决**（双人分歧）、**验收**（最终报告抽检）；
不参与生成、不替 judge 打分，也不得用模型评分替代人工标注（见上「禁止」）。

```bash
# 1) judge 产出盲材料（pairs + 封存 key；材料已去系统元数据）
python eval/quality_pairwise.py --bundle quality-bundle.json \
    --emit-materials eval/human_eval/calibration/materials.json
# 2) 分层抽样 near_miss/rejected/random=60/20/20 + A/B 重随机化
python eval/human_eval/build_calibration.py \
    --materials eval/human_eval/calibration/materials.json \
    --out-dir eval/human_eval/calibration --n 100 --seed 20261106
# 3) 双人填完后算一致率/Cohen kappa（门禁 0.6）；一致行自动裁决、分歧回填 adjudication.csv
python eval/human_eval/agreement.py --dir eval/human_eval/calibration
# 4) 最终报告分层抽 15% 人工验收；填完 --check 出 signoff.json
python eval/human_eval/acceptance.py --report quality-report.json \
    --key eval/human_eval/calibration/key.json \
    --out eval/human_eval/calibration/acceptance.csv --rate 0.15
python eval/human_eval/acceptance.py --report quality-report.json \
    --key eval/human_eval/calibration/key.json \
    --check eval/human_eval/calibration/acceptance.csv \
    --json eval/human_eval/calibration/signoff.json
```

退出码：build 样本不足=1、拒绝覆盖已有标注=3；agreement/acceptance 未过门槛=1。
`adjudication.csv` 填完 final_winner 后可直接作为 `judge_calibration.py --human` 的人工真值标签。
kappa<0.6 时只能用代理评审做探索（`PROXY.md`），不得声称人工校准或质量结论。
