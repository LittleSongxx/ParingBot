#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rubric v2 多评者汇总：item-level 一致性与 overall κ。

Rubric v2 把主观 1-5 拆成可判定项（hard_gate/lifestyle/commute/lease/data/boundary），
再用确定性规则汇总 overall。本脚本用于回答：
- overall 的 κ/加权 κ 是否比 v1 提高；
- 分歧主要来自哪个 item（hard_gate 还是 lifestyle）。

审计修正（2026-11-05，A3）：
* 新增可选 --models path.json（如 {"annotator_a": "deepseek", "annotator_qwen": "qwen"}）：
  把评者对一致性分解为同族/跨族 κ 均值。4 个 DeepSeek 子 Agent + Qwen 的面板里，
  “同族 κ 高”可能只是同基座回声；跨族 κ 才更接近真正的独立一致性；
* 输出 same_family_kappa / cross_family_kappa / same_family_only 与每个评者的模型族；
* overall κ 均值给 pair bootstrap 95% CI（按 pair 重采样、固定种子，可复现）。

注意：代理评审（LLM/子 Agent）不是人工真值，κ 只表示评者间一致性。
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

from proxy_panel import cohen_kappa, spearman

ITEM_FIELDS = ("hard_gate", "commute", "lease_stability", "data_consistency", "boundary")
FLAGS = ("schedule", "smoking", "pet", "tidiness")
BOOTSTRAP_SEED = 20261104
BOOTSTRAP_ITERATIONS = 1000


def load_panel(paths: list[Path]) -> list[tuple[str, dict]]:
    panel = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise SystemExit(f"标注文件必须是数组：{path}")
        rows = {str(item.get("pair_id")): item for item in data if item.get("pair_id")}
        panel.append((path.stem, rows))
    return panel


def load_models(path: Path | None) -> dict:
    """读取评者→模型族映射；未提供返回空 dict（保持原汇总口径）。"""
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"--models 必须是 JSON 对象：{path}")
    models = {}
    for name, family in data.items():
        if not isinstance(family, str) or not family.strip():
            raise SystemExit(f"--models 里 {name} 的模型族必须是非空字符串")
        models[str(name)] = family.strip()
    return models


def pair_pairs(a: dict, b: dict, field: str):
    values = [(a[p].get(field), b[p].get(field)) for p in sorted(set(a) & set(b))]
    return [(int(x), int(y)) for x, y in values
            if isinstance(x, (int, float)) and isinstance(y, (int, float))]


def _family_pair(models: dict, left: str, right: str) -> str:
    left_family = models.get(left)
    right_family = models.get(right)
    if left_family and right_family:
        return "same" if left_family == right_family else "cross"
    return "unknown"


