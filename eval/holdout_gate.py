#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Holdout 质量门禁：检查 S30-S37 的交付下限与失败数。

Holdout 不参与供给调优，因此它比调优集更能代表真实质量。
用法：
  python eval/holdout_gate.py --reports eval/reports \
      --min-avg-delivery 5.0 --max-failures 1 --out holdout-gate.md
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scenario_variance  # noqa: E402

DEFAULT_HOLDOUT = "S30,S31,S32,S34,S36,S37,S40,S42,S43,S45,S46,S47"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", type=Path, default=Path("eval/reports"))
    parser.add_argument("--holdout", default=DEFAULT_HOLDOUT)
    parser.add_argument("--min-avg-delivery", type=float, default=4.0)
    parser.add_argument("--max-failures", type=int, default=1)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    keys = {item.strip() for item in args.holdout.split(",") if item.strip()}
    rows = [item for item in scenario_variance.collect(args.reports) if item["key"] in keys]
    if not rows:
        print("没有找到 holdout 场景报告，跳过 holdout 门禁")
        return 0
    total_delivered = sum(sum(item["deliveries"]) for item in rows)
    total_capacity = sum(item["trials"] * 8 for item in rows)
    failures = sum(item["failed"] for item in rows)
    avg_delivery = total_delivered / total_capacity if total_capacity else 0.0
    failed = avg_delivery < args.min_avg_delivery / 8 or failures > args.max_failures
    result = {"holdout": sorted(keys), "runs": sum(item["trials"] for item in rows),
              "delivered": total_delivered, "capacity": total_capacity,
              "avg_delivery": round(avg_delivery * 8, 2), "failures": failures,
              "min_avg_delivery": args.min_avg_delivery, "max_failures": args.max_failures,
              "failed": failed, "rows": rows}
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Holdout 质量门禁", "",
             f"- 阈值：平均交付 ≥ {args.min_avg_delivery}/8；失败数 ≤ {args.max_failures}",
             f"- 结果：**{'通过' if not failed else '失败'}**",
             f"- 平均交付：{result['avg_delivery']}/8；失败数：{failures}", "",
             "| 场景 | trials | 交付序列 | 最低 |", "|---|---|---|---|"]
    for item in rows:
        lines.append(f"| {item['key']} | {item['trials']} | {item['deliveries']} | {item['min_delivery']} |")
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("runs", "avg_delivery", "failures", "failed")}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
