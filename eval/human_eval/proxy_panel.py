#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立 LLM 子 Agent 盲评面板的汇总脚本（探索性代理，不是人工真值）。

用法：
  python eval/human_eval/proxy_panel.py --annotations dir/ --key key.json \
      --out proxy-report.md --json proxy-report.json

约定：
- annotations 目录下每个 JSON 是某位盲评员对同一 blind_set 的评分数组；
- key.json 记录 pair_id → delivered / 对照来源（仅汇总用，评者不可见）；
- 输出 pairwise Cohen's kappa、二次加权 kappa、Spearman、交付组 vs 对照组的评分差。
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

DIMENSIONS = ("hard", "fit", "evidence", "boundary", "overall")


def load_annotations(paths: list[Path]) -> list[tuple[str, dict]]:
    panel = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise SystemExit(f"标注文件必须是 JSON 数组：{path}")
        rows = {str(item.get("pair_id")): item for item in data if item.get("pair_id")}
        panel.append((path.stem, rows))
    return panel


def cohen_kappa(a: list[int], b: list[int], weighted: bool = False) -> float:
    if not a or len(a) != len(b):
        return 0.0
    labels = sorted(set(a) | set(b))
    n = len(a)
    observed = 0.0
    expected = 0.0
    for i, label_a in enumerate(labels):
        for j, label_b in enumerate(labels):
            count = sum(1 for x, y in zip(a, b) if x == label_a and y == label_b)
            if not count:
                continue
            if weighted:
                distance = ((i - j) / (len(labels) - 1)) ** 2 if len(labels) > 1 else 0
                observed += count * (1 - distance)
            elif label_a == label_b:
                observed += count
    observed /= n
    for label_a in labels:
        for label_b in labels:
            if weighted:
                distance = ((labels.index(label_a) - labels.index(label_b)) / (len(labels) - 1)) ** 2 if len(labels) > 1 else 0
                expected += ((sum(1 for x in a if x == label_a) / n)
                             * (sum(1 for y in b if y == label_b) / n) * (1 - distance))
            elif label_a == label_b:
                expected += (sum(1 for x in a if x == label_a) / n) * (sum(1 for y in b if y == label_b) / n)
    if expected >= 1:
        return 0.0
    return (observed - expected) / (1 - expected)


def spearman(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or len(a) < 3:
        return 0.0
    def rank(values):
        ordered = sorted(values)
        return [ordered.index(v) + 1 for v in values]
    ra, rb = rank(a), rank(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else 0.0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="独立 LLM 面板汇总（代理，不是人工真值）")
    parser.add_argument("--annotations", required=True, type=Path, help="标注 JSON 文件目录")
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    paths = sorted(args.annotations.glob("*.json"))
    if not paths:
        raise SystemExit("没有找到标注 JSON")
    panel = load_annotations(paths)
    key = {str(item["pair_id"]): item for item in json.loads(args.key.read_text(encoding="utf-8"))}

    pair_ids = sorted(key)
    scores = {}
    for annotator, rows in panel:
        for pair_id in pair_ids:
            item = rows.get(pair_id)
            if item is None:
                continue
            for dim in DIMENSIONS:
                if isinstance(item.get(dim), (int, float)):
                    scores.setdefault(dim, {}).setdefault(pair_id, {})[annotator] = float(item[dim])

    stats = {}
    for dim in DIMENSIONS:
        values = [v for pair in scores.get(dim, {}).values() for v in pair.values()]
        stats[dim] = {
            "mean": round(statistics.mean(values), 3) if values else None,
            "sd": round(statistics.pstdev(values), 3) if len(values) > 1 else None,
            "n": len(values),
        }

    pairwise = {"kappa": [], "weighted_kappa": [], "spearman": []}
    names = [name for name, _ in panel]
    for dim in DIMENSIONS:
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                left = [scores.get(dim, {}).get(pair, {}).get(names[i]) for pair in pair_ids]
                right = [scores.get(dim, {}).get(pair, {}).get(names[j]) for pair in pair_ids]
                pairs = [(a, b) for a, b in zip(left, right) if a is not None and b is not None]
                if not pairs:
                    continue
                a = [int(round(x)) for x, _ in pairs]
                b = [int(round(y)) for _, y in pairs]
                pairwise["kappa"].append(cohen_kappa(a, b))
                pairwise["weighted_kappa"].append(cohen_kappa(a, b, weighted=True))
                pairwise["spearman"].append(spearman([x for x, _ in pairs], [y for _, y in pairs]))
    agreement = {key_: round(statistics.mean(value), 3) if value else None
                 for key_, value in pairwise.items()}

    groups = {"delivered": [], "control": []}
    for pair_id, item in key.items():
        per_pair = scores.get("overall", {}).get(pair_id, {})
        if not per_pair:
            continue
        mean_score = statistics.mean(per_pair.values())
        groups["delivered" if item.get("delivered") else "control"].append(mean_score)
    result = {
        "annotators": names,
        "pairs": len(pair_ids),
        "stats": stats,
        "agreement": agreement,
        "groups": {name: {"n": len(values), "mean": round(statistics.mean(values), 3) if values else None}
                   for name, values in groups.items()},
        "note": "LLM 面板是探索性代理，不是人工真值；kappa 是评者间一致性，不是人工信度。",
    }
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [
        "# 独立 LLM 面板盲评汇总（代理，不是人工真值）",
        "",
        f"- 评者：{', '.join(names)}；样本：{len(pair_ids)} 对",
        "",
        "| 维度 | 均值 | SD | n |",
        "|---|---|---|---|",
    ]
    for dim in DIMENSIONS:
        item = stats[dim]
        lines.append(f"| {dim} | {item['mean']} | {item['sd']} | {item['n']} |")
    lines += [
        "",
        f"- 评者间一致性：Cohen kappa **{agreement['kappa']}**；二次加权 kappa **{agreement['weighted_kappa']}**；"
        f"Spearman **{agreement['spearman']}**",
        f"- 交付组 overall：{result['groups']['delivered']['mean']}（n={result['groups']['delivered']['n']}）；"
        f"随机池对照组：{result['groups']['control']['mean']}（n={result['groups']['control']['n']}）",
        "",
        "> 这是 LLM 子 Agent 的探索性代理评审，**不是人工真值**；kappa 只表示评者间一致性，"
        "不能替代人工 kappa。不得据此对外声称“匹配质量已验证”。",
    ]
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"agreement": agreement, "groups": result["groups"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
