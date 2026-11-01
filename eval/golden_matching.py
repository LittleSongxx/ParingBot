#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""匹配质量指标：用 golden 标注算 Precision@K / Recall@K。

这是第一版「匹配准不准」的可重复指标，输入：
- `eval/golden/matching_labels.json`：每位申请人按规则启发式标注的 gold 候选；
- quality bundle（含 applicant / candidates / delivered 标记 / task.deliver_count）。

输出每位申请人、每个 run 的：
- gold 数、deliver 数、命中数；
- Precision@K = 命中 / delivered；
- Recall@K = 命中 / min(K, gold 数)；
- 若该申请人没有 gold 标注则跳过。

规则启发式标注不是人工逐人打分，报告里必须注明；它的作用是先把
「匹配质量」变成可跟踪、可回归的数字，而不是继续只看轮次和交付数。

用法：
  python eval/golden_matching.py --bundle analysis/quality-bundles/runs-947-949.json
  python eval/golden_matching.py --bundle ... --json /tmp/golden.json --out /tmp/golden.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_LABELS = Path(__file__).resolve().parent / "golden" / "matching_labels.json"


def evaluate(bundle_path: Path, labels_path: Path) -> dict:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    by_member = {}
    by_username = {}
    for item in labels.get("labels", []):
        by_member[item["member_id"]] = item
        if item.get("username"):
            by_username[item["username"]] = item
    rows = []
    for item in bundle.get("runs", []):
        run = item.get("run") or {}
        applicant = item.get("applicant") or {}
        task = item.get("task") or {}
        gold = by_member.get(applicant.get("id")) or by_username.get(applicant.get("username"))
        if gold is None:
            rows.append({"run_id": run.get("id"), "skipped": True,
                         "reason": f"申请人 {applicant.get('id')} 没有 golden 标注"})
            continue
        # 通过审核的人数可能大于页面展示上限；质量指标要看「用户实际看到的前 K 个」
        all_delivered = [row.get("id") for row in item.get("candidates", []) if row.get("delivered")]
        gold_ids = set(gold.get("gold_ids") or [])
        requested = task.get("deliver_count") or len(all_delivered) or 8
        delivered = all_delivered[:requested]
        hits = [candidate_id for candidate_id in delivered if candidate_id in gold_ids]
        precision = len(hits) / len(delivered) if delivered else 0.0
        recall = len(hits) / min(requested, len(gold_ids)) if gold_ids else 0.0
        rows.append({
            "run_id": run.get("id"), "run_no": run.get("run_no"),
            "applicant_id": applicant.get("id"), "applicant": applicant.get("nickname"),
            "requested": requested, "delivered": len(delivered),
            "gold": len(gold_ids), "hits": len(hits),
            "precision_at_k": round(precision, 4), "recall_at_k": round(recall, 4),
            "hit_ids": hits, "miss_gold_ids": sorted(gold_ids - set(hits)),
            "extra_ids": [candidate_id for candidate_id in delivered if candidate_id not in gold_ids],
        })
    valid = [row for row in rows if not row.get("skipped")]
    aggregate = {
        "runs": len(valid),
        "avg_precision_at_k": round(sum(row["precision_at_k"] for row in valid) / len(valid), 4) if valid else 0.0,
        "avg_recall_at_k": round(sum(row["recall_at_k"] for row in valid) / len(valid), 4) if valid else 0.0,
    }
    return {"bundle": str(bundle_path), "labels": str(labels_path),
            "method": labels.get("method"), "note": labels.get("note"),
            "rows": rows, "aggregate": aggregate}


def render(result: dict) -> str:
    lines = ["# 匹配质量指标（Precision@K / Recall@K）", "",
             f"- 标注方法：{result.get('method')}（{result.get('note')}）",
             f"- 数据包：`{result.get('bundle')}`", "",
             "| run | 申请人 | 要求 | 交付 | gold | 命中 | Precision@K | Recall@K |",
             "|---|---|---|---|---|---|---|---|"]
    for row in result.get("rows", []):
        if row.get("skipped"):
            continue
        lines.append(f"| {row['run_id']} | {row['applicant']} | {row['requested']} | "
                     f"{row['delivered']} | {row['gold']} | {row['hits']} | "
                     f"{row['precision_at_k']:.2%} | {row['recall_at_k']:.2%} |")
    agg = result.get("aggregate", {})
    lines += ["", f"平均 Precision@K：**{agg.get('avg_precision_at_k', 0):.2%}**；"
                  f"平均 Recall@K：**{agg.get('avg_recall_at_k', 0):.2%}**。",
              "", "> 规则启发式标注 v1，仅用于建立可重复基线；下一步需要人工抽检校准 gold。"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--min-precision", type=float, default=0.0)
    args = parser.parse_args(argv)
    result = evaluate(args.bundle, args.labels)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"JSON 报告：{args.json}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(render(result), encoding="utf-8")
        print(f"Markdown 报告：{args.out}")
    aggregate = result["aggregate"]
    print(json.dumps(aggregate, ensure_ascii=False))
    if aggregate["avg_precision_at_k"] < args.min_precision:
        print(f"质量门禁失败：Precision@K {aggregate['avg_precision_at_k']:.2%} "
              f"低于阈值 {args.min_precision:.2%}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
