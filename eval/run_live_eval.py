#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实模型评测：用当前演示库的档案跑一次真实多 Agent 匹配，收集过程与结果。

前置：
  1) Docker 栈在跑（默认 http://127.0.0.1:8080）；
  2) 已用 eval/configure_models.py 把四个用途的模型配置写进库；
  3) .env.eval 里填好租客账号（默认 member02）与标签。

它不做的事：不自动判断「匹配好不好」——那需要人工/评测规则；它只负责把一次真实运行
的输入、轮次、工具调用、候选漏斗、否决分类、耗时与总结完整记录下来，供横向比较。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DEFAULT_ENV = REPO / ".env.eval"
REPORTS = ROOT / "reports"


def load_env(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"找不到 {path}；请先 cp .env.eval.example .env.eval 并填写")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def request(app_base: str, method: str, path: str, token: str | None = None,
            payload: dict | None = None) -> dict:
    url = app_base.rstrip("/") + "/api" + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["token"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} 调用 {path} 失败：{detail[:300]}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"连不上 {url}：{exc}. 确认 Docker 栈已启动、EVAL_APP_BASE 正确")
    if body.get("code") != "200":
        raise SystemExit(f"{path} 返回业务错误：{body.get('code')} {body.get('msg')}")
    return body.get("data")


def login(app_base: str, username: str, password: str) -> str:
    data = request(app_base, "POST", "/login", payload={"username": username, "password": password})
    token = (data or {}).get("token")
    if not token:
        raise SystemExit("登录失败：没有拿到 token")
    return token


def current_models(app_base: str, admin_token: str) -> list[dict]:
    data = request(app_base, "GET", "/aiModelConfig/selectPage?page_num=1&page_size=100",
                   token=admin_token) or {}
    rows = []
    for item in data.get("list", []):
        if item.get("enabled") == "是":
            rows.append({
                "purpose": item.get("model_purpose"),
                "model": item.get("model_name"),
                "provider": item.get("provider"),
                "base_url": item.get("base_url"),
            })
    return rows


def wait_run(app_base: str, member_token: str, run_id: int, timeout: int, poll: int) -> dict:
    deadline = time.time() + timeout
    last_status = None
    while True:
        data = request(app_base, "GET", "/match/my", token=member_token) or {}
        run = data.get("run") or {}
        status = run.get("run_status")
        if status != last_status:
            print(f"  轮询：{run.get('run_no') or run_id} -> {status}")
            last_status = status
        if run.get("id") != run_id:
            if time.time() > deadline:
                raise SystemExit("等待超时，且最新运行已经不是目标运行；请到页面查看")
        elif status not in ("运行中", "待执行", "执行中"):
            return data
        if time.time() > deadline:
            raise SystemExit(f"等待超时（{timeout}s）：运行仍在 {status}；"
                             f"请到管理端【调度时间线】查看是否卡住，或重启后查看失败原因")
        time.sleep(poll)


def run_trial(app_base: str, member_token: str, admin_token: str,
              timeout: int, poll: int, index: int) -> dict:
    print(f"\n=== Trial {index} ===")
    started = time.time()
    created = request(app_base, "POST", "/match/rerun", token=member_token) or {}
    run_id = created.get("run_id")
    if not run_id:
        raise SystemExit(f"没有拿到 run_id：{created}")
    print(f"  run_id={run_id} run_no={created.get('run_no')} task={created.get('task_no')} "
          f"already_running={created.get('already_running')}")
    data = wait_run(app_base, member_token, run_id, timeout, poll)
    elapsed = round(time.time() - started, 2)
    run = data.get("run") or {}
    task = data.get("task") or {}
    detail = {}
    try:
        detail = request(app_base, "GET", f"/trace/detail?run_id={run_id}", token=admin_token) or {}
    except SystemExit as exc:
        print(f"  [warn] 读取调度详情失败：{exc}")
    timeline = detail.get("timeline") or []
    stat = detail.get("stat") or {}
    step_types = {}
    for step in timeline:
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
        "total_round": run.get("total_round"),
        "cost_millis": run.get("cost_millis"),
        "wall_seconds": elapsed,
        "delivered": data.get("delivered"),
        "counts": data.get("counts"),
        "distribution": data.get("distribution"),
        "note": data.get("note"),
        "output_summary": run.get("output_summary"),
        "error_message": run.get("error_message"),
        "funnel": detail.get("funnel"),
        "stat": stat,
        "tool_calls": stat.get("tool_calls"),
        "steps_total": stat.get("steps"),
        "failed_steps": stat.get("failed"),
        "timeline_steps": len(timeline),
        "step_types": step_types,
        "rounds": data.get("rounds"),
    }


