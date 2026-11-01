#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景方差报告：从 eval/reports/scenario-matrix-* 读同一场景的多次 trial。

用法：
  python eval/scenario_variance.py --reports eval/reports --out scenario-variance.md
"""
from __future__ import annotations
import argparse, json
from pathlib import Path


def collect(reports: Path) -> list[dict]:
    rows: dict[str, dict] = {}
    seen = set()
    for path in sorted(reports.glob("scenario-matrix-*/matrix.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for scenario in data.get("scenarios", []):
            key = scenario.get("key")
            title = scenario.get("title")
            for run in scenario.get("runs") or []:
                run_id = run.get("run_id")
                if run_id in seen:
                    continue
                seen.add(run_id)
                item = rows.setdefault(key, {"key": key, "title": title, "runs": []})
                item["runs"].append({
                    "run_id": run_id, "status": run.get("run_status"),
                    "delivered": run.get("delivered"), "rounds": run.get("total_round"),
                    "wall_seconds": run.get("wall_seconds"),
                    "candidates": (run.get("counts") or {}).get("total"),
                })
    result = []
    for item in rows.values():
        deliveries = [r["delivered"] or 0 for r in item["runs"]]
        statuses = [r["status"] for r in item["runs"]]
        result.append({
            "key": item["key"], "title": item["title"], "trials": len(item["runs"]),
            "deliveries": deliveries,
            "min_delivery": min(deliveries) if deliveries else 0,
            "max_delivery": max(deliveries) if deliveries else 0,
            "avg_delivery": round(sum(deliveries) / len(deliveries), 2) if deliveries else 0,
            "completed": statuses.count("已完成"),
            "failed": sum(1 for status in statuses if status != "已完成"),
            "runs": item["runs"],
        })
    result.sort(key=lambda item: int(item["key"][1:]))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", type=Path, default=Path("eval/reports"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    rows = collect(args.reports)
    payload = {"reports": str(args.reports), "scenarios": rows}
    if args.json:
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# 场景 trial 方差报告", "", f"- 报告目录：`{args.reports}`", "",
             "| 场景 | 标题 | trials | 交付序列 | 最低 | 最高 | 平均 | 完成/失败 |",
             "|---|---|---|---|---|---|---|---|"]
    for item in rows:
        lines.append(f"| {item['key']} | {item['title']} | {item['trials']} | "
                     f"{item['deliveries']} | {item['min_delivery']} | {item['max_delivery']} | "
                     f"{item['avg_delivery']} | {item['completed']}/{item['failed']} |")
    lines += ["", "交付序列按 run 去重后统计；失败包含非「已完成」运行。"]
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"scenarios": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
