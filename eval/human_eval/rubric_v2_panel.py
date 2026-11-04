#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rubric v2 多评者汇总：item-level 一致性与 overall κ。

Rubric v2 把主观 1-5 拆成可判定项（hard_gate/lifestyle/commute/lease/data/boundary），
再用确定性规则汇总 overall。本脚本用于回答：
- overall 的 κ/加权 κ 是否比 v1 提高；
- 分歧主要来自哪个 item（hard_gate 还是 lifestyle）。
注意：代理评审（LLM/子 Agent）不是人工真值，κ 只表示评者间一致性。
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from proxy_panel import cohen_kappa, spearman

ITEM_FIELDS = ("hard_gate", "commute", "lease_stability", "data_consistency", "boundary")
FLAGS = ("schedule", "smoking", "pet", "tidiness")


def load_panel(paths: list[Path]) -> list[tuple[str, dict]]:
    panel = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise SystemExit(f"标注文件必须是数组：{path}")
        rows = {str(item.get("pair_id")): item for item in data if item.get("pair_id")}
        panel.append((path.stem, rows))
    return panel


def pair_pairs(a: dict, b: dict, field: str):
    values = [(a[p].get(field), b[p].get(field)) for p in sorted(set(a) & set(b))]
    return [(int(x), int(y)) for x, y in values if isinstance(x, (int, float)) and isinstance(y, (int, float))]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Rubric v2 面板汇总（代理评审，不是人工真值）")
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--key", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    panel = load_panel(sorted(args.annotations.glob("*.json")))
    if not panel:
        raise SystemExit("没有标注文件")
    pair_ids = sorted(set.intersection(*(set(rows) for _, rows in panel)))

    pairwise = {"overall_kappa": [], "overall_weighted_kappa": [], "overall_spearman": [],
                "hard_gate_kappa": [], "flags_agreement": [], "item_agreement": {}}
    names = [name for name, _ in panel]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            left, right = panel[i][1], panel[j][1]
            overall = pair_pairs(left, right, "overall")
            if overall:
                a = [x for x, _ in overall]
                b = [y for _, y in overall]
                pairwise["overall_kappa"].append(cohen_kappa(a, b))
                pairwise["overall_weighted_kappa"].append(cohen_kappa(a, b, weighted=True))
                pairwise["overall_spearman"].append(spearman([float(x) for x in a], [float(y) for y in b]))
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

    agreement = {
        "overall_kappa": round(statistics.mean(pairwise["overall_kappa"]), 3) if pairwise["overall_kappa"] else None,
        "overall_weighted_kappa": round(statistics.mean(pairwise["overall_weighted_kappa"]), 3) if pairwise["overall_weighted_kappa"] else None,
        "overall_spearman": round(statistics.mean(pairwise["overall_spearman"]), 3) if pairwise["overall_spearman"] else None,
        "hard_gate_kappa": round(statistics.mean(pairwise["hard_gate_kappa"]), 3) if pairwise["hard_gate_kappa"] else None,
        "lifestyle_jaccard": round(statistics.mean(pairwise["flags_agreement"]), 3) if pairwise["flags_agreement"] else None,
        "item_agreement": {field: round(statistics.mean(values), 3)
                           for field, values in pairwise["item_agreement"].items()},
    }

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
        "groups": {name: {"n": len(values), "mean": round(statistics.mean(values), 3) if values else None}
                   for name, values in groups.items()},
        "note": "Rubric v2 代理评审，不是人工真值；κ 只表示评者间一致性。",
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [
        "# Rubric v2 面板汇总（代理评审，不是人工真值）",
        "",
        f"- 评者：{', '.join(names)}；样本：{len(pair_ids)} 对",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| overall Cohen κ | **{agreement['overall_kappa']}** |",
        f"| overall 加权 κ | {agreement['overall_weighted_kappa']} |",
        f"| overall Spearman | {agreement['overall_spearman']} |",
        f"| hard_gate κ | {agreement['hard_gate_kappa']} |",
        f"| lifestyle Jaccard | {agreement['lifestyle_jaccard']} |",
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
    print(json.dumps({"agreement": agreement, "groups": result["groups"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
