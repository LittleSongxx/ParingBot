#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立 judge：用另一次模型调用对交付候选做 1-5 分合住适配评分。

与 heuristic/consensus 不同，它不读 gold 标签、不看审核结论，只看申请方档案/偏好
和候选档案/自我介绍/动态；用于交叉验证交付名单，不进入 CI 门禁。

用法：
  python eval/independent_judge.py --bundle analysis/quality-bundles/expanded-latest.json \
      --out analysis/independent-judge.md
"""
from __future__ import annotations
import argparse, json, math, re, urllib.request
from pathlib import Path

DEFAULT_ENV = Path(".env.eval")


def load_env(path: Path) -> dict:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def text(value) -> str:
    return str(value if value is not None else "未填")


def age_of(item: dict):
    if item.get("age") is not None:
        return item.get("age")
    birth = str(item.get("birth_date") or "")[:10]
    try:
        from datetime import date, datetime
        born = datetime.strptime(birth, "%Y-%m-%d").date()
        today = date.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except (TypeError, ValueError):
        return None


def store_of(item: dict):
    return item.get("store") or item.get("store_id")


def applicant_text(app: dict) -> str:
    pref = app.get("preference") or {}
    return "\n".join([
        f"昵称：{text(app.get('nickname'))}，性别：{text(app.get('gender'))}",
        f"年龄：{text(age_of(app))}，预算：{text(app.get('rent_budget'))} 元",
        f"计划租期：{text(app.get('lease_term'))}，门店：{text(store_of(app))}",
        f"作息：{text(app.get('schedule_type'))}，整洁：{text(app.get('tidiness'))}",
        f"养宠：{text(app.get('has_pet'))}，吸烟：{text(app.get('smoking'))}",
        f"自我介绍：{text(app.get('self_intro'))}",
        f"室友期望：{text(app.get('roommate_expectation'))}",
        "合住偏好：" + json.dumps(pref, ensure_ascii=False, default=str),
    ])


def candidate_text(c: dict) -> str:
    moments = "；".join(str(m.get("content") or "") for m in (c.get("moments") or [])[:3])
    pref = c.get("preference") or {}
    return "\n".join([
        f"昵称：{text(c.get('nickname'))}，性别：{text(c.get('gender'))}",
        f"年龄：{text(age_of(c))}，预算：{text(c.get('rent_budget'))} 元",
        f"计划租期：{text(c.get('lease_term'))}，门店：{text(store_of(c))}",
        f"作息：{text(c.get('schedule_type'))}，整洁：{text(c.get('tidiness'))}",
        f"养宠：{text(c.get('has_pet'))}，吸烟：{text(c.get('smoking'))}",
        f"自我介绍：{text(c.get('self_intro'))}",
        f"室友期望：{text(c.get('roommate_expectation'))}",
        f"动态摘录：{moments or '无'}",
        "候选方偏好：" + json.dumps(pref, ensure_ascii=False, default=str),
    ])


def judge_one(base_url: str, api_key: str, model: str, app: dict, cand: dict) -> dict:
    prompt = (
        "你是独立合租匹配评审，只根据下面双方资料判断候选是否适合这位申请方，"
        "不要参考任何已有审核结论。评分 1-5：1=明显不适合，3=一般，5=非常合适。"
        "如果资料不足，score 给 null 并说明缺什么。只输出 JSON，不要解释文字："
        '{"score": 1-5 或 null, "reason": "一句话", "missing": "缺什么/无"}。\n\n'
        "【申请方】\n" + applicant_text(app) + "\n\n【候选方】\n" + candidate_text(cand)
    )
    payload = {"model": model, "temperature": 0.0, "max_tokens": 1200,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=90) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    content = re.sub(r"```(?:json)?", "", content).strip("` \n")
    match = re.search(r"\{.*\}", content, re.S)
    data = json.loads(match.group(0)) if match else {}
    score = data.get("score")
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None
    return {"score": score, "reason": str(data.get("reason") or ""),
            "missing": str(data.get("missing") or "")}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--limit-per-run", type=int, default=8)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    env = load_env(args.env_file)
    api_key = env.get("EVAL_API_KEY")
    base_url = env.get("EVAL_BASE_URL") or "https://api.deepseek.com"
    model = env.get("EVAL_MODEL") or "deepseek-flash"
    if not api_key:
        raise SystemExit("缺少 EVAL_API_KEY，无法运行独立 judge")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    rows = []
    for run in bundle.get("runs", []):
        app = run.get("applicant") or {}
        delivered = [c for c in run.get("candidates", []) if c.get("delivered")][:args.limit_per_run]
        for cand in delivered:
            try:
                result = judge_one(base_url, api_key, model, app, cand)
            except Exception as exc:  # noqa: BLE001
                result = {"score": None, "reason": f"调用失败：{exc}", "missing": ""}
            rows.append({"run_id": run.get("run", {}).get("id"), "applicant": app.get("nickname"),
                         "candidate_id": cand.get("id"), "candidate": cand.get("nickname"), **result})
    scores = [row["score"] for row in rows if row["score"] is not None]
    aggregate = {"judged": len(scores), "errors": sum(1 for row in rows if row["score"] is None),
                 "avg_score": round(sum(scores) / len(scores), 3) if scores else 0}
    result = {"bundle": str(args.bundle), "model": model, "rows": rows, "aggregate": aggregate}
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# 独立 judge 评分", "", f"- 模型：{model}", f"- 已评：{len(scores)}；失败：{aggregate['errors']}",
             f"- 平均分：**{aggregate['avg_score']} / 5**", "",
             "| run | 申请人 | 候选 | 分数 | 理由 |", "|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['run_id']} | {row['applicant']} | {row['candidate']} | "
                     f"{row['score'] if row['score'] is not None else '—'} | {row['reason'][:80]} |")
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(aggregate, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
