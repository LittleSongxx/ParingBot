#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测报告与 fail-closed 门禁。

主指标：交付率 / 完成率 / 失败数 / 安全 / 成本 / 延迟；
监控指标：heuristic agreement / NDCG（永不作为质量门禁或质量结论）。
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
import sys

sys.path.insert(0, str(ROOT))

from lib import metrics  # noqa: E402
import check_freeze  # noqa: E402
import quality_checks  # noqa: E402
import safety_checks  # noqa: E402

DEFAULT_K = 8


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_frozen(scenarios_path: Path) -> list[dict]:
    data = read_json(scenarios_path)
    return [item for item in data.get("scenarios", []) if isinstance(item, dict)]


def load_matrix(reports_dir: Path) -> dict[str, list[dict]]:
    """合并所有 scenario-matrix-* 报告，按场景 key 收集 runs。"""
    merged: dict[str, list[dict]] = {}
    if not reports_dir.exists():
        return merged
    for path in sorted(reports_dir.glob("scenario-matrix-*/matrix.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        for scenario in payload.get("scenarios", []) or []:
            key = scenario.get("key")
            if not key:
                continue
            merged.setdefault(key, []).extend(scenario.get("runs") or [])
    # 每个 key 内按 run_id 去重，保留最后一次
    deduped: dict[str, list[dict]] = {}
    for key, runs in merged.items():
        by_id: dict = {}
        for index, run in enumerate(runs):
            rid = run.get("run_id") or index
            by_id[rid] = run
        deduped[key] = list(by_id.values())
    return deduped


def scenario_delivery(scenarios: list[dict], matrix: dict[str, list[dict]]) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    missing: list[str] = []
    for scenario in scenarios:
        if not scenario.get("run"):
            continue
        key = scenario.get("key")
        runs = matrix.get(key) or []
        if not runs:
            missing.append(key)
            continue
        for run in runs:
            requested = (run.get("counts") or {}).get("deliver_count") or scenario.get("deliver_count") or DEFAULT_K
            delivered = run.get("delivered")
            if delivered is None:
                delivered = (run.get("counts") or {}).get("delivered") or 0
            rows.append({
                "key": key,
                "trial": run.get("trial"),
                "run_status": run.get("run_status"),
                "requested": int(requested),
                "delivered": int(delivered),
                "wall_seconds": run.get("wall_seconds"),
            })
    return rows, missing


def _p50_p95(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    ordered = sorted(values)
    return ordered[int(0.5 * (len(ordered) - 1))], ordered[int(0.95 * (len(ordered) - 1))]


def build(args) -> tuple[dict, str]:
    bundle = read_json(args.bundle)
    frozen = load_frozen(args.scenarios)
    matrix = load_matrix(args.matrix)
    rows, missing = scenario_delivery(frozen, matrix)
    requested = sum(row["requested"] for row in rows)
    delivered = sum(row["delivered"] for row in rows)
    failures = len([row for row in rows if row["run_status"] not in ("已完成",)])
    avg_delivered = delivered / len(rows) if rows else 0.0
    avg_requested = requested / len(rows) if rows else 0.0
    delivery_rate = delivered / requested if requested else 0.0
    ratios = [row["delivered"] / row["requested"] for row in rows if row["requested"]]
    delivery_ci = metrics.bootstrap_ci(ratios)
    delivery_sd = round(statistics.stdev(ratios), 4) if len(ratios) > 1 else 0.0
    delivery_mde = metrics.mde(delivery_sd, len(ratios)) if ratios else None
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row["key"], []).append(row)
    trials_min = min((len(values) for values in grouped.values()), default=0)
    pass_power = {}
    for k in (2, 3, 5):
        if trials_min >= k:
            passed = sum(1 for values in grouped.values()
                         if len(values) >= k and all(row["delivered"] >= row["requested"] for row in values[:k]))
            pass_power[f"pass^{k}"] = round(passed / len(grouped), 4) if grouped else 0.0

    checks = [quality_checks.check_run(item) for item in bundle.get("runs", [])]
    quality_errors = [error for check in checks for error in check["errors"]]
    hard_violations = sum(len(check.get("hard_rule_violations") or []) for check in checks)
    profile_warnings = [warning for check in checks
                        for warning in check.get("profile_consistency_warnings") or []]
    safety_findings = safety_checks.scan_bundle(bundle)
    safety_errors = [item for item in safety_findings if item.get("severity") == "error"]

    labels = read_json(args.labels) if args.labels and Path(args.labels).exists() else None
    agreement = metrics.agreement(bundle, labels, k=DEFAULT_K) if labels else {"aggregate": {}, "runs": []}
    ndcg = metrics.ndcg_penalized(bundle, labels, k=DEFAULT_K) if labels else {"aggregate": {}}

    prompt_tokens = sum((item.get("run") or {}).get("prompt_tokens") or 0 for item in bundle.get("runs", []))
    completion_tokens = sum((item.get("run") or {}).get("completion_tokens") or 0 for item in bundle.get("runs", []))
    total_tokens = prompt_tokens + completion_tokens
    cost = None
    if args.price_input_per_m is not None and args.price_output_per_m is not None:
        cost = round(prompt_tokens / 1_000_000 * args.price_input_per_m
                     + completion_tokens / 1_000_000 * args.price_output_per_m, 6)
    durations = [float(row["wall_seconds"]) for row in rows if row.get("wall_seconds") is not None]
    p50, p95 = _p50_p95(durations)

    freeze_errors = check_freeze.check_manifest(Path(args.manifest).parent)
    freeze_errors += check_freeze.scan_eval_sql()

    gates: list[str] = []
    if freeze_errors:
        gates.extend(freeze_errors)
    if missing:
        gates.append(f"缺少必需场景报告：{sorted(missing)}")
    if not rows:
        gates.append("没有任何场景运行数据")
    if safety_errors:
        gates.append(f"安全 error {len(safety_errors)} 条")
    if hard_violations:
        gates.append(f"硬规则违规 {hard_violations} 条")
    if quality_errors:
        gates.append(f"数据一致性错误 {len(quality_errors)} 条")
    if args.max_tokens and total_tokens > args.max_tokens:
        gates.append(f"token {total_tokens} 超过预算 {args.max_tokens}")
    if args.require_cost and cost is None:
        gates.append("缺少成本单价（--price-input-per-m / --price-output-per-m）")
    if args.require_judge and not (args.judge and Path(args.judge).exists()):
        gates.append("缺少 judge 报告（--judge）")

    baseline = None
    baseline_path = Path(args.baseline) if args.baseline else None
    baseline_candidate = {
        "version": 1,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "delivery_avg": round(avg_delivered, 4),
        "delivery_rate": round(delivery_rate, 4),
        "requested_avg": round(avg_requested, 4),
        "failures": failures,
        "runs": len(rows),
        "regression_margin_delivery": 1.0,
        "max_failures_delta": 1,
        "labels_sha256": _hash(args.labels),
        "scenarios_sha256": _hash(args.scenarios),
    }
    if args.mode == "verify":
        if baseline_path is None or not baseline_path.exists():
            gates.append(f"缺少 baseline：{baseline_path}；先跑 --mode baseline 并人工提交")
        else:
            baseline = read_json(baseline_path)
            margin = float(baseline.get("regression_margin_delivery", 1.0))
            if avg_delivered < float(baseline.get("delivery_avg", 0.0)) - margin:
                gates.append(f"交付回退：{avg_delivered:.2f} < baseline {baseline.get('delivery_avg')} - {margin}")
            if failures > int(baseline.get("failures", 0)) + int(baseline.get("max_failures_delta", 1)):
                gates.append(f"失败数增加：{failures} > baseline {baseline.get('failures')}")

    result = {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": args.mode,
            "bundle": str(args.bundle),
            "suite": "v3",
            "labels": str(args.labels) if args.labels else None,
            "scenarios": str(args.scenarios),
            "manifest": str(args.manifest),
            "bundle_meta": bundle.get("meta"),
            "price_input_per_m": args.price_input_per_m,
            "price_output_per_m": args.price_output_per_m,
        },
        "delivery": {
            "runs": len(rows),
            "requested_total": requested,
            "delivered_total": delivered,
            "avg_delivered": round(avg_delivered, 4),
            "avg_requested": round(avg_requested, 4),
            "delivery_rate": round(delivery_rate, 4),
            "ci95": {"lo": delivery_ci["lo"], "hi": delivery_ci["hi"], "n": delivery_ci["n"]},
            "sd": delivery_sd,
            "mde_abs": delivery_mde,
            "trials_min": trials_min,
            "pass_power": pass_power,
            "failures": failures,
            "per_scenario": _per_scenario(rows),
        },
        "quality": {
            "hard_rule_violations": hard_violations,
            "data_consistency_errors": quality_errors,
            "profile_consistency_warnings": profile_warnings,
            "checks": checks,
        },
        "safety": {
            "errors": len(safety_errors),
            "warnings": len([item for item in safety_findings if item.get("severity") == "warning"]),
            "findings": safety_findings[:50],
        },
        "agreement": agreement.get("aggregate"),
        "ndcg": ndcg.get("aggregate"),
        "cost": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                 "total_tokens": total_tokens, "estimated_cost": cost, "currency": "CNY"},
        "latency": {"p50_seconds": p50, "p95_seconds": p95, "n": len(durations)},
        "gates": {"failed": bool(gates), "reasons": gates},
        "baseline": baseline,
        "baseline_candidate": baseline_candidate,
    }
    return result, render(result)


