#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v3 评测报告与 fail-closed 门禁（2026-11 审计后版本）。

主指标：交付率 / target 归一交付 / 完成率 / 失败数 / 安全 / 成本 / 延迟；
监控指标：heuristic agreement / NDCG（永不作为质量门禁或质量结论）。

fail-closed 规则：
* 冻结文件 / base 供给池 / eval SQL 目录任一漂移 -> 失败；
* 缺少正向场景、负向场景未按预期阻断、bundle 指纹不匹配 -> 失败；
* baseline 必须是 schema v2（含 provenance + 每场景交付），否则失败；
* 任一场景从有交付退化为 0、失败数增加、target 达成率配对回退超阈值 -> 失败；
* publish 模式必须提供真实成本与合法独立 judge 报告。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import metrics  # noqa: E402
import check_freeze  # noqa: E402
import quality_checks  # noqa: E402
import safety_checks  # noqa: E402

DEFAULT_K = 8
COMPLETED_STATUSES = {"已完成", "完成", "completed", "Completed", "done", "DONE"}
JUDGE_MIN_PAIRS = 8
JUDGE_MIN_CONSISTENCY = 0.8
TARGET_MARGIN_TARGETS = 2.0  # 允许的 target 回退约 2 人（v3 = 2/57 ≈ 3.5pp）


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_frozen(scenarios_path: Path) -> list[dict]:
    data = read_json(scenarios_path)
    return [item for item in data.get("scenarios", []) if isinstance(item, dict)]


def _matrix_source_dirs(reports_dir: Path, stamp: str | None = None) -> list[Path]:
    """只选一个 matrix 来源：给 stamp 用指定目录，否则用最新修改的目录。"""
    if not reports_dir.exists():
        return []
    if stamp:
        candidate = reports_dir / f"scenario-matrix-{stamp}"
        return [candidate] if (candidate / "matrix.json").is_file() else []
    directories = [path for path in reports_dir.glob("scenario-matrix-*")
                   if (path / "matrix.json").is_file()]
    directories.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return directories


def load_matrix(reports_dir: Path, stamp: str | None = None) -> dict[str, list[dict]]:
    """读取单个 matrix（最新或指定 stamp），按场景 key 收集 runs。"""
    sources = _matrix_source_dirs(reports_dir, stamp)
    if not sources:
        return {}
    payload = read_json(sources[0] / "matrix.json")
    merged: dict[str, list[dict]] = {}
    for scenario in payload.get("scenarios", []) or []:
        key = scenario.get("key")
        if not key:
            continue
        merged.setdefault(key, []).extend(scenario.get("runs") or [])
    deduped: dict[str, list[dict]] = {}
    for key, runs in merged.items():
        by_id: dict = {}
        for index, run in enumerate(runs):
            rid = run.get("run_id") or index
            by_id[rid] = run
        deduped[key] = list(by_id.values())
    return deduped


def load_matrix_records(reports_dir: Path, stamp: str | None = None) -> dict[str, dict]:
    """读取 matrix 的场景级原始记录（负向断言需要 status/readiness，不能只看 runs）。"""
    sources = _matrix_source_dirs(reports_dir, stamp)
    if not sources:
        return {}
    payload = read_json(sources[0] / "matrix.json")
    records: dict[str, dict] = {}
    for scenario in payload.get("scenarios", []) or []:
        key = scenario.get("key")
        if key:
            records[key] = scenario
    return records


def _scenario_target(scenario: dict, requested: int) -> int:
    """target = 显式 expect.target，否则 min(requested, 不限门店可匹配上限)。"""
    expect = scenario.get("expect") or {}
    target = expect.get("target")
    if target is None:
        capacity = scenario.get("ex_ante_capacity") or {}
        eligible = (capacity.get("eligible_unbounded")
                    or expect.get("ex_ante_unbounded")
                    or capacity.get("eligible")
                    or expect.get("ex_ante_eligible"))
        target = min(requested, int(eligible)) if eligible else requested
    return max(0, int(target))