def bootstrap_kappa_ci(panel: list[tuple[str, dict]], pair_ids: list[str],
                       iterations: int = BOOTSTRAP_ITERATIONS,
                       seed: int = BOOTSTRAP_SEED) -> dict | None:
    """按 pair 重采样，给“各评者对 overall κ 的均值”算 95% CI。

    pair 是抽样单位（同一对候选在不同评者间配对比较），按 pair 重采样比按评者
    重采样更贴近“换一批样本结论会不会变”的问题。
    """
    if len(panel) < 2 or len(pair_ids) < 2:
        return None
    names = [name for name, _ in panel]
    annotator_pairs = [(i, j) for i in range(len(names)) for j in range(i + 1, len(names))]
    rng = random.Random(seed)
    estimates = []
    for _ in range(max(1, int(iterations))):
        sample = [pair_ids[rng.randrange(len(pair_ids))] for _ in range(len(pair_ids))]
        kappas = []
        for i, j in annotator_pairs:
            left, right = panel[i][1], panel[j][1]
            pairs = [(left[pair_id].get("overall"), right[pair_id].get("overall"))
                     for pair_id in sample if pair_id in left and pair_id in right]
            pairs = [(int(x), int(y)) for x, y in pairs
                     if isinstance(x, (int, float)) and isinstance(y, (int, float))]
            if len(pairs) >= 2:
                kappas.append(cohen_kappa([x for x, _ in pairs], [y for _, y in pairs]))
        if kappas:
            estimates.append(sum(kappas) / len(kappas))
    if not estimates:
        return None
    estimates.sort()
    return {"center": round(sum(estimates) / len(estimates), 3),
            "lo": round(estimates[int(0.025 * len(estimates))], 3),
            "hi": round(estimates[min(len(estimates) - 1, int(0.975 * len(estimates)))], 3),
            "iterations": int(iterations), "seed": seed}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Rubric v2 面板汇总（代理评审，不是人工真值）")
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--key", type=Path, default=None)
    parser.add_argument("--models", type=Path, default=None,
                        help='评者→模型族映射 JSON，如 {"annotator_a":"deepseek","annotator_qwen":"qwen"}')
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    panel = load_panel(sorted(args.annotations.glob("*.json")))
    if not panel:
        raise SystemExit("没有标注文件")
    models = load_models(args.models)
    pair_ids = sorted(set.intersection(*(set(rows) for _, rows in panel)))

    pairwise = {"overall_kappa": [], "overall_weighted_kappa": [], "overall_spearman": [],
                "hard_gate_kappa": [], "flags_agreement": [], "item_agreement": {}}
    family_records: list[dict] = []
    same_family_values: list[float] = []
    cross_family_values: list[float] = []
    names = [name for name, _ in panel]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            left, right = panel[i][1], panel[j][1]
            family = _family_pair(models, names[i], names[j])
            record = {"left": names[i], "right": names[j], "family": family,
                      "left_model": models.get(names[i]), "right_model": models.get(names[j])}
            overall = pair_pairs(left, right, "overall")
            if overall:
                a = [x for x, _ in overall]
                b = [y for _, y in overall]
                kappa = cohen_kappa(a, b)
                pairwise["overall_kappa"].append(kappa)
                pairwise["overall_weighted_kappa"].append(cohen_kappa(a, b, weighted=True))
                pairwise["overall_spearman"].append(spearman([float(x) for x in a], [float(y) for y in b]))
                record["overall_kappa"] = round(kappa, 3)
                record["pairs"] = len(overall)
                if family == "same":
                    same_family_values.append(kappa)
                elif family == "cross":
                    cross_family_values.append(kappa)
            hard = pair_pairs(left, right, "hard_gate")
            if hard:
                pairwise["hard_gate_kappa"].append(cohen_kappa([x for x, _ in hard], [y for _, y in hard]))
            for field in ITEM_FIELDS:
                pairs = pair_pairs(left, right, field)
                if pairs:
                    agreement = sum(1 for x, y in pairs if x == y) / len(pairs)
                    pairwise["item_agreement"].setdefault(field, []).append(agreement)
            flag_scores = []
            for pair_id in sorted(set(left) & set(right)):
                a_flags = set(left[pair_id].get("lifestyle_conflicts") or [])
                b_flags = set(right[pair_id].get("lifestyle_conflicts") or [])
                union = a_flags | b_flags
                flag_scores.append(1.0 if not union else len(a_flags & b_flags) / len(union))
            if flag_scores:
                pairwise["flags_agreement"].append(statistics.mean(flag_scores))
            family_records.append(record)

    agreement = {
        "overall_kappa": round(statistics.mean(pairwise["overall_kappa"]), 3) if pairwise["overall_kappa"] else None,
        "overall_weighted_kappa": round(statistics.mean(pairwise["overall_weighted_kappa"]), 3) if pairwise["overall_weighted_kappa"] else None,
        "overall_spearman": round(statistics.mean(pairwise["overall_spearman"]), 3) if pairwise["overall_spearman"] else None,
        "hard_gate_kappa": round(statistics.mean(pairwise["hard_gate_kappa"]), 3) if pairwise["hard_gate_kappa"] else None,
        "lifestyle_jaccard": round(statistics.mean(pairwise["flags_agreement"]), 3) if pairwise["flags_agreement"] else None,
        "item_agreement": {field: round(statistics.mean(values), 3)
                           for field, values in pairwise["item_agreement"].items()},
    }

    # 同族/跨族分解：同族 κ 高不等于独立；跨族 κ 是更有意义的“非回声”一致性。
    families = sorted({models[name] for name in names if models.get(name)})
    annotator_models = {name: models.get(name) for name in names}
    same_family_kappa = round(statistics.mean(same_family_values), 3) if same_family_values else None
    cross_family_kappa = round(statistics.mean(cross_family_values), 3) if cross_family_values else None
    same_family_only = bool(families) and len(families) == 1 and len(names) >= 2 \
        and all(models.get(name) for name in names)
    family_counts: dict = {}
    for name in names:
        family = models.get(name)
        if family:
            family_counts[family] = family_counts.get(family, 0) + 1
    kappa_ci = bootstrap_kappa_ci(panel, pair_ids)

    groups = {"delivered": [], "control": []}
    if args.key and args.key.exists():
        key = {str(item["pair_id"]): item for item in json.loads(args.key.read_text(encoding="utf-8"))}
        for pair_id in pair_ids:
            values = [row[pair_id].get("overall") for _, row in panel if isinstance(row[pair_id].get("overall"), (int, float))]
            if values and pair_id in key:
                groups["delivered" if key[pair_id].get("delivered") else "control"].append(statistics.mean(values))

    result = {
        "annotators": names,
        "pairs": len(pair_ids),
        "agreement": agreement,
        "models": models,
        "annotator_models": annotator_models,
        "families": families,
        "family_counts": family_counts,
        "same_family_kappa": same_family_kappa,
        "cross_family_kappa": cross_family_kappa,
        "same_family_only": same_family_only,
        "pairwise_family": family_records,
        "ci95": {"overall_kappa": kappa_ci},
        "groups": {name: {"n": len(values), "mean": round(statistics.mean(values), 3) if values else None}
                   for name, values in groups.items()},
        "note": "Rubric v2 代理评审，不是人工真值；κ 只表示评者间一致性；同族 κ 可能含同基座回声，"
                "跨族 κ 才是更独立的信号。",
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    ci_text = f"{kappa_ci['lo']}–{kappa_ci['hi']}" if kappa_ci else "不可计算（样本/评者不足）"
    lines = [
        "# Rubric v2 面板汇总（代理评审，不是人工真值）",
        "",
        f"- 评者：{', '.join(names)}；样本：{len(pair_ids)} 对",
        f"- 模型族：{json.dumps(annotator_models, ensure_ascii=False)}；"
        f"same_family_only={same_family_only}",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| overall Cohen κ | **{agreement['overall_kappa']}**（pair bootstrap 95% CI {ci_text}） |",
        f"| overall 加权 κ | {agreement['overall_weighted_kappa']} |",
        f"| overall Spearman | {agreement['overall_spearman']} |",
        f"| hard_gate κ | {agreement['hard_gate_kappa']} |",
        f"| lifestyle Jaccard | {agreement['lifestyle_jaccard']} |",
        f"| 同族 κ 均值 | {same_family_kappa} |",
        f"| 跨族 κ 均值 | {cross_family_kappa} |",
    ]
    for field, value in agreement["item_agreement"].items():
        lines.append(f"| {field} 完全一致率 | {value} |")
    if result["groups"]["delivered"]["n"]:
        lines += ["", f"- 交付组 overall：{result['groups']['delivered']['mean']}（n={result['groups']['delivered']['n']}）；"
                  f"随机对照：{result['groups']['control']['mean']}（n={result['groups']['control']['n']}）"]
    lines += ["", "> Rubric v2 是代理评审（E2.5），不是人工真值，不得替代人工 κ≥0.6 门禁。"]
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"agreement": agreement, "same_family_kappa": same_family_kappa,
                      "cross_family_kappa": cross_family_kappa, "ci95": kappa_ci,
                      "groups": result["groups"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
