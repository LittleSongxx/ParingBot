"""交付召回率（容量归一）—— 确定性指标，不需要 judge。

recall = min(delivered, target) / target，target = min(requested, eligible_unbounded)；
同时报告交付精度（交付候选里真正通过双向硬规则的比例）与逐场景漏斗归因：
供给/发现不足、审核否决、容量上限。

用法：
    python eval/delivery_recall.py --bundle quality-bundle.json \
        --scenarios eval/frozen/v3/scenarios.json --out delivery-recall.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import rules, stats  # noqa: E402
import pairwise_quality as pq  # noqa: E402
import quality_spec as spec  # noqa: E402

PROTOCOL = spec.PROTOCOL_VERSION
REJECT_STATUS = {"否决", "rejected", "MISMATCH_HARD", "PREFERENCE_CONFLICT",
                 "PORTRAIT_INSUFFICIENT"}


def read_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _scenario_target(scenario: dict, requested: int) -> int:
    expect = scenario.get("expect") or {}
    target = expect.get("target")
    if target is not None:
        return max(0, int(target))
    capacity = scenario.get("ex_ante_capacity") or {}
    eligible = (capacity.get("eligible_unbounded")
                or expect.get("ex_ante_unbounded")
                or capacity.get("eligible")
                or expect.get("ex_ante_eligible"))
    return max(0, min(requested, int(eligible))) if eligible else max(0, requested)


def _person(dict_person: dict):
    member = pq.member_from_person(dict_person)
    preference = pq.preference_from_person(dict_person)
    return member, preference


def _eligible(applicant: dict, candidate: dict) -> bool:
    """双向硬规则复核：与 backend auditor_service / eval/lib/rules 同口径。"""
    try:
        app_member, app_pref = _person(applicant)
        cand_member, cand_pref = _person(candidate)
        return rules.is_hard_eligible(app_member, app_pref, cand_member, cand_pref)
    except Exception:  # noqa: BLE001 - 数据缺失时按"不可判定"处理，但会计入 unverifiable
        return False


def _runs_for_scenario(scenario: dict, runs: list[dict]) -> list[dict]:
    """同一场景可能有多次 trial（v4 pilot 12 场景 x3 trials），全部收集。"""
    account = scenario.get("account")
    matched = []
    for run in runs:
        applicant = run.get("applicant") or {}
        if account and (applicant.get("username") == account
                        or applicant.get("account") == account):
            matched.append(run)
    return matched


def _row_for_run(scenario: dict, run: dict, trial: int, deliver_default: int) -> dict:
    task = run.get("task") or {}
    requested = int(task.get("deliver_count") or scenario.get("deliver_count") or deliver_default)
    delivered = int(run.get("delivered_to_user") or 0)
    candidates = [item for item in (run.get("candidates") or []) if isinstance(item, dict)]
    discovered = len(candidates)
    rejected = sum(1 for item in candidates
                   if str(item.get("audit_status") or "") in REJECT_STATUS
                   or bool(item.get("reject_code")))
    target = _scenario_target(scenario, requested)
    attainment = round(min(delivered / target, 1.0), 4) if target else 0.0
    delivered_rows = [item for item in candidates if item.get("delivered")]
    eligible_count = sum(1 for item in delivered_rows
                         if _eligible(run.get("applicant") or {}, item))
    precision = round(eligible_count / len(delivered_rows), 4) if delivered_rows else 0.0
    shortfall = target - delivered
    if shortfall <= 0:
        cause = "none"
    elif discovered < target:
        cause = "supply_or_discovery"
    elif rejected > 0 and (discovered - rejected) < target:
        cause = "audit_reject"
    else:
        cause = "capacity_or_policy"
    return {
        "key": scenario.get("key"), "trial": trial,
        "requested": requested, "target": target,
        "delivered": delivered, "discovered": discovered, "rejected": rejected,
        "attainment": attainment, "precision": precision,
        "delivered_eligible": eligible_count, "shortfall_cause": cause,
        "run_no": (run.get("run") or {}).get("run_no"),
    }


def evaluate(bundle: dict, scenarios: list[dict], deliver_default: int = 8) -> dict:
    runs = [run for run in (bundle.get("runs") or []) if isinstance(run, dict)]
    positive = [item for item in scenarios if item.get("run")]
    rows: list[dict] = []
    unmatched: list[str] = []
    used_runs: set[int] = set()
    scenario_keys: list[str] = []
    accounts = {str(item.get("account")) for item in positive if item.get("account")}
    has_account_match = any(
        str((run.get("applicant") or {}).get("username") or "") in accounts
        for run in runs)
    for scenario in positive:
        matched = _runs_for_scenario(scenario, runs)
        if not matched and not has_account_match:
            # 兼容无 username 的旧 bundle：按场景顺序与 run 顺序一一对应
            index = positive.index(scenario)
            if index < len(runs):
                matched = [runs[index]]
            else:
                unmatched.append(scenario.get("key"))
                continue
        if not matched:
            unmatched.append(scenario.get("key"))
            continue
        scenario_keys.append(scenario.get("key"))
        for trial, run in enumerate(matched, start=1):
            used_runs.add(id(run))
            rows.append(_row_for_run(scenario, run, trial, deliver_default))

    attainment_values = [row["attainment"] for row in rows]
    precision_values = [row["precision"] for row in rows]
    cluster_keys = [row["key"] for row in rows]
    trials_per_scenario = {}
    for row in rows:
        trials_per_scenario[row["key"]] = trials_per_scenario.get(row["key"], 0) + 1
    n_trials = min(trials_per_scenario.values()) if trials_per_scenario else 0
    result = {
        "metric": "delivery_recall",
        "protocol": PROTOCOL,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "n_scenarios": len(scenario_keys),
        "n_trials": n_trials,
        "n_runs": len(rows),
        "requested_total": sum(row["requested"] for row in rows),
        "target_total": sum(row["target"] for row in rows),
        "delivered_total": sum(row["delivered"] for row in rows),
        "mean_attainment": round(sum(attainment_values) / len(attainment_values), 4)
        if attainment_values else 0.0,
        "attainment_ci95": stats.cluster_bootstrap_mean(
            attainment_values, cluster_keys) if len(rows) >= 2 else None,
        "mean_precision": round(sum(precision_values) / len(precision_values), 4)
        if precision_values else 0.0,
        "precision_ci95": stats.cluster_bootstrap_mean(
            precision_values, cluster_keys) if len(rows) >= 2 else None,
        "causes": {
            cause: sum(1 for row in rows if row["shortfall_cause"] == cause)
            for cause in ("none", "supply_or_discovery", "audit_reject", "capacity_or_policy")
        },
        "unmatched_scenarios": unmatched,
        "unused_runs": max(0, len(runs) - len(used_runs)),
        "per_scenario": rows,
        "usable": len(scenario_keys) >= 8 and n_trials >= 1,
        "reasons": [] if len(scenario_keys) >= 8 else [f"匹配到的场景数 {len(scenario_keys)} < 8"],
    }
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="交付召回率（确定性，容量归一）")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--scenarios", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--deliver-default", type=int, default=8)
    args = parser.parse_args(argv)
    bundle = read_json(args.bundle)
    frozen = read_json(args.scenarios)
    scenarios = frozen.get("scenarios") if isinstance(frozen, dict) else frozen
    result = evaluate(bundle, scenarios or [], args.deliver_default)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("n_scenarios", "mean_attainment", "mean_precision", "causes", "usable")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