def scenario_delivery(scenarios: list[dict], matrix: dict[str, list[dict]]) -> tuple[list[dict], list[str]]:
    """逐 trial 的交付行；target 用于容量归一与门禁。"""
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
            requested = int(requested)
            delivered = run.get("delivered")
            if delivered is None:
                delivered = (run.get("counts") or {}).get("delivered") or 0
            delivered = int(delivered)
            target = _scenario_target(scenario, requested)
            rows.append({
                "key": key,
                "trial": run.get("trial"),
                "run_status": run.get("run_status"),
                "requested": requested,
                "delivered": delivered,
                "target": target,
                "target_attainment": round(min(delivered / target, 1.0), 4) if target else 0.0,
                "wall_seconds": run.get("wall_seconds"),
            })
    return rows, missing


def _infer_negative_ok(record: dict, expect: dict) -> bool:
    """兼容旧 artifact：无 expectation_ok 字段时按可观测结果推断。"""
    if record.get("api_rejected"):
        return True
    status = str(record.get("status") or "")
    if "API 层拒绝" in status or "保存阶段" in status and "拒" in status:
        return True
    readiness = record.get("readiness") or {}
    blocker = (readiness.get("blocker") or {}).get("key") if isinstance(readiness.get("blocker"), dict) else None
    if readiness.get("can_run") is False and blocker == expect.get("blocker"):
        return True
    return False


def negative_assertions(scenarios: list[dict], matrix: dict[str, list[dict]]) -> tuple[list[dict], list[str]]:
    """负向场景必须真正被 API/readiness 阻断，否则 gate 失败。"""
    rows: list[dict] = []
    errors: list[str] = []
    for scenario in scenarios:
        if scenario.get("run"):
            continue
        key = scenario.get("key")
        expect = scenario.get("expect") or {}
        record = matrix.get(key)
        if record is None:
            errors.append(f"缺少负向场景报告：{key}")
            rows.append({"key": key, "ok": False, "expected_blocker": expect.get("blocker"),
                         "status": None, "observed": None})
            continue
        observed = record.get("negative_observed") or {}
        ok = record.get("expectation_ok")
        if ok is None:
            ok = _infer_negative_ok(record, expect)
        status = record.get("status")
        rows.append({"key": key, "ok": bool(ok), "expected_blocker": expect.get("blocker"),
                     "status": status, "observed": observed})
        if not ok:
            errors.append(f"负向场景 {key} 未按预期阻断/拒绝"
                          f"（expect={expect.get('blocker')!r}, status={status!r}）")
    return rows, errors


def _p50_p95(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    return round(statistics.median(values), 6), metrics.p95(values)


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


def _per_scenario_detail(rows: list[dict], targets: dict[str, int]) -> dict:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["key"], []).append(row)
    detail: dict = {}
    for key, values in grouped.items():
        delivered = [row["delivered"] for row in values]
        target = targets.get(key) or (values[0]["target"] if values else 0)
        attainment = [min(value / target, 1.0) for value in delivered] if target else []
        detail[key] = {
            "requested": values[0]["requested"],
            "delivered": delivered,
            "target": target,
            "target_attainment": round(statistics.mean(attainment), 4) if attainment else 0.0,
            "run_status": [row["run_status"] for row in values],
        }
    return detail


def _scenario_means(rows: list[dict], field: str) -> list[float]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(row["key"], []).append(float(row[field]))
    return [statistics.mean(values) for _, values in sorted(grouped.items())]


