"""pass^k 稳定性指标（确定性）：同一冻结场景 k 次独立 trial 全部达成的比例。

pass^k = 每个场景所有 k 子集全成功的比例，再对场景取平均；
pass^1 = 所有 trial 的单次成功率。按场景 cluster bootstrap 出 CI，
不把同场景 trial 当独立样本。

用法：
    python eval/pass_k.py --matrix eval/reports --matrix-stamp v3-smoke \
        --scenarios eval/frozen/v3/scenarios.json --k 3 --out pass-k.json
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from datetime import datetime
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import stats  # noqa: E402
import quality_spec as spec  # noqa: E402

PROTOCOL = spec.PROTOCOL_VERSION
COMPLETED = {"已完成", "completed", "success", "finished"}


def read_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _matrix_dir(root: Path, stamp: str | None) -> Path:
    if (root / "matrix.json").exists():
        return root
    if stamp:
        candidate = root / f"scenario-matrix-{stamp}"
        if candidate.exists():
            return candidate
    dirs = sorted(glob.glob(str(root / "scenario-matrix-*")))
    if not dirs:
        raise FileNotFoundError(f"{root} 下没有 matrix.json 或 scenario-matrix-* 目录")
    return Path(dirs[-1])


def load_matrix(root: Path, stamp: str | None = None) -> dict[str, list[dict]]:
    directory = _matrix_dir(root, stamp)
    payload = read_json(directory / "matrix.json")
    merged: dict[str, list[dict]] = {}
    for scenario in payload.get("scenarios") or []:
        key = scenario.get("key")
        if not key:
            continue
        merged.setdefault(key, []).extend(scenario.get("runs") or [])
    deduped: dict[str, list[dict]] = {}
    for key, runs in merged.items():
        seen = {}
        for index, run in enumerate(runs):
            seen[run.get("run_id") or index] = run
        deduped[key] = list(seen.values())
    return deduped


def _target(scenario: dict, requested: int) -> int:
    expect = scenario.get("expect") or {}
    if expect.get("target") is not None:
        return max(0, int(expect["target"]))
    capacity = scenario.get("ex_ante_capacity") or {}
    eligible = (capacity.get("eligible_unbounded")
                or expect.get("ex_ante_unbounded")
                or capacity.get("eligible")
                or expect.get("ex_ante_eligible"))
    return max(0, min(requested, int(eligible))) if eligible else max(0, requested)


def _delivered(run: dict) -> int:
    value = run.get("delivered")
    if value is None:
        value = (run.get("counts") or {}).get("delivered") or 0
    return int(value)


def evaluate(matrix: dict[str, list[dict]], scenarios: list[dict], k: int = 3) -> dict:
    positive = [item for item in scenarios if item.get("run")]
    per_scenario: list[dict] = []
    missing: list[str] = []
    all_success: list[int] = []
    for scenario in positive:
        key = scenario.get("key")
        runs = matrix.get(key) or []
        if not runs:
            missing.append(key)
            continue
        requested = int(scenario.get("deliver_count") or 8)
        target = _target(scenario, requested)
        trials = [run for run in runs]
        outcomes = []
        for run in trials:
            delivered = _delivered(run)
            ok = delivered >= target and str(run.get("run_status") or "") in COMPLETED
            outcomes.append({"delivered": delivered, "ok": bool(ok),
                             "run_status": run.get("run_status"),
                             "trial": run.get("trial")})
            all_success.append(1 if ok else 0)
        n_trials = len(outcomes)
        if n_trials < k:
            missing.append(f"{key}(trials={n_trials})")
            continue
        total = math.comb(n_trials, k)
        success = sum(1 for subset in combinations(outcomes, k)
                      if all(item["ok"] for item in subset))
        per_scenario.append({
            "key": key, "target": target, "n_trials": n_trials,
            "trials": outcomes, "pass_k": round(success / total, 4),
            "pass_1": round(sum(1 for item in outcomes if item["ok"]) / n_trials, 4),
            "failure_reasons": [item for item in outcomes if not item["ok"]],
        })
    values = [row["pass_k"] for row in per_scenario]
    pass_one = [row["pass_1"] for row in per_scenario]
    clusters = [row["key"] for row in per_scenario]
    trials_min = min((row["n_trials"] for row in per_scenario), default=0)
    result = {
        "metric": "pass_k",
        "protocol": PROTOCOL,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "k": k,
        "n_scenarios": len(per_scenario),
        "n_trials": trials_min,
        "min_trials": trials_min,
        "pass_k": round(sum(values) / len(values), 4) if values else 0.0,
        "pass_1": round(sum(pass_one) / len(pass_one), 4) if pass_one else 0.0,
        "pass_k_ci95": stats.cluster_bootstrap_mean(values, clusters) if len(values) >= 2 else None,
        "pass_1_ci95": stats.cluster_bootstrap_mean(pass_one, clusters) if len(pass_one) >= 2 else None,
        "trials_total": sum(row["n_trials"] for row in per_scenario),
        "single_trial_success": round(sum(all_success) / len(all_success), 4) if all_success else 0.0,
        "missing_scenarios": missing,
        "per_scenario": per_scenario,
        "usable": len(per_scenario) >= spec.SAMPLE_FLOORS["pass_k_min_scenarios"]
        and trials_min >= spec.SAMPLE_FLOORS["pass_k_min_trials"],
        "reasons": [],
    }
    if result["n_scenarios"] < spec.SAMPLE_FLOORS["pass_k_min_scenarios"]:
        result["reasons"].append(
            f"场景数 {result['n_scenarios']} < {spec.SAMPLE_FLOORS['pass_k_min_scenarios']}")
    if trials_min < spec.SAMPLE_FLOORS["pass_k_min_trials"]:
        result["reasons"].append(
            f"trial 数 {trials_min} < {spec.SAMPLE_FLOORS['pass_k_min_trials']}")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="pass^k 稳定性指标")
    parser.add_argument("--matrix", required=True, type=Path)
    parser.add_argument("--matrix-stamp", default=None)
    parser.add_argument("--scenarios", required=True, type=Path)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    frozen = read_json(args.scenarios)
    scenarios = frozen.get("scenarios") if isinstance(frozen, dict) else frozen
    matrix = load_matrix(args.matrix, args.matrix_stamp)
    result = evaluate(matrix, scenarios or [], args.k)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("k", "n_scenarios", "n_trials", "pass_1", "pass_k", "usable", "reasons")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
