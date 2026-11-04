#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成对质量评审：同一申请人，系统交付候选 vs 随机池候选，哪个更适合。

比“交付组均分”更抗尺度漂移；同时做 A/B 位置交换，报告：
- delivered 胜率（tie 算 0.5）；
- position consistency（交换后是否仍选同一个人）。
代理评审（LLM），不是人工真值。

用法：
  python eval/pairwise_quality.py --blind-set analysis/.../blind_set.json \
      --key analysis/.../key.json --limit 12 --env-file .env.eval \
      --out pairwise-report.md --json pairwise-report.json
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import urllib.request
from datetime import date
from pathlib import Path

EVAL = Path(__file__).resolve().parent
REPO = EVAL.parent
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

from lib import rules, seed as seedmod  # noqa: E402

RUBRIC = """你是独立盲评员。同一申请方有 A/B 两位候选，请判断谁更适合合租。
先分别写出 A、B 各自的硬条件（同性/双向必须项/租期档差）和生活习惯（作息/吸烟/宠物/整洁）事实，
再比较；A/B 的位置不代表任何优劣，禁止因为“A 在前”就选 A；确实接近时选 tie。
只输出 JSON 数组，对象字段 pair_id, winner（A/B/tie）, reason（<=40字）。不要 markdown。
"""

PREF_FIELDS = ("age_min", "age_max", "age_required", "budget_min", "budget_max", "budget_required",
               "tidiness_min", "tidiness_required", "store_scope", "store_required",
               "schedule_accept", "schedule_required", "lease_min", "lease_required",
               "pet_accept", "pet_required")


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


def age_of(birth):
    try:
        y, m, d = map(int, str(birth)[:10].split("-"))
        today = date.today()
        return today.year - y - ((today.month, today.day) < (m, d))
    except Exception:
        return None


def person_from_member(member, preference) -> dict:
    detail = {}
    if preference is not None:
        detail = {field: getattr(preference, field, None) for field in PREF_FIELDS
                  if getattr(preference, field, None) is not None}
    return {
        "gender": member.gender, "age": age_of(member.birth_date),
        "rent_budget": member.rent_budget, "lease_term": member.lease_term,
        "store": rules.area_of(member.store_id), "store_id": member.store_id,
        "store_name": rules.store_name(member.store_id),
        "schedule_type": member.schedule_type, "tidiness": member.tidiness,
        "has_pet": member.has_pet, "smoking": member.smoking,
        "occupation": member.occupation, "self_intro": member.self_intro,
        "roommate_expectation": member.roommate_expectation,
        "interest_tags": member.interest_tags,
        "preference": {"detail": detail},
    }




def pick_control(applicant: dict, approved: list, preferences: dict, rng: random.Random,
                mode: str) -> object:
    """选对照候选：random=随机池；hard=同性别同片区但带一个软冲突的难负例。"""
    if mode == "random":
        return rng.choice(approved)
    detail = (applicant.get("preference") or {}).get("detail") or {}
    area = applicant.get("store") or rules.area_of(applicant.get("store_id") or 0)
    pet_accept = detail.get("pet_accept")
    schedule_accept = str(detail.get("schedule_accept") or "")
    budget_min = detail.get("budget_min")
    budget_max = detail.get("budget_max")
    candidates = []
    for member in approved:
        if member.gender != applicant.get("gender"):
            continue
        if rules.area_of(member.store_id) != area:
            continue
        conflicts = 0
        if applicant.get("smoking") == "不吸烟" and getattr(member, "smoking", None) == "经常":
            conflicts += 1
        if pet_accept == "不接受" and getattr(member, "has_pet", None) == "有":
            conflicts += 1
        if schedule_accept and getattr(member, "schedule_type", None) not in schedule_accept:
            conflicts += 1
        try:
            if budget_min and budget_max and not (float(budget_min) <= member.rent_budget <= float(budget_max)):
                conflicts += 1
        except (TypeError, ValueError):
            pass
        if conflicts:
            candidates.append((conflicts, member))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[rng.randrange(min(3, len(candidates)))][1]
    return rng.choice(approved)