def _hash(path) -> str | None:
    if not path or not Path(path).exists():
        return None
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _per_scenario(rows: list[dict]) -> dict:
    out: dict[str, list[int]] = {}
    for row in rows:
        out.setdefault(row["key"], []).append(row["delivered"])
    return out


def render(result: dict) -> str:
    delivery = result["delivery"]
    safety = result["safety"]
    cost = result["cost"]
    latency = result["latency"]
    gates = result["gates"]
    lines = [
        "# ParingBot v3 评测报告",
        "",
        f"- 模式：{result['meta']['mode']}",
        f"- 生成时间：{result['meta']['generated_at']}",
        f"- bundle：{result['meta']['bundle']}",
        "",
        "## 交付（主指标）",
        "",
        "| 场景 | 交付序列 |",
        "|---|---|",
    ]
    for key, values in sorted(delivery["per_scenario"].items()):
        lines.append(f"| {key} | {values} |")
    lines += [
        "",
        f"- 运行 {delivery['runs']} 次；平均交付 **{delivery['avg_delivered']}** / {delivery['avg_requested']}；"
        f"交付率 {delivery['delivery_rate']:.2%}；失败 {delivery['failures']}",
        f"- 95% bootstrap CI（交付率）：[{delivery['ci95']['lo']:.3f}, {delivery['ci95']['hi']:.3f}]；"
        f"SD={delivery['sd']}；MDE(α=.05,power=.8)={delivery['mde_abs']}",
        f"- pass^k：{delivery['pass_power'] or 'N/A（每场景需要 ≥2 trials）'}",
        "",
        "",
        "## 质量与安全",
        "",
        f"- 硬规则违规：{result['quality']['hard_rule_violations']}",
        f"- 数据一致性错误：{len(result['quality']['data_consistency_errors'])}",
        f"- 档案自洽 warning：{len(result['quality'].get('profile_consistency_warnings') or [])}（不门禁）",
        f"- 安全 error / warning：{safety['errors']} / {safety['warnings']}",
        f"- 成本：{cost['estimated_cost']}（token {cost['total_tokens']}）",
        f"- 延迟 P50/P95：{latency['p50_seconds']}s / {latency['p95_seconds']}s",
        "",
        "> heuristic agreement / NDCG 仅监控，**不作为质量结论或门禁**。",
        f"> agreement：{json.dumps(result['agreement'], ensure_ascii=False)}",
        "",
        "## 门禁",
        "",
    ]
    if gates["failed"]:
        lines += [f"- ❌ {reason}" for reason in gates["reasons"]]
    else:
        lines.append("- ✅ 通过")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="v3 评测报告与 fail-closed 门禁")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--matrix", required=True, type=Path)
    parser.add_argument("--labels", type=Path, default=ROOT / "frozen" / "v3" / "labels.json")
    parser.add_argument("--scenarios", type=Path, default=ROOT / "frozen" / "v3" / "scenarios.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "frozen" / "v3" / "MANIFEST.json")
    parser.add_argument("--baseline", type=Path, default=ROOT / "frozen" / "v3" / "BASELINE.json")
    parser.add_argument("--mode", choices=("baseline", "verify"), default="verify")
    parser.add_argument("--price-input-per-m", type=float, default=None)
    parser.add_argument("--price-output-per-m", type=float, default=None)
    parser.add_argument("--require-cost", action="store_true")
    parser.add_argument("--require-judge", action="store_true")
    parser.add_argument("--judge", type=Path, default=None)
    parser.add_argument("--max-tokens", type=int, default=0)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--baseline-out", type=Path, default=None)
    args = parser.parse_args(argv)
    result, text = build(args)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.baseline_out:
        args.baseline_out.write_text(json.dumps(result["baseline_candidate"], ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    print(json.dumps({"mode": args.mode, "failed": result["gates"]["failed"],
                      "delivery_avg": result["delivery"]["avg_delivered"],
                      "reasons": result["gates"]["reasons"]}, ensure_ascii=False))
    return 1 if result["gates"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