def _validate_baseline(baseline: dict, manifest: dict, positives: list[str],
                       labels_hash: str | None, scenarios_hash: str | None) -> list[str]:
    errors: list[str] = []
    if not isinstance(baseline, dict):
        return ["baseline 不是 JSON 对象"]
    schema = int(baseline.get("schema_version") or baseline.get("version") or 0)
    if schema < 2:
        errors.append("BASELINE 版本过旧：需要 schema_version>=2（含 source/per_scenario/target）")
    if baseline.get("protocol_version") != manifest.get("protocol_version"):
        errors.append(f"BASELINE protocol_version {baseline.get('protocol_version')!r} "
                      f"!= 当前 {manifest.get('protocol_version')!r}")
    if baseline.get("labels_sha256") != labels_hash:
        errors.append("BASELINE labels_sha256 与当前 labels.json 不一致")
    if baseline.get("scenarios_sha256") != scenarios_hash:
        errors.append("BASELINE scenarios_sha256 与当前 scenarios.json 不一致")
    per_scenario = baseline.get("per_scenario") or {}
    missing = [key for key in positives if key not in per_scenario]
    if missing:
        errors.append(f"BASELINE 缺少场景交付记录：{sorted(missing)}")
    source = baseline.get("source") or {}
    if not source.get("code_commit"):
        errors.append("BASELINE 缺少 source.code_commit（无法追溯来源）")
    if not baseline.get("model_configs"):
        errors.append("BASELINE 缺少 model_configs（无法追溯模型/温度）")
    if baseline.get("db_profile") != "eval":
        errors.append("BASELINE db_profile 必须是 eval")
    return errors


def _validate_judge(path: Path | None, production_models: set, bundle_meta: dict) -> list[str]:
    if not path or not Path(path).exists():
        return ["缺少 judge 报告（--judge）"]
    try:
        data = read_json(path)
    except (OSError, ValueError) as exc:
        return [f"judge 报告无法解析：{exc}"]
    errors: list[str] = []
    model = str(data.get("model") or "")
    if not model:
        errors.append("judge 报告缺少 model 字段")
    elif model in production_models:
        errors.append(f"judge 模型 {model} 与生产模型相同，不独立")
    meta = data.get("bundle_meta") or {}
    if meta and bundle_meta:
        for field in ("code_commit", "labels_hash", "scenarios_hash"):
            if meta.get(field) and bundle_meta.get(field) and meta.get(field) != bundle_meta.get(field):
                errors.append(f"judge 报告 bundle_meta.{field} 与本次 bundle 不一致")
    aggregate = data.get("aggregate") or {}
    mode = data.get("mode") or "pointwise"
    if mode == "pairwise":
        pairs = int(aggregate.get("pairs") or aggregate.get("judged") or 0)
        consistency = aggregate.get("position_consistency", aggregate.get("swap_consistency"))
        if pairs < JUDGE_MIN_PAIRS:
            errors.append(f"judge pairwise 有效样本 {pairs} < {JUDGE_MIN_PAIRS}")
        if consistency is None or float(consistency) < JUDGE_MIN_CONSISTENCY:
            errors.append(f"judge pairwise 位置一致性 {consistency} < {JUDGE_MIN_CONSISTENCY}")
    else:
        judged = int(aggregate.get("judged") or 0)
        if judged < JUDGE_MIN_PAIRS:
            errors.append(f"judge pointwise 有效样本 {judged} < {JUDGE_MIN_PAIRS}")
    return errors


