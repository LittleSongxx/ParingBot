#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NDCG@8：使用 golden 的排名位置做分级相关性，衡量交付名单的排序质量。

grade: label.ranked 第 1-2 名=3，3-5 名=2，6-8 名=1，其余=0。
交付顺序优先用 bundle 的 delivered_rank；旧 bundle 没有时按原顺序。

用法：
  python eval/ndcg.py --bundle eval/fixtures/quality_bundle_sample.json
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path


def grade_of(label: dict) -> dict:
    grades = {}
    for rank, item in enumerate((label.get("ranked") or [])[:8], 1):
        grades[item["id"]] = 3 if rank <= 2 else (2 if rank <= 5 else 1)
    return grades


def ndcg_at_k(bundle_path: Path, labels_path: Path, k: int = 8) -> dict:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    by_id = {}
    by_name = {}
    for item in labels.get("labels", []):
        by_id[item["member_id"]] = item
        if item.get("username"):
            by_name[item["username"]] = item
    rows = []
    for run in bundle.get("runs", []):
        applicant = run.get("applicant") or {}
        label = by_id.get(applicant.get("id")) or by_name.get(applicant.get("username"))
        if not label:
            continue
        grades = grade_of(label)
        delivered = [c for c in run.get("candidates", []) if c.get("delivered")]
        delivered.sort(key=lambda c: (c.get("delivered_rank") or 10 ** 9, c.get("id") or 0))
        gains = [(2 ** grades.get(c.get("id"), 0)) - 1 for c in delivered[:k]]
        dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
        ideal_grades = sorted((2 ** g) - 1 for g in grades.values())[::-1][:k]
        idcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(ideal_grades))
        rows.append({"run_id": run.get("run", {}).get("id"), "applicant": applicant.get("nickname"),
                     "delivered": len(delivered), "ndcg_at_8": round(dcg / idcg, 4) if idcg else 0.0})
    aggregate = round(sum(row["ndcg_at_8"] for row in rows) / len(rows), 4) if rows else 0.0
    return {"bundle": str(bundle_path), "labels": str(labels_path), "rows": rows,
            "aggregate": {"runs": len(rows), "avg_ndcg_at_8": aggregate}}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--labels", type=Path, default=Path("eval/golden/matching_labels.json"))
    parser.add_argument("--json", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = ndcg_at_k(args.bundle, args.labels)
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# NDCG@8", "", "| run | 申请人 | 交付 | NDCG@8 |", "|---|---|---|---|"]
    for row in result["rows"]:
        lines.append(f"| {row['run_id']} | {row['applicant']} | {row['delivered']} | {row['ndcg_at_8']:.2%} |")
    lines += ["", f"平均 NDCG@8：**{result['aggregate']['avg_ndcg_at_8']:.2%}**"]
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result["aggregate"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
