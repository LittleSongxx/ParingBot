#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析 v4 pilot matrix：交付、pass^k、CI、按容量层。

用法：
  python eval/analyze_pilot.py --matrix eval/reports/scenario-matrix-v4-pilot/matrix.json \
      --scenarios eval/frozen/v4/scenarios.json --out v4-pilot-report.md --json v4-pilot-report.json
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path


def bootstrap_ci(values: list[float], iterations: int = 5000, seed: int = 20261104) -> dict:
    if not values:
        return {"n": 0, "mean": 0.0, "lo": 0.0, "hi": 0.0}
    rng = random.Random(seed)
    means = []
    for _ in range(iterations):
        means.append(sum(values[rng.randrange(len(values))] for _ in range(len(values))) / len(values))
    means.sort()
    return {"n": len(values), "mean": round(statistics.mean(values), 4),
            "lo": round(means[int(0.025 * iterations)], 4),
            "hi": round(means[min(iterations - 1, int(0.975 * iterations))], 4)}


def analyze(matrix: dict, scenarios: dict) -> dict:
    scenario_map = {item["key"]: item for item in scenarios.get("scenarios", [])}
    rows = []
    for record in matrix.get("scenarios", []):
        key = record.get("key")
        scenario = scenario_map.get(key) or {}
        runs = record.get("runs") or []
        expected = int((scenario.get("expect") or {}).get("requested") or 8)
        # 目标交付上限：ex_ante_unbounded（不限门店）才是“实际可达到”的上界。
        # scoped eligible 只是申请方门店偏好范围内的人数；门店只是加分项时，
        # 交付名单可以超出该范围，用 scoped 当 target 会把 pass^k 人为抬高。
        capacity = scenario.get("ex_ante_capacity") or {}
        eligible = (capacity.get("eligible_unbounded")
                    or (scenario.get("expect") or {}).get("ex_ante_unbounded")
                    or (scenario.get("expect") or {}).get("ex_ante_eligible") or 0)
        target = min(expected, int(eligible)) if eligible else expected
        delivered = [int(run.get("delivered") or 0) for run in runs]
        if not delivered:
            continue
        k = len(delivered)
        full = [value == expected for value in delivered]
        cap = [value >= target for value in delivered]
        any_ok = [value > 0 for value in delivered]
        causes = []
        for run in runs:
            counts = run.get("counts") or {}
            total = int(counts.get("total") or 0)
            passed = int(counts.get("passed") or 0)
            value = int(run.get("delivered") or 0)
            if value >= target:
                continue
            if total < target:
                causes.append("supply")
            elif passed < target:
                causes.append("audit")
            else:
                causes.append("other")
        rows.append({
            "key": key,
            "tier": (scenario.get("ex_ante_capacity") or {}).get("tier"),
            "delivered": delivered,
            "expected": expected,
            "target": target,
            "target_shortfall": any(value < target for value in delivered),
            "shortfall_causes": causes,
            "capacity_limited": target < expected,
            "delivery_rate": round(statistics.mean([value / expected for value in delivered]), 4),
            "pass_full": all(full),
            "pass_cap": all(cap),
            "pass_any": all(any_ok),
            "consistent": len(set(delivered)) == 1,
            "failures": sum(1 for run in runs if run.get("run_status") not in ("已完成",)),
        })
    rates = [row["delivery_rate"] for row in rows]
    tier_stats = {}
    for tier in ("high", "medium", "low"):
        subset = [row for row in rows if row["tier"] == tier]
        if subset:
            tier_stats[tier] = {
                "n": len(subset),
                "delivery_rate": round(statistics.mean([row["delivery_rate"] for row in subset]), 4),
                "pass_cap": round(sum(1 for row in subset if row["pass_cap"]) / len(subset), 4),
            }
    return {
        "scenarios": len(rows),
        "trials": sorted({len(row["delivered"]) for row in rows}),
        "delivery_rate": round(statistics.mean(rates), 4) if rates else 0.0,
        "delivery_ci95": bootstrap_ci(rates),
        "pass_full": round(sum(1 for row in rows if row["pass_full"]) / len(rows), 4) if rows else 0.0,
        "pass_cap": round(sum(1 for row in rows if row["pass_cap"]) / len(rows), 4) if rows else 0.0,
        "pass_any": round(sum(1 for row in rows if row["pass_any"]) / len(rows), 4) if rows else 0.0,
        "consistency": round(sum(1 for row in rows if row["consistent"]) / len(rows), 4) if rows else 0.0,
        "failures": sum(row["failures"] for row in rows),
        "shortfall": {
            "scenarios_target_short": sum(1 for row in rows if row.get("target_shortfall")),
            "causes": {cause: sum(1 for row in rows if cause in (row.get("shortfall_causes") or []))
                       for cause in ("supply", "audit", "other")},
            "capacity_limited": sum(1 for row in rows if row.get("capacity_limited")),
        },
        "tier_stats": tier_stats,
        "rows": rows,
    }


def render(result: dict) -> str:
    lines = ["# v4 pilot 分析（真实运行）", "",
             f"- 场景 {result['scenarios']} 个；trials={result['trials']}；失败 {result['failures']}",
             f"- 平均交付率 **{result['delivery_rate']:.2%}**，95% CI "
             f"[{result['delivery_ci95']['lo']:.3f}, {result['delivery_ci95']['hi']:.3f}]",
             f"- pass^k（全部达到 requested 8）**{result['pass_full']:.3f}**；"
             f"pass^k（达到 min(8, 容量)）**{result['pass_cap']:.3f}**；"
             f"pass^k（>0）**{result['pass_any']:.3f}**",
             f"- 同场景三 trial 交付完全一致：**{result['consistency']:.3f}**", "",
             "| 层 | n | 交付率 | pass^k(cap) |", "|---|---|---|---|"]
    for tier, item in result["tier_stats"].items():
        lines.append(f"| {tier} | {item['n']} | {item['delivery_rate']:.2%} | {item['pass_cap']:.3f} |")
    lines += ["", "| 场景 | tier | delivered | target | pass_cap | 短交付原因 |",
              "|---|---|---|---|---|---|"]
    for row in result["rows"]:
        lines.append(f"| {row['key']} | {row['tier']} | {row['delivered']} | {row['target']} | "
                     f"{row['pass_cap']} | {','.join(row.get('shortfall_causes') or []) or '-'} |")
    shortfall = result["shortfall"]
    lines += ["", f"- 短交付场景：{shortfall['scenarios_target_short']} 个；原因 {shortfall['causes']}；"
              f"容量上限低于 requested：{shortfall['capacity_limited']} 个"]
    lines += ["", "> 这是真实运行结果；样本仍小（pilot），不能当作完整 v4 质量结论。"]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="分析 v4 pilot 结果")
    parser.add_argument("--matrix", required=True, type=Path)
    parser.add_argument("--scenarios", type=Path, default=Path("eval/frozen/v4/scenarios.json"))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    scenarios = json.loads(args.scenarios.read_text(encoding="utf-8"))
    result = analyze(matrix, scenarios)
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    text = render(result)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