def call(env: dict, pairs: list[dict], max_tokens: int = 8192) -> list[dict]:
    base_url = env["EVAL_JUDGE_BASE_URL"].rstrip("/")
    api_key = env["EVAL_JUDGE_API_KEY"]
    model = env["EVAL_JUDGE_MODEL"]
    prompt = RUBRIC + "\n\n材料：\n" + json.dumps(pairs, ensure_ascii=False)
    payload = {"model": model, "temperature": 0.0, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        body = json.loads(response.read().decode("utf-8"))
    message = body["choices"][0]["message"]
    content = message.get("content") or message.get("reasoning_content") or ""
    content = re.sub(r"```(?:json)?", "", content).strip("` \n")
    match = re.search(r"\[.*\]", content, re.S)
    if not match:
        raise RuntimeError("pairwise judge 响应中没有 JSON：" + content[:300])
    return json.loads(match.group(0))


def summarize(rows: list[dict]) -> dict:
    wins = 0.0
    consistent = 0
    for row in rows:
        if row["forward"] == "A":
            wins += 1
        elif row["forward"] == "tie":
            wins += 0.5
        # forward/backward 都已归一成“A=delivered / B=control”，同一身份才算一致
        if row["forward"] == row["backward"]:
            consistent += 1
    n = len(rows)
    consistency = round(consistent / n, 4) if n else 0.0
    return {"n": n,
            "delivered_win_rate": round(wins / n, 4) if n else 0.0,
            "position_consistency": consistency,
            "usable": consistency >= 0.8,
            "note": "position_consistency<0.8 时 win_rate 不可用（位置偏差）"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="成对质量评审（代理）")
    parser.add_argument("--blind-set", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env.eval"))
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--control", choices=("random", "hard"), default="random")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    env = load_env(args.env_file)
    if not all(env.get(key) for key in ("EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY", "EVAL_JUDGE_MODEL")):
        raise SystemExit("缺少 EVAL_JUDGE_* 配置")
    blind = {item["pair_id"]: item for item in json.loads(args.blind_set.read_text(encoding="utf-8"))}
    key = {item["pair_id"]: item for item in json.loads(args.key.read_text(encoding="utf-8"))}
    data = seedmod.load_seed(REPO)
    approved = seedmod.approved_candidates(data)
    random.Random(20261104).shuffle(approved)
    pair_ids = [pid for pid in sorted(key) if key[pid].get("delivered")][: args.limit]

    pairs = []
    for index, pid in enumerate(pair_ids):
        applicant = blind[pid]["applicant"]
        delivered = blind[pid]["candidate"]
        chosen = pick_control(applicant, approved, data.preferences, random.Random(20261104 + index), args.control)
        control = person_from_member(chosen, data.preferences.get(chosen.id))
        pairs.append({"pair_id": pid, "applicant": applicant, "A": delivered, "B": control,
                      "A_role": "delivered", "B_role": "control"})
    forward = []
    for start in range(0, len(pairs), 4):
        forward.extend(call(env, pairs[start:start + 4]))
    swapped = []
    for pair in pairs:
        swapped.append({"pair_id": pair["pair_id"], "applicant": pair["applicant"],
                        "A": pair["B"], "B": pair["A"], "A_role": "control", "B_role": "delivered"})
    backward = []
    for start in range(0, len(swapped), 4):
        backward.extend(call(env, swapped[start:start + 4]))
    fmap = {row["pair_id"]: row.get("winner") for row in forward}
    bmap = {row["pair_id"]: row.get("winner") for row in backward}
    rows = []
    for pair in pairs:
        pid = pair["pair_id"]
        f = fmap.get(pid, "tie")
        b = bmap.get(pid, "tie")
        # forward A=delivered；backward A=control，B=delivered
        b_as_forward = {"A": "B", "B": "A"}.get(b, "tie")
        rows.append({"pair_id": pid, "forward": f, "backward": b_as_forward,
                     "delivered_win": f == "A", "control_win": f == "B"})
    summary = summarize(rows)
    result = {"summary": summary, "rows": rows, "control": args.control, "note": "成对代理评审，不是人工真值。"}
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# 成对质量评审（交付 vs {args.control} 对照，代理）", "",
             f"- 样本：{summary['n']} 对；delivered 胜率 {summary['delivered_win_rate']:.2%}；"
             f"位置一致性 **{summary['position_consistency']:.2f}**；可用性 **{summary['usable']}**",
             "", "| pair | forward | backward(归一) | delivered win |", "|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['pair_id']} | {row['forward']} | {row['backward']} | {row['delivered_win']} |")
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