def markdown_report(env: dict, models: list[dict], trials: list[dict], path: Path) -> str:
    lines = [
        f"# 真实模型评测报告 · {env.get('EVAL_LABEL', 'eval')}",
        "",
        f"- 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 应用：{env.get('EVAL_APP_BASE', 'http://127.0.0.1:8080')}",
        f"- 租客：{env.get('EVAL_MEMBER_USERNAME', 'member02')}",
        f"- 模型配置：",
    ]
    for item in models:
        lines.append(f"  - {item['purpose']}：{item['provider']} / {item['model']}（{item['base_url']}）")
    lines += ["", "## 结果汇总", ""]
    header = "| Trial | 状态 | 轮次 | 候选 | 通过 | 否决 | 交付 | 耗时(s) | 工具调用 | 步骤 | 失败步骤 |"
    sep = "|---|---|---|---|---|---|---|---|---|---|---|"
    lines += [header, sep]
    for item in trials:
        counts = item.get("counts") or {}
        lines.append(
            f"| {item['trial']} | {item.get('run_status')} | {item.get('total_round')} | "
            f"{counts.get('total')} | {counts.get('passed')} | {counts.get('rejected')} | "
            f"{item.get('delivered')} | {item.get('wall_seconds')} | {item.get('tool_calls')} | "
            f"{item.get('steps_total')} | {item.get('failed_steps')} |")
    for item in trials:
        lines += ["", f"## Trial {item['trial']} · {item.get('run_no')}", ""]
        lines.append(f"- 任务：{item.get('task_no')}（{item.get('task_status')}）")
        lines.append(f"- 运行：{item.get('run_status')}，{item.get('total_round')} 轮，"
                     f"模型侧耗时 {item.get('cost_millis')} ms，总墙钟 {item.get('wall_seconds')} s")
        lines.append(f"- 候选：{item.get('counts')}；交付 {item.get('delivered')}")
        funnel = item.get("funnel") or {}
        if funnel.get("stages"):
            stages = " → ".join(f"{stage.get('label')} {stage.get('value')}" for stage in funnel["stages"])
            lines.append(f"- 漏斗：{stages}")
        distribution = item.get("distribution") or []
        if distribution:
            dist = "；".join(f"{row.get('label') or row.get('code')} {row.get('count')}"
                             for row in distribution if row.get("count"))
            lines.append(f"- 否决分类：{dist or '无'}")
        lines.append(f"- 记录：{item.get('steps_total')} 个步骤 / {item.get('tool_calls')} 次工具调用 / "
                     f"{item.get('failed_steps')} 个失败步骤（时间线 {item.get('timeline_steps')} 个调度节点）")
        if item.get("note"):
            lines.append(f"- 说明：{item['note']}")
        lines += ["", "运行总结：", "", "```", str(item.get("output_summary") or ""), "```"]
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="真实模型匹配评测（一次或多次 trial）")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--label", help="覆盖 EVAL_LABEL")
    parser.add_argument("--trials", type=int, help="覆盖 EVAL_TRIALS")
    args = parser.parse_args(argv)

    env = load_env(args.env_file)
    label = args.label or env.get("EVAL_LABEL") or "eval"
    trials = args.trials or int(env.get("EVAL_TRIALS") or 1)
    app_base = env.get("EVAL_APP_BASE", "http://127.0.0.1:8080")
    poll = int(env.get("EVAL_POLL_SECONDS") or 3)
    timeout = int(env.get("EVAL_MAX_WAIT_SECONDS") or 600)

    admin_token = login(app_base, env.get("EVAL_ADMIN_USERNAME", "admin"),
                        env.get("EVAL_ADMIN_PASSWORD", "admin123"))
    member_token = login(app_base, env.get("EVAL_MEMBER_USERNAME", "member02"),
                         env.get("EVAL_MEMBER_PASSWORD", "123456"))
    models = current_models(app_base, admin_token)
    print("当前启用的模型配置：")
    for item in models:
        print(f"  {item['purpose']}: {item['provider']} / {item['model']} @ {item['base_url']}")

    readiness = request(app_base, "GET", "/match/my", token=member_token) or {}
    state = readiness.get("readiness") or {}
    if not state.get("can_run"):
        blocker = state.get("blocker") or {}
        print("\n当前账号还不能发起真实匹配：")
        print(f"  {blocker.get('label')}: {blocker.get('message')}")
        print("\n如果是模型 Key 相关：先把 .env.eval 的 EVAL_API_KEY 填好，再运行：")
        print("  python eval/configure_models.py")
        return 2

    results = []
    for index in range(1, trials + 1):
        results.append(run_trial(app_base, member_token, admin_token, timeout, poll, index))

    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORTS / f"live-{label}-{stamp}.json"
    md_path = REPORTS / f"live-{label}-{stamp}.md"
    payload = {
        "label": label,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "app_base": app_base,
        "member": env.get("EVAL_MEMBER_USERNAME", "member02"),
        "models": models,
        "trials": results,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = markdown_report(env, models, results, md_path)
    print(f"\n报告已写入：\n  {json_path}\n  {md_path}")
    print("\n" + "\n".join(report.splitlines()[:18]))
    failed = [row for row in results if row.get("run_status") != "已完成"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
