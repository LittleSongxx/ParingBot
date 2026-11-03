#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立 judge：跨模型族评估交付候选（pointwise / pairwise）。

独立性约束：judge 模型不得与生产模型相同；相同必须显式 --allow-same-model（仅探索）。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from lib.env import load_env  # noqa: E402

DEFAULT_ENV = ROOT.parent / ".env.eval"
POINT_PROMPT = """你是独立合租匹配评审。只根据双方资料判断候选是否适合该申请方，不要参考已有审核结论。
评分 1-5：1=明显不适合，3=一般，5=非常合适。资料不足时 score=null 并说明缺什么。
只输出 JSON，不要解释：{"score": 1-5 或 null, "reason": "一句话", "missing": "缺什么/无"}。

【申请方】
{applicant}

【候选方】
{candidate}
"""
PAIR_PROMPT = """你是独立合租匹配评审。下面有两个候选（A/B），请判断对申请方而言谁更适合合租。
只输出 JSON：{"winner": "A" 或 "B" 或 "tie", "reason": "一句话"}。

【申请方】
{applicant}

【候选 A】
{candidate_a}

【候选 B】
{candidate_b}
"""


def text(item: dict) -> str:
    pref = item.get("preference") or {}
    return json.dumps({
        "nickname": item.get("nickname"), "gender": item.get("gender"), "age": item.get("age"),
        "birth_date": item.get("birth_date"), "rent_budget": item.get("rent_budget"),
        "lease_term": item.get("lease_term"), "store": item.get("store") or item.get("store_id"),
        "schedule_type": item.get("schedule_type"), "tidiness": item.get("tidiness"),
        "has_pet": item.get("has_pet"), "smoking": item.get("smoking"),
        "self_intro": item.get("self_intro"), "roommate_expectation": item.get("roommate_expectation"),
        "interest_tags": item.get("interest_tags"), "preference": pref,
    }, ensure_ascii=False, default=str)


def call(env: dict, prompt: str, model: str, base_url: str, api_key: str) -> dict:
    payload = {"model": model, "temperature": 0.0, "max_tokens": 1200,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions",
                                 data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {api_key}"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=90) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = re.sub(r"```(?:json)?", "", body["choices"][0]["message"]["content"]).strip("` \n")
    match = re.search(r"\{.*\}", content, re.S)
    return json.loads(match.group(0)) if match else {}


def delivered(bundle: dict) -> list[dict]:
    rows = []
    for run in bundle.get("runs", []):
        app = run.get("applicant") or {}
        for candidate in run.get("candidates", []):
            if candidate.get("delivered"):
                rows.append({"run": run, "applicant": app, "candidate": candidate})
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="独立 judge（跨模型族）")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--mode", choices=("pointwise", "pairwise"), default="pointwise")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--sample-not-delivered", type=int, default=0)
    parser.add_argument("--human-labels", type=Path, default=None)
    parser.add_argument("--allow-same-model", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    env = load_env(args.env_file)
    provider = env.get("EVAL_JUDGE_PROVIDER")
    api_key = env.get("EVAL_JUDGE_API_KEY") or ""
    base_url = env.get("EVAL_JUDGE_BASE_URL") or ""
    model = env.get("EVAL_JUDGE_MODEL") or ""
    if not all([provider, api_key, base_url, model]):
        raise SystemExit("缺少 EVAL_JUDGE_PROVIDER/BASE_URL/API_KEY/MODEL；judge 必须独立配置")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    production = {cfg.get("model_name") for cfg in ((bundle.get("meta") or {}).get("model_configs") or [])}
    if model in production and not args.allow_same_model:
        raise SystemExit(f"judge 模型 {model} 与生产模型相同，不独立；换不同模型族，或显式 --allow-same-model（仅探索）")
    rows = delivered(bundle)
    if not rows:
        raise SystemExit("bundle 中没有交付候选")
    scored = []
    for index, row in enumerate(rows):
        if args.mode == "pointwise":
            prompt = POINT_PROMPT.format(applicant=text(row["applicant"]), candidate=text(row["candidate"]))
            try:
                data = call(env, prompt, model, base_url, api_key)
                scored.append({"index": index, "candidate": row["candidate"].get("nickname"),
                               "score": data.get("score"), "reason": data.get("reason")})
            except Exception as exc:  # noqa: BLE001
                scored.append({"index": index, "candidate": row["candidate"].get("nickname"),
                               "score": None, "error": str(exc)})
    scores = [item["score"] for item in scored if isinstance(item.get("score"), (int, float))]
    result = {
        "mode": args.mode, "provider": provider, "model": model,
        "rows": scored,
        "aggregate": {"judged": len(scores), "errors": len(scored) - len(scores),
                      "avg_score": round(sum(scores) / len(scores), 3) if scores else None},
    }
    lines = ["# 独立 judge 报告", "", f"- 模式：{args.mode}；模型：{model}（{provider}）",
             f"- 已评：{result['aggregate']['judged']}；失败：{result['aggregate']['errors']}",
             f"- 平均分：{result['aggregate']['avg_score']}", "",
             "> judge 为探索性外部信号，不是人工真值；不得作为唯一质量依据。"]
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result["aggregate"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
