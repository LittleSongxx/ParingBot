#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容质量（画像/解释文本）rubric：用异族模型给 bundle 里的 content 打分。

当前质量指标主要覆盖“交付/匹配”，内容（画像 summary、标签、解释）没有独立口径；
本脚本补这一维：faithful / coherent / readable / respectful / overall（1-5）。
注意：这是代理评审（E2.5），不是人工真值；结果只能作为内容质量的探索性信号。

用法：
  python eval/content_quality.py --bundle quality-bundle.json --limit 20 \
      --env-file .env.eval --out content-report.md --json content-report.json
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import urllib.request
from pathlib import Path

RUBRIC = """你是内容质量评审员。对每条租客画像（portrait summary + tags）按 1-5 打分：
- faithful：陈述是否与档案字段一致（年龄/性别/预算/作息/宠物/吸烟/整洁/租期），无编造；
- coherent：标签与 summary 是否自洽，不互相矛盾；
- readable：表达通顺、简洁、可读；
- respectful：无歧视/冒犯/越权判断；
- overall：综合质量。
只输出 JSON 数组，对象字段 item_id, faithful, coherent, readable, respectful, overall, reason（<=40字）。
不要 markdown、不要解释。
"""


def load_env(path: Path) -> dict:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def sample_items(bundle: dict, limit: int) -> list[dict]:
    items = []
    for run in bundle.get("runs", []):
        applicant = run.get("applicant") or {}
        portrait = applicant.get("portrait")
        if portrait:
            items.append({"item_id": f"A{len(items)+1}", "role": "applicant", "profile": applicant, "portrait": portrait})
    for run in bundle.get("runs", []):
        for candidate in run.get("candidates", []):
            if not candidate.get("delivered"):
                continue
            portrait = candidate.get("portrait")
            if portrait and len(items) < limit:
                items.append({"item_id": f"C{len(items)+1}", "role": "candidate",
                              "profile": candidate, "portrait": portrait})
    if len(items) > limit:
        items = items[:limit]
    return items


def profile_text(profile: dict) -> str:
    fields = ("gender", "birth_date", "rent_budget", "lease_term", "schedule_type", "tidiness",
              "has_pet", "smoking", "occupation", "store_id", "store_area")
    return "；".join(f"{key}={profile.get(key)}" for key in fields if profile.get(key) is not None)


def call_judge(env: dict, items: list[dict], max_tokens: int = 4096) -> list[dict]:
    base_url = env["EVAL_JUDGE_BASE_URL"].rstrip("/")
    api_key = env["EVAL_JUDGE_API_KEY"]
    model = env["EVAL_JUDGE_MODEL"]
    materials = [{"item_id": item["item_id"], "profile": profile_text(item["profile"]),
                  "portrait": item["portrait"]} for item in items]
    prompt = RUBRIC + "\n\n材料：\n" + json.dumps(materials, ensure_ascii=False)
    payload = {"model": model, "temperature": 0.0, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"].get("content") or ""
    content = re.sub(r"```(?:json)?", "", content).strip("` \n")
    match = re.search(r"\[.*\]", content, re.S)
    if not match:
        raise RuntimeError("judge 响应中没有 JSON 数组：" + content[:300])
    return json.loads(match.group(0))


def rule_warnings(items: list[dict]) -> list[dict]:
    warnings = []
    for item in items:
        profile = item["profile"]
        portrait = item["portrait"] or {}
        text = str(portrait.get("summary") or "") + " " + str(portrait.get("lifestyle_tags") or "")
        no_pet_phrase = any(phrase in text for phrase in ("不养宠物", "不养猫", "不养狗", "不养仓鼠", "无宠物"))
        if profile.get("has_pet") == "无" and not no_pet_phrase and re.search(r"养(猫|狗|仓鼠|鱼|宠物)|有宠物", text):
            warnings.append({"item_id": item["item_id"], "reason": "portrait 提到养宠但档案 has_pet=无"})
        if profile.get("smoking") == "不吸烟" and "吸烟" in text and "不吸烟" not in text:
            warnings.append({"item_id": item["item_id"], "reason": "portrait 提到吸烟但档案不吸烟"})
    return warnings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="内容质量 rubric（代理评审）")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env.eval"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    env = load_env(args.env_file)
    if not all(env.get(key) for key in ("EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY", "EVAL_JUDGE_MODEL")):
        raise SystemExit("缺少 EVAL_JUDGE_* 配置")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    items = sample_items(bundle, args.limit)
    rows = []
    for start in range(0, len(items), 4):
        rows.extend(call_judge(env, items[start:start + 4]))
    by_id = {row.get("item_id"): row for row in rows}
    dims = ("faithful", "coherent", "readable", "respectful", "overall")
    values = {dim: [float(by_id[item["item_id"]][dim]) for item in items if item["item_id"] in by_id and dim in by_id[item["item_id"]]]
              for dim in dims}
    summary = {dim: round(statistics.mean(vals), 3) if vals else None for dim, vals in values.items()}
    result = {"items": len(items), "scored": len(rows), "means": summary,
              "rule_warnings": rule_warnings(items), "rows": rows,
              "note": "内容质量代理评审（E2.5），不是人工真值。"}
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# 内容质量代理评审（不是人工真值）", "",
             f"- 样本：{len(items)} 条；评分：{len(rows)} 条"];
    lines += [f"- {dim}: {value}" for dim, value in summary.items()]
    lines += [f"- 规则 warning：{len(result['rule_warnings'])} 条"]
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"means": summary, "warnings": len(result["rule_warnings"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