def build(args) -> tuple[dict, str]:
    bundle = read_json(args.bundle)
    frozen = load_frozen(args.scenarios)
    scenario_meta = read_json(args.scenarios)
    matrix_sources = _matrix_source_dirs(Path(args.matrix), getattr(args, "matrix_stamp", None))
    matrix = load_matrix(Path(args.matrix), getattr(args, "matrix_stamp", None))
    matrix_records = load_matrix_records(Path(args.matrix), getattr(args, "matrix_stamp", None))
    rows, missing = scenario_delivery(frozen, matrix)
    negatives, negative_errors = negative_assertions(frozen, matrix_records)

    targets = {scenario["key"]: _scenario_target(
        scenario, int((scenario.get("expect") or {}).get("requested") or scenario.get("deliver_count") or DEFAULT_K))
        for scenario in frozen if scenario.get("run")}
    requested = sum(row["requested"] for row in rows)
    delivered = sum(row["delivered"] for row in rows)
    target_total = sum(row["target"] for row in rows)
    delivered_target = sum(min(row["delivered"], row["target"]) for row in rows)
    failures = len([row for row in rows if row["run_status"] not in COMPLETED_STATUSES])
    avg_delivered = delivered / len(rows) if rows else 0.0
    avg_requested = requested / len(rows) if rows else 0.0
    delivery_rate = delivered / requested if requested else 0.0
    target_attainment = delivered_target / target_total if target_total else 0.0

    target_ratios = _scenario_means(rows, "target_attainment")
    delivery_ratios = [row["delivered"] / row["requested"] for row in rows if row["requested"]]
    target_ci = metrics.bootstrap_ci(target_ratios)
    delivery_ci = metrics.bootstrap_ci(delivery_ratios)
    delivery_sd = round(statistics.stdev(delivery_ratios), 4) if len(delivery_ratios) > 1 else 0.0
    target_sd = round(statistics.stdev(target_ratios), 4) if len(target_ratios) > 1 else 0.0
    delivery_mde = metrics.mde_two_sample(delivery_sd, len(delivery_ratios), len(delivery_ratios)) \
        if len(delivery_ratios) > 1 and delivery_sd > 0 else None

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["key"], []).append(row)
    trials_min = min((len(values) for values in grouped.values()), default=0)
    pass_full = metrics.pass_power([[row["delivered"] >= row["requested"] for row in values]
                                    for values in grouped.values()])
    pass_cap = metrics.pass_power([[row["delivered"] >= row["target"] for row in values]
                                   for values in grouped.values()])
    pass_any = metrics.pass_power([[row["delivered"] > 0 for row in values]
                                   for values in grouped.values()])

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

    manifest = read_json(args.manifest)
    freeze_errors = check_freeze.check_manifest(Path(args.manifest).parent)
    freeze_errors += check_freeze.scan_eval_sql()
    labels_hash = _hash(args.labels)
    scenarios_hash = _hash(args.scenarios)
    bundle_meta = bundle.get("meta") or {}
    production_models = {cfg.get("model_name") for cfg in (bundle_meta.get("model_configs") or [])
                         if cfg.get("model_name")}

    meta_errors: list[str] = []
    if bundle_meta.get("scenario_suite") not in (None, "v3"):
        meta_errors.append(f"bundle scenario_suite={bundle_meta.get('scenario_suite')!r} != v3")
    if bundle_meta.get("db_profile") not in (None, "eval"):
        meta_errors.append(f"bundle db_profile={bundle_meta.get('db_profile')!r} != eval")
    if not bundle_meta.get("code_commit"):
        meta_errors.append("bundle meta 缺少 code_commit（无法追溯运行代码）")
    if bundle_meta.get("labels_hash") and bundle_meta.get("labels_hash") != labels_hash:
        meta_errors.append("bundle labels_hash 与当前 labels.json 不一致")
    if bundle_meta.get("scenarios_hash") and bundle_meta.get("scenarios_hash") != scenarios_hash:
        meta_errors.append("bundle scenarios_hash 与当前 scenarios.json 不一致")

    gates: list[str] = []
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
    gates.extend(meta_errors)

    baseline = None
    baseline_errors: list[str] = []
    if args.mode == "verify":
        baseline_path = Path(args.baseline) if args.baseline else None
        if baseline_path is None or not baseline_path.exists():
            gates.append(f"缺少 baseline：{baseline_path}；先跑 --mode baseline 并人工提交")
        else:
            baseline = read_json(baseline_path)
            positives = [scenario["key"] for scenario in frozen if scenario.get("run")]
            baseline_errors = _validate_baseline(baseline, manifest, positives, labels_hash, scenarios_hash)
            gates.extend([f"baseline: {error}" for error in baseline_errors])
            if not baseline_errors:
                regression = baseline.get("regression") or {}
                max_failures_delta = int(regression.get("max_failures_delta", 0))
                if failures > int(baseline.get("failures", 0)) + max_failures_delta:
                    gates.append(f"失败数增加：{failures} > baseline {baseline.get('failures')} + {max_failures_delta}")
                target_margin = float(regression.get("target_margin")
                                      or (TARGET_MARGIN_TARGETS / max(1, target_total)))
                baseline_per = baseline.get("per_scenario") or {}
                current_detail = _per_scenario_detail(rows, targets)
                current_targets = [current_detail[key]["target_attainment"] for key in sorted(current_detail)]
                baseline_targets = [float((baseline_per.get(key) or {}).get("target_attainment", 0.0))
                                    for key in sorted(current_detail)]
                diffs = [current - previous for current, previous in zip(current_targets, baseline_targets)]
                if diffs:
                    diff_ci = metrics.paired_diff_ci(baseline_targets, current_targets)
                    mean_diff = statistics.mean(diffs)
                    if mean_diff < -target_margin and diff_ci["hi"] < 0:
                        gates.append(f"target 达成率回退：{mean_diff:.3f} < -{target_margin:.3f}，"
                                     f"配对 95% CI [{diff_ci['lo']:.3f}, {diff_ci['hi']:.3f}]")
                for key in sorted(current_detail):
                    current = current_detail[key]["delivered"]
                    previous = (baseline_per.get(key) or {}).get("delivered") or []
                    if previous and max(previous) > 0 and max(current) == 0:
                        gates.append(f"场景 {key} 从有交付退化为 0（baseline {previous} -> {current}）")
        if negative_errors:
            gates.extend(negative_errors)

    publish = bool(getattr(args, "publish", False))
    if publish:
        price_in = args.price_input_per_m
        price_out = args.price_output_per_m
        if cost is None or not price_in or not price_out or price_in <= 0 or price_out <= 0:
            gates.append("publish 模式必须提供真实成本单价（>0，禁止 0/缺省）")
        judge_errors = _validate_judge(args.judge, production_models, bundle_meta)
        gates.extend([f"judge: {error}" for error in judge_errors])

    source_run = getattr(args, "source_run", None)
    baseline_candidate = {
        "schema_version": 2,
        "protocol_version": manifest.get("protocol_version"),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": {
            "run_id": source_run,
            "code_commit": bundle_meta.get("code_commit"),
            "bundle_generated_at": bundle_meta.get("generated_at"),
            "matrix_source": str(matrix_sources[0]) if matrix_sources else None,
            "matrix_label": None,
        },
        "labels_sha256": labels_hash,
        "scenarios_sha256": scenarios_hash,
        "model_configs": bundle_meta.get("model_configs") or [],
        "run_timeout_seconds": bundle_meta.get("run_timeout_seconds"),
        "db_profile": bundle_meta.get("db_profile"),
        "delivery": {
            "avg": round(avg_delivered, 4),
            "rate": round(delivery_rate, 4),
            "target_attainment": round(target_attainment, 4),
        },
        "requested_avg": round(avg_requested, 4),
        "target_total": target_total,
        "failures": failures,
        "runs": len(rows),
        "trials_min": trials_min,
        "per_scenario": _per_scenario_detail(rows, targets),
        "regression": {
            "max_failures_delta": 0,
            "target_margin": round(TARGET_MARGIN_TARGETS / max(1, target_total), 4),
        },
    }

    result = {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": args.mode,
            "publish": publish,
            "bundle": str(args.bundle),
            "suite": "v3",
            "labels": str(args.labels) if args.labels else None,
            "scenarios": str(args.scenarios),
            "manifest": str(args.manifest),
            "bundle_meta": bundle_meta,
            "matrix_sources": [str(path) for path in matrix_sources],
            "matrix_stamp": getattr(args, "matrix_stamp", None),
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
            "target_attainment": round(target_attainment, 4),
            "target_total": target_total,
            "ci95": {"lo": delivery_ci["lo"], "hi": delivery_ci["hi"], "n": delivery_ci["n"]},
            "target_ci95": {"lo": target_ci["lo"], "hi": target_ci["hi"], "n": target_ci["n"]},
            "sd": delivery_sd,
            "target_sd": target_sd,
            "mde_abs": delivery_mde,
            "trials_min": trials_min,
            "pass_power": pass_full,
            "pass_power_target": pass_cap,
            "pass_power_any": pass_any,
            "failures": failures,
            "per_scenario": _per_scenario(rows),
            "per_scenario_detail": _per_scenario_detail(rows, targets),
        },
        "negative_assertions": {"ok": not negative_errors, "errors": negative_errors, "rows": negatives},
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
        "baseline_validation": {"errors": baseline_errors},
        "gates": {"failed": bool(gates), "reasons": gates},
        "baseline": baseline,
        "baseline_candidate": baseline_candidate,
    }
    return result, render(result)


