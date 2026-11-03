"""场景矩阵运行器（数据驱动；demo 仅演示 smoke，v3 为冻结评测集）。

用法：
  python eval/run_matrix.py --suite v3 --trials 1 --label v3-smoke
  python eval/run_matrix.py --suite demo --phase ready
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DEFAULT_ENV = REPO / ".env.eval"
REPORTS = ROOT / "reports"

from lib.api import (  # noqa: E402
    Api, BALANCE_HINTS, ensure_account, ensure_moments, login, readiness_of, save_preference,
    save_profile, wait_idle, wait_run,
)
from lib.env import load_env  # noqa: E402


def load_suite(suite: str) -> list[dict]:
    if suite == "v3":
        payload = json.loads((ROOT / "frozen" / "v3" / "scenarios.json").read_text(encoding="utf-8"))
        return payload["scenarios"]
    payload = json.loads((ROOT / "suites" / "demo.json").read_text(encoding="utf-8"))
    return payload["scenarios"]


def run_trial(api: Api, admin: str, token: str, timeout: int, poll: int, index: int) -> dict:
    wait_idle(api, token, timeout=timeout, poll=poll)
    print(f"  trial {index}: 发起 /match/rerun")
    created = api.data("POST", "/match/rerun", token=token) or {}
    run_id = created.get("run_id")
    if not run_id:
        return {"trial": index, "fatal": f"没有拿到 run_id：{created}"}
    my, wall = wait_run(api, token, run_id, timeout, poll)
    run = my.get("run") or {}
    task = my.get("task") or {}
    detail = {}
    try:
        detail = api.data("GET", f"/trace/detail?run_id={run_id}", token=admin) or {}
    except Exception as exc:  # noqa: BLE001 调度详情只是加分项，取不到不阻断
        detail = {"error": str(exc)}
    stat = detail.get("stat") or {}
    step_types: dict = {}
    for step in detail.get("timeline") or []:
        key = step.get("step_type") or "未知"
        step_types[key] = step_types.get(key, 0) + 1
    return {
        "trial": index,
        "run_id": run_id,
        "run_no": run.get("run_no") or created.get("run_no"),
        "task_id": task.get("id"),
        "task_no": task.get("task_no") or created.get("task_no"),
        "task_status": task.get("status"),
        "run_status": run.get("run_status"),
        "already_running": created.get("already_running"),
        "total_round": run.get("total_round"),
        "cost_millis": run.get("cost_millis"),
        "wall_seconds": wall,
        "counts": my.get("counts"),
        "delivered": my.get("delivered"),
        "distribution": [row for row in (my.get("distribution") or []) if row.get("count")],
        "note": my.get("note"),
        "output_summary": run.get("output_summary"),
        "error_message": run.get("error_message"),
        "funnel": detail.get("funnel"),
        "stat": stat,
        "step_types": step_types,
        "rounds": len(my.get("rounds") or []),
        "round_rows": my.get("rounds") or [],
    }


def balance_hit(trial: dict) -> str | None:
    text = " ".join(str(trial.get(key) or "") for key in
                    ("error_message", "output_summary", "note", "fatal"))
    for hint in BALANCE_HINTS:
        if hint.lower() in text.lower():
            return hint
    return None


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def run_scenario(api: Api, admin: str, scenario: dict, args, env: dict) -> dict:
    key = scenario["key"]
    print(f"\n=== {key} {scenario['title']} ===")
    record = {
        "key": key,
        "title": scenario["title"],
        "account": scenario["account"],
        "expect": scenario["expect"],
        "why": scenario["why"],
        "trials_planned": scenario.get("trials", 0),
        "notes": [],
        "runs": [],
    }
    token, note = ensure_account(api, scenario["account"], scenario.get("reuse", False))
    record["account_note"] = note
    print(f"  账号：{scenario['account']}（{note}）")

    if scenario.get("profile"):
        save_profile(api, token, scenario["profile"])
        record["notes"].append("档案已保存")
    if scenario.get("preference"):
        save_preference(api, token, scenario["preference"])
        record["notes"].append("偏好已保存")
    if scenario.get("moments"):
        moment_state = ensure_moments(api, token, scenario["moments"])
        record["moments"] = moment_state
        record["notes"].append(f"动态 {moment_state.get('existing')} 条")

    member = api.data("GET", "/member/my", token=token)
    record["profile"] = member
    if member:
        record["profile_view"] = {
            field: member.get(field) for field in
            ("id", "nickname", "gender", "age", "rent_budget", "tidiness", "lease_term",
             "store_id", "store_name", "schedule_type", "has_pet", "smoking", "audit_status")
        }
    my = readiness_of(api, token)
    state = my.get("readiness") or {}
    record["readiness"] = {
        "can_run": state.get("can_run"),
        "blocker": state.get("blocker"),
        "checks": state.get("checks") or [],
        "limits": my.get("limits"),
    }
    blocker = state.get("blocker") or {}
    print(f"  readiness: can_run={state.get('can_run')} "
          f"checks={len(state.get('checks') or [])} "
          f"blocker={blocker.get('key') or '-'}")
    for check in state.get("checks") or []:
        print(f"    [{'OK' if check.get('ok') else 'NG'}] {check.get('key')}: {check.get('message')}")

    if scenario.get("probe_rerun") and not state.get("can_run"):
        body = api.call("POST", "/match/rerun", token=token)
        record["rerun_probe"] = {"code": body.get("code"), "msg": body.get("msg")}
        print(f"  直接调 /match/rerun -> {body.get('code')} {body.get('msg')}")
        record["notes"].append("已验证 API 层拒绝发起")

    if args.phase == "ready" or not scenario.get("run"):
        record["status"] = "未运行（只做前置检查）"
        return record

    if not state.get("can_run"):
        record["status"] = "未运行（readiness 阻断）"
        print("  跳过真实运行：readiness 已阻断")
        return record

    trials = args.trials or scenario.get("trials", 1)
    for index in range(1, trials + 1):
        trial = run_trial(api, admin, token, args.timeout, args.poll, index)
        record["runs"].append(trial)
        counts = trial.get("counts") or {}
        print(f"  trial {index}: {trial.get('run_status')} rounds={trial.get('total_round')} "
              f"cand={counts.get('total')} pass={counts.get('passed')} "
              f"rej={counts.get('rejected')} delivered={trial.get('delivered')} "
              f"wall={trial.get('wall_seconds')}s")
        hit = balance_hit(trial)
        if hit:
            record["status"] = f"中止：模型侧疑似余额/额度不足（命中「{hit}」）"
            record["balance_abort"] = True
            print("  !! 疑似 DeepSeek 余额/额度不足，停止后续场景")
            return record

    record["status"] = "已运行"
    return record


def summarize(record: dict) -> dict:
    runs = record.get("runs") or []
    if not runs:
        blocker = (record.get("readiness") or {}).get("blocker") or {}
        return {
            "runs": 0,
            "status": record.get("status"),
            "blocker": blocker.get("key"),
            "can_run": (record.get("readiness") or {}).get("can_run"),
        }
    walls = [row.get("wall_seconds") or 0 for row in runs]
    rounds = [row.get("total_round") or 0 for row in runs]
    delivered = [row.get("delivered") or 0 for row in runs]
    ok = [row for row in runs if row.get("run_status") == "已完成"]
    return {
        "runs": len(runs),
        "status": record.get("status"),
        "can_run": (record.get("readiness") or {}).get("can_run"),
        "completed": len(ok),
        "failed_runs": len(runs) - len(ok),
        "rounds": rounds,
        "delivered": delivered,
        "wall_seconds": walls,
        "wall_mean": round(sum(walls) / len(walls), 1),
    }


def write_outputs(records: list[dict], env: dict, args, stamp: str) -> Path:
    out_dir = REPORTS / f"scenario-matrix-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        (out_dir / f"{record['key'].lower()}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    payload = {
        "label": args.label or env.get("EVAL_LABEL"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "app_base": env.get("EVAL_APP_BASE"),
        "phase": args.phase,
        "scenarios": records,
        "summaries": {record["key"]: summarize(record) for record in records},
    }
    (out_dir / "matrix.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# 场景矩阵原始结果 · {stamp}",
        "",
        f"- 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 应用：{env.get('EVAL_APP_BASE')}",
        f"- 阶段：{args.phase}",
        "",
        "| 场景 | 账号 | readiness | 运行 | 状态 | 轮次 | 候选 | 通过 | 否决 | 交付 | 耗时(s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for record in records:
        state = record.get("readiness") or {}
        blocker = state.get("blocker") or {}
        mark = "OK" if state.get("can_run") else f"阻断:{blocker.get('key')}"
        runs = record.get("runs") or []
        if runs:
            for row in runs:
                counts = row.get("counts") or {}
                lines.append(
                    f"| {record['key']} | {record['account']} | {mark} | #{row.get('trial')} | "
                    f"{row.get('run_status')} | {row.get('total_round')} | {counts.get('total')} | "
                    f"{counts.get('passed')} | {counts.get('rejected')} | {row.get('delivered')} | "
                    f"{row.get('wall_seconds')} |")
        else:
            lines.append(f"| {record['key']} | {record['account']} | {mark} | - | "
                         f"{record.get('status')} | - | - | - | - | - | - |")
    (out_dir / "matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="场景矩阵评测（真实多 Agent 匹配）")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--suite", choices=("demo", "v3"), default="v3")
    parser.add_argument("--phase", choices=("ready", "run"), default="run")
    parser.add_argument("--only", help="只跑这些场景，逗号分隔，例如 S1,S3")
    parser.add_argument("--trials", type=int, help="覆盖每个场景的 trial 数")
    parser.add_argument("--poll", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=650,
                        help="单次运行最长等待秒数（生产 MATCH_TIMEOUT_SECONDS=600 + 缓冲）")
    parser.add_argument("--label", help="报告标签")
    parser.add_argument("--stamp", help="输出目录时间戳")
    args = parser.parse_args(argv)

    env = load_env(args.env_file)
    api = Api(env.get("EVAL_APP_BASE", "http://127.0.0.1:8080"))
    admin = login(api, env.get("EVAL_ADMIN_USERNAME", "admin"),
                  env.get("EVAL_ADMIN_PASSWORD", "admin123"))
    selected = load_suite(args.suite)
    if args.only:
        wanted = {item.strip().upper() for item in args.only.split(",") if item.strip()}
        selected = [item for item in selected if item["key"].upper() in wanted]
        if not selected:
            raise SystemExit(f"没有匹配到场景：{args.only}")

    stamp = args.stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    records: list[dict] = []
    aborted = None
    for scenario in selected:
        try:
            record = run_scenario(api, admin, scenario, args, env)
        except Exception as exc:  # noqa: BLE001 单个场景失败不该拖垮整批
            record = {"key": scenario["key"], "title": scenario["title"],
                      "account": scenario["account"], "expect": scenario["expect"],
                      "why": scenario["why"], "fatal": f"{type(exc).__name__}: {exc}",
                      "status": "场景执行出错", "runs": []}
            print(f"  !! {record['fatal']}")
        records.append(record)
        if record.get("balance_abort"):
            aborted = record["key"]
            break

    out_dir = write_outputs(records, env, args, stamp)
    print(f"\n原始结果：{out_dir}")
    if aborted:
        print(f"!! 因 {aborted} 疑似余额不足提前停止")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

