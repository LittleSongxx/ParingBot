#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析 v4 pilot matrix：交付、pass^k、CI、按容量层。

用法：
  python eval/analyze_pilot.py --matrix eval/reports/scenario-matrix-v4-pilot/matrix.json \
      --scenarios eval/frozen/v4/scenarios.json --out v4-pilot-report.md --json v4-pilot-report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import metrics  # noqa: E402

DEFAULT_K = 8
PASS_KS = (2, 3, 5)


def sha256_file(path) -> str:
    """对文件 bytes 做 sha256（scenarios 冻结指纹，跨机器可复核）。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_target(expect: dict, capacity: dict | None = None) -> int:
    """场景的可达到交付目标。

    优先用冻结的 ``expect.target``（v4 重冻时写入 min(8, 不限门店可匹配上限)）；
    老场景没有该字段时回退 min(requested, eligible_unbounded or eligible)。
    """
    expect = expect or {}
    capacity = capacity or {}
    requested = int(expect.get("requested") or DEFAULT_K)
    frozen_target = expect.get("target")
    if frozen_target is not None:
        target = int(frozen_target)
        if target > 0:
            return target
    eligible = (capacity.get("eligible_unbounded") or expect.get("ex_ante_unbounded")
                or capacity.get("eligible") or expect.get("ex_ante_eligible") or 0)
    return min(requested, int(eligible)) if eligible else requested


def target_rule(expect: dict) -> str:
    """记录 target 的来源，便于审计「口径是不是事后改的」。"""
    value = (expect or {}).get("target")
    return "expect.target" if value not in (None, 0) else "min(requested, eligible_unbounded)"


def _subset_pass(flags: list[bool], k: int) -> bool:
    """所有 k 元子集都通过才算通过（k=len(flags) 时等价于「全部 trial 都通过」）。"""
    if k <= 0 or len(flags) < k:
        return False
    return all(all(flags[index] for index in subset)
               for subset in combinations(range(len(flags)), k))


def _group_samples(groups) -> list[list[bool]]:
    """统一 groups 形态：dict[key] -> list[bool] 或直接 list[list[bool]]。"""
    if isinstance(groups, dict):
        return [list(flags) for flags in groups.values()]
    return [list(flags) for flags in groups or []]


def _enumerate_pass_power(groups, ks=PASS_KS) -> dict:
    """本地 pass^k 兜底实现：逐场景枚举所有 k 子集。

    与 ``lib.metrics.pass_power`` 同口径：只有全部场景 trial 数都 >= k 才报告该 k。
    """
    samples = _group_samples(groups)
    powers = {}
    for k in ks:
        if not samples or any(len(flags) < k for flags in samples):
            continue
        passed = sum(1 for flags in samples if _subset_pass(flags, k))
        powers[f"pass^{k}"] = round(passed / len(samples), 4)
    return powers


def _pass_power(groups, ks=PASS_KS) -> dict:
    """优先调用 ``lib.metrics.pass_power``（Lead 统一实现），否则用本地枚举。

    metrics.pass_power 的入参是 list[list[bool]]；这里兼容 dict 形态再传过去。
    """
    impl = getattr(metrics, "pass_power", None)
    if callable(impl):
        try:
            result = impl(_group_samples(groups), ks=ks)
        except (TypeError, NameError, AttributeError, ValueError, KeyError):
            result = None
        if isinstance(result, dict):
            return result
    return _enumerate_pass_power(groups, ks)


def matrix_source(matrix: dict) -> str | None:
    """matrix 的 label/tag（runner 写入的 RUN_LABEL），用于报告溯源。"""
    for key in ("label", "tag", "stamp", "source"):
        value = matrix.get(key)
        if value:
            return str(value)
    meta = matrix.get("meta") or {}
    for key in ("label", "tag", "stamp", "source"):
        value = meta.get(key)
        if value:
            return str(value)
    return None


def analyze(matrix: dict, scenarios: dict, *, scenarios_sha256: str | None = None,
            source: str | None = None) -> dict:
    scenario_map = {item["key"]: item for item in scenarios.get("scenarios", [])}
    rows = []
    groups_full: dict[str, list[bool]] = {}
    groups_cap: dict[str, list[bool]] = {}
    for record in matrix.get("scenarios", []):
        key = record.get("key")
        scenario = scenario_map.get(key) or {}
        expect = scenario.get("expect") or {}
        requested = int(expect.get("requested") or DEFAULT_K)
        # 目标交付上限：优先冻结的 expect.target；老场景回退「不限门店可匹配上限」。
        # scoped eligible 只是申请方门店偏好范围内的人数，门店只是加分项时交付可以超出，
        # 用它当 target 会把 pass^k 人为抬高。
        target = resolve_target(expect, scenario.get("ex_ante_capacity") or {})
        runs = record.get("runs") or []
        delivered = [int(run.get("delivered") or 0) for run in runs]
        discovered = [int((run.get("counts") or {}).get("total") or 0) for run in runs]
        if not delivered:
            continue
        coverage = [min(value / target, 1.0) for value in discovered] if target else []
        k = len(delivered)
        full = [value == requested for value in delivered]
        cap = [value >= target for value in delivered]
        any_ok = [value > 0 for value in delivered]
        groups_full[key] = full
        groups_cap[key] = cap
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
            "discovered": discovered,
            "coverage_mean": round(statistics.mean(coverage), 4) if coverage else 0.0,
            "coverage_range": round(max(coverage) - min(coverage), 4) if coverage else 0.0,
            "expected": requested,
            "target": target,
            "target_rule": target_rule(expect),
            "target_shortfall": any(value < target for value in delivered),
            "shortfall_causes": causes,
            "capacity_limited": target < requested,
            "delivery_rate": round(statistics.mean([value / requested for value in delivered]), 4),
            "target_attainment": round(statistics.mean(
                [min(value / target, 1.0) for value in delivered]), 4) if target else 0.0,
            # 「所有 k 子集都通过」枚举：k = 本场景 trial 数（=全部 trial 通过）
            "pass_full": _subset_pass(full, k),
            "pass_cap": _subset_pass(cap, k),
            "pass_any": _subset_pass(any_ok, k),
            "consistent": len(set(delivered)) == 1,
            "failures": sum(1 for run in runs if run.get("run_status") not in ("已完成",)),
        })
    rates = [row["delivery_rate"] for row in rows]
    attainments = [row["target_attainment"] for row in rows]
    tier_stats = {}
    for tier in ("high", "medium", "low"):
        subset = [row for row in rows if row["tier"] == tier]
        if subset:
            tier_stats[tier] = {
                "n": len(subset),
                "delivery_rate": round(statistics.mean([row["delivery_rate"] for row in subset]), 4),
                "target_attainment": round(statistics.mean([row["target_attainment"] for row in subset]), 4),
                "discovery_coverage": round(statistics.mean([row["coverage_mean"] for row in subset]), 4),
                "pass_cap": round(sum(1 for row in subset if row["pass_cap"]) / len(subset), 4),
            }
    return {
        "scenarios": len(rows),
        "trials": sorted({len(row["delivered"]) for row in rows}),
        "source": source if source is not None else matrix_source(matrix),
        "scenarios_sha256": scenarios_sha256,
        "delivery_rate": round(statistics.mean(rates), 4) if rates else 0.0,
        "delivery_ci95": metrics.bootstrap_ci(rates),
        "discovery_coverage": round(statistics.mean([row["coverage_mean"] for row in rows]), 4) if rows else 0.0,
        "low_coverage_scenarios": sorted(row["key"] for row in rows if row["coverage_mean"] < 0.99),
        "target_attainment": round(statistics.mean(attainments), 4) if attainments else 0.0,
        "target_attainment_ci95": metrics.bootstrap_ci(attainments),
        "pass_full": round(sum(1 for row in rows if row["pass_full"]) / len(rows), 4) if rows else 0.0,
        "pass_cap": round(sum(1 for row in rows if row["pass_cap"]) / len(rows), 4) if rows else 0.0,
        "pass_any": round(sum(1 for row in rows if row["pass_any"]) / len(rows), 4) if rows else 0.0,
        "pass_power_full": _pass_power(groups_full),
        "pass_power_cap": _pass_power(groups_cap),
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
    ci = result["delivery_ci95"]
    attain_ci = result.get("target_attainment_ci95") or {"lo": 0.0, "hi": 0.0}
    source = result.get("source") or "-"
    scenarios_sha = result.get("scenarios_sha256") or "-"
    lines = ["# v4 pilot 分析（真实运行）", "",
             f"- 场景 {result['scenarios']} 个；trials={result['trials']}；失败 {result['failures']}",
             f"- matrix 来源：{source}；scenarios sha256：{scenarios_sha}",
             f"- 平均交付率 **{result['delivery_rate']:.2%}**，95% CI "
             f"[{ci['lo']:.3f}, {ci['hi']:.3f}]；"
             f"target 达成率 **{result['target_attainment']:.2%}**，95% CI "
             f"[{attain_ci['lo']:.3f}, {attain_ci['hi']:.3f}]",
             f"- pass^k（全部达到 requested 8）**{result['pass_full']:.3f}**；"
             f"pass^k（达到 target）**{result['pass_cap']:.3f}**；"
             f"pass^k（>0）**{result['pass_any']:.3f}**",
             f"- pass_power（requested）：{result.get('pass_power_full') or {}}；"
             f"pass_power（target）：{result.get('pass_power_cap') or {}}",
             f"- 同场景全部 trial 交付完全一致：**{result['consistency']:.3f}**；"
             f"候选发现覆盖率 **{result.get('discovery_coverage', 0):.1%}**"
             f"（不足场景：{result.get('low_coverage_scenarios') or '无'}）", "",
             "| 层 | n | 交付率 | target 达成率 | 发现覆盖率 | pass^k(cap) |",
             "|---|---|---|---|---|---|"]
    for tier, item in result["tier_stats"].items():
        lines.append(f"| {tier} | {item['n']} | {item['delivery_rate']:.2%} | "
                     f"{item['target_attainment']:.2%} | {item.get('discovery_coverage', 0):.2%} | "
                     f"{item['pass_cap']:.3f} |")
    lines += ["", "| 场景 | tier | delivered | target | 发现覆盖 | pass_cap | 短交付原因 |",
              "|---|---|---|---|---|---|---|"]
    for row in result["rows"]:
        lines.append(f"| {row['key']} | {row['tier']} | {row['delivered']} | {row['target']} | "
                     f"{row.get('coverage_mean', 0):.0%} | {row['pass_cap']} | "
                     f"{','.join(row.get('shortfall_causes') or []) or '-'} |")
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
    result = analyze(matrix, scenarios,
                     scenarios_sha256=sha256_file(args.scenarios),
                     source=matrix_source(matrix))
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    text = render(result)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