def render(result: dict) -> str:
    delivery = result["delivery"]
    safety = result["safety"]
    cost = result["cost"]
    latency = result["latency"]
    gates = result["gates"]
    lines = [
        "# ParingBot v3 评测报告",
        "",
        f"- 模式：{result['meta']['mode']}；publish={result['meta']['publish']}",
        f"- 生成时间：{result['meta']['generated_at']}",
        f"- bundle：{result['meta']['bundle']}",
        f"- matrix：{result['meta']['matrix_sources']}",
        "",
        "## 交付（主指标 + target 归一）",
        "",
        "| 场景 | target | 交付序列 | target 达成 |",
        "|---|---|---|---|",
    ]
    detail = delivery.get("per_scenario_detail") or {}
    for key in sorted(detail):
        item = detail[key]
        lines.append(f"| {key} | {item['target']} | {item['delivered']} | {item['target_attainment']:.2%} |")
    lines += [
        "",
        f"- 运行 {delivery['runs']} 次；平均交付 **{delivery['avg_delivered']}** / {delivery['avg_requested']}；"
        f"交付率 {delivery['delivery_rate']:.2%}；失败 {delivery['failures']}",
        f"- **target 达成率 {delivery['target_attainment']:.2%}**（目标合计 {delivery['target_total']} 人）",
        f"- 95% bootstrap CI（交付率）：[{delivery['ci95']['lo']:.3f}, {delivery['ci95']['hi']:.3f}]；"
        f"target CI：[{delivery['target_ci95']['lo']:.3f}, {delivery['target_ci95']['hi']:.3f}]",
        f"- 两样本 MDE（交付率，α=.05, power=.8）：{delivery['mde_abs']}",
        f"- pass^k（requested）：{delivery['pass_power'] or 'N/A（需要 ≥2 trials）'}",
        f"- pass^k（target）：{delivery['pass_power_target'] or 'N/A（需要 ≥2 trials）'}",
        "",
        "## 负向断言",
        "",
    ]
    for row in (result.get("negative_assertions") or {}).get("rows", []):
        lines.append(f"- {row['key']}：{'OK' if row['ok'] else 'FAIL'}；"
                     f"期望 {row.get('expected_blocker')}；实际 {row.get('status')}")
    lines += [
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
    parser.add_argument("--matrix-stamp", default=None,
                        help="只读取 scenario-matrix-<stamp>；不传则用最新目录")
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
    parser.add_argument("--publish", action="store_true", help="发布模式：隐含 require-cost + require-judge")
    parser.add_argument("--max-tokens", type=int, default=0)
    parser.add_argument("--source-run", default=None, help="baseline provenance：运行 id/artifact 标识")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--baseline-out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.publish:
        args.require_cost = True
        args.require_judge = True
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
                      "target_attainment": result["delivery"]["target_attainment"],
                      "reasons": result["gates"]["reasons"]}, ensure_ascii=False))
    return 1 if result["gates"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())