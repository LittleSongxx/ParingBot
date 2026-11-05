#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成对质量评审：同一申请人，系统交付候选 vs 对照池候选，哪个更适合。

审计修正（2026-11-05，A3）：
* judge 材料只允许白名单字段 —— 交付候选不再把 delivered_rank/screen_score/
  audit_status/evidence/candidate_row_id 等系统元数据带进 prompt（见 safe_person）；
* 材料里不再出现 A_role/B_role，角色映射只保留在内部（A=delivered、B=control 的
  forward/backward 归一化逻辑不进入 prompt）；
* 新增 --control near：同性别、同片区、双向硬规则可匹配、软维度尽量接近申请方的
  near-miss 对照。随机池对照太弱（含性别/门店硬冲突），hard 对照也带明显软冲突，
  都容易把“对照太弱”误读成“交付质量高”；near 是更难、更公平的负例。
* 汇总增加 Wilson 95% CI（n 只有十几对时，胜率必须带区间）。
* 交叉核对：材料在发送前统一过 assert_safe_material（fail-closed）。

比“交付组均分”更抗尺度漂移；同时做 A/B 位置交换，报告：
- delivered 胜率（tie 算 0.5）；
- position consistency（交换后是否仍选同一个人）。
代理评审（LLM），不是人工真值。

用法：
  python eval/pairwise_quality.py --blind-set analysis/.../blind_set.json \
      --key analysis/.../key.json --limit 12 --control near --env-file .env.eval \
      --out pairwise-report.md --json pairwise-report.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

EVAL = Path(__file__).resolve().parent
REPO = EVAL.parent
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

from lib import rules, seed as seedmod  # noqa: E402

# Lead 在 eval/lib/metrics.py 统一实现 Wilson CI；未就绪时用本地同签名 fallback。
try:  # pragma: no cover - 正常路径
    from lib.metrics import wilson_ci as _metrics_wilson_ci
except ImportError:  # pragma: no cover
    _metrics_wilson_ci = None

DEFAULT_SEED = 20261104

RUBRIC = """你是独立盲评员。同一申请方有 A/B 两位候选，请判断谁更适合合租。
先分别写出 A、B 各自的硬条件（同性/双向必须项/租期档差）和生活习惯（作息/吸烟/宠物/整洁）事实，
再比较；A/B 的位置不代表任何优劣，禁止因为“A 在前”就选 A；确实接近时选 tie。
只输出 JSON 数组，对象字段 pair_id, winner（A/B/tie）, reason（<=40字）。不要 markdown。
"""

# 偏好明细字段（候选方/申请方的 must 约束都在这里）
PREF_FIELDS = ("age_min", "age_max", "age_required", "budget_min", "budget_max", "budget_required",
               "tidiness_min", "tidiness_required", "store_scope", "store_required",
               "schedule_accept", "schedule_required", "lease_min", "lease_required",
               "pet_accept", "pet_required")

# judge 材料白名单：只有租客画像本身，任何系统结论/排序/审核元数据都不得进入 prompt。
SAFE_PERSON_FIELDS = ("gender", "age", "rent_budget", "lease_term", "store", "store_id",
                      "store_name", "schedule_type", "tidiness", "has_pet", "smoking",
                      "occupation", "self_intro", "roommate_expectation", "interest_tags")

# 这些 key 一旦出现在 judge 材料里就说明系统元数据泄漏（assert_safe_material 强制拦截）。
FORBIDDEN_MATERIAL_KEYS = ("delivered_rank", "screen_score", "delivered", "audit_status",
                           "reject_code", "reject_reason", "delivered_to_user", "evidence",
                           "candidate_row_id", "found_round", "relax_note")

_WILSON_SOURCE = "lib.metrics" if _metrics_wilson_ci is not None else "local-fallback"


def _local_wilson_ci(successes: float, n: int, z: float = 1.96) -> dict:
    """Wilson 95% 置信区间（lib.metrics.wilson_ci 缺失时的兜底实现）。"""
    total = int(n)
    count = float(successes)
    if total <= 0:
        return {"n": 0, "successes": 0.0, "rate": 0.0, "lo": 0.0, "hi": 0.0}
    rate = max(0.0, min(1.0, count / total))
    denominator = 1 + z * z / total
    centre = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return {"n": total, "successes": round(count, 4), "rate": round(rate, 4),
            "lo": round(max(0.0, centre - margin), 4),
            "hi": round(min(1.0, centre + margin), 4)}


def wilson_ci(successes: float, n: int) -> dict:
    """Wilson 95% CI：优先调用 lib.metrics.wilson_ci，缺失/异常时回退本地实现。"""
    if _metrics_wilson_ci is not None:
        try:
            result = _metrics_wilson_ci(successes, n)
            return {"n": int(result.get("n", n) or 0),
                    "successes": round(float(result.get("successes", successes) or 0.0), 4),
                    "rate": round(float(result.get("rate", 0.0) or 0.0), 4),
                    "lo": round(float(result.get("lo", 0.0) or 0.0), 4),
                    "hi": round(float(result.get("hi", 0.0) or 0.0), 4)}
        except Exception:  # noqa: BLE001 - fallback 兜底优先于崩溃
            pass
    return _local_wilson_ci(successes, n)


def _is_forbidden_key(key: object) -> bool:
    name = str(key)
    return name in FORBIDDEN_MATERIAL_KEYS or name.endswith("_role")


def assert_safe_material(payload) -> None:
    """深度遍历 judge 材料（dict/list），命中系统元数据或角色字段即 raise ValueError。

    这是成对评审的 hard fail-closed 闸门：材料里一旦出现 delivered_rank、
    screen_score、audit_status、A_role/B_role 等，就直接拒绝发请求。
    """
    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if _is_forbidden_key(key):
                    raise ValueError(f"judge 材料含系统元数据字段 '{key}'（路径 {path}）")
                walk(value, f"{path}.{key}")
        elif isinstance(node, (list, tuple)):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(payload, "$")


def _safe_value(value):
    """must 等自由结构的兜底清洗：只保留标量/列表/字典，命中禁 key 的字典项丢弃。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()
                if not _is_forbidden_key(key)}
    return str(value)


def _as_int(value) -> int | None:
    """把 bundle 里可能是字符串的数字统一成 int；失败返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _parse_birth(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def age_of(birth):
    try:
        if isinstance(birth, (date, datetime)):
            y, m, d = birth.year, birth.month, birth.day
        else:
            y, m, d = map(int, str(birth)[:10].split("-"))
        today = date.today()
        return today.year - y - ((today.month, today.day) < (m, d))
    except Exception:
        return None


def preference_detail(person: dict) -> dict:
    """兼容两种偏好结构：{"detail": {...}}（盲材料/控制组）与扁平 dict（bundle 原样）。"""
    pref = (person or {}).get("preference")
    if not isinstance(pref, dict):
        return {}
    detail = pref.get("detail")
    raw = detail if isinstance(detail, dict) else pref
    return {field: raw.get(field) for field in PREF_FIELDS if raw.get(field) is not None}


def _safe_preference(preference) -> dict:
    """preference 只保留 must/detail，detail 再按 PREF_FIELDS 白名单。"""
    if not isinstance(preference, dict):
        return {}
    detail_raw = preference.get("detail")
    if not isinstance(detail_raw, dict):
        detail_raw = preference
    detail = {field: detail_raw[field] for field in PREF_FIELDS
              if detail_raw.get(field) is not None}
    safe: dict = {}
    if preference.get("must") is not None:
        safe["must"] = _safe_value(preference["must"])
    if detail:
        safe["detail"] = detail
    return safe


def safe_person(person: dict) -> dict:
    """把租客/候选材料裁成 judge 可用白名单，去掉一切系统元数据。

    - 只保留 SAFE_PERSON_FIELDS；delivered_rank/screen_score/delivered/audit_status/
      evidence/... 等全部丢弃；
    - age 缺失时由 birth_date 现算，store/store_name 缺失时由 store_id 推导，
      保证交付组/对照组材料对称（输出仍严格限白名单）；
    - preference 只保留 must/detail，detail 再白名单。
    """
    person = person or {}
    safe = {field: person.get(field) for field in SAFE_PERSON_FIELDS
            if person.get(field) is not None}
    if "age" not in safe and person.get("birth_date") is not None:
        derived_age = age_of(person.get("birth_date"))
        if derived_age is not None:
            safe["age"] = derived_age
    store_id = _as_int(safe.get("store_id"))
    if store_id is not None:
        if safe.get("store") is None:
            area = rules.area_of(store_id)
            if area:
                safe["store"] = area
        if safe.get("store_name") is None:
            name = rules.store_name(store_id)
            if name:
                safe["store_name"] = name
    preference = _safe_preference(person.get("preference"))
    if preference:
        safe["preference"] = preference
    return safe


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


def member_from_person(person: dict):
    """把盲材料/档案 dict 还原成 rules 可用的 Member（near 对照做硬规则筛选用）。"""
    person = person or {}
    birth = _parse_birth(person.get("birth_date"))
    age = _as_int(person.get("age"))
    if birth is None and age is not None:
        # 只有年龄没有生日时，用“今年 1 月 1 日出生”反推一个等价生日：
        # rules.age_of 现算仍等于 age，且不改变任何“缺失不判违规”的口径。
        try:
            birth = date(date.today().year - age, 1, 1)
        except ValueError:
            birth = None
    return seedmod.Member(
        id=_as_int(person.get("id")) or 0,
        nickname=str(person.get("nickname") or ""),
        gender=str(person.get("gender") or ""),
        birth_date=birth,
        rent_budget=_as_int(person.get("rent_budget")),
        tidiness=str(person.get("tidiness") or ""),
        occupation=str(person.get("occupation") or ""),
        lease_term=str(person.get("lease_term") or ""),
        store_id=_as_int(person.get("store_id")),
        schedule_type=str(person.get("schedule_type") or ""),
        has_pet=str(person.get("has_pet") or ""),
        smoking=str(person.get("smoking") or ""),
    )


def preference_from_person(person: dict, member_id: int = 0):
    """把盲材料里的 preference 还原成 rules 可用的 Preference。"""
    detail = preference_detail(person)
    pref = seedmod.Preference(member_id=member_id)
    for field in ("age_min", "age_max", "budget_min", "budget_max"):
        value = _as_int(detail.get(field))
        if value is not None:
            setattr(pref, field, value)
    for field in ("tidiness_min", "store_scope", "lease_min", "pet_accept"):
        value = detail.get(field)
        if value is not None:
            setattr(pref, field, str(value))
    schedule = detail.get("schedule_accept")
    if isinstance(schedule, str):
        pref.schedule_accept = [item.strip() for item in re.split(r"[,，]", schedule) if item.strip()]
    elif isinstance(schedule, (list, tuple)):
        pref.schedule_accept = [str(item) for item in schedule if item]
    for field in ("age_required", "budget_required", "tidiness_required", "store_required",
                  "schedule_required", "lease_required", "pet_required"):
        value = detail.get(field)
        if value is not None:
            setattr(pref, field, str(value))
    return pref


def _area_of(person: dict) -> str | None:
    return person.get("store") or rules.area_of(_as_int(person.get("store_id")))


def _soft_match_count(applicant: dict, member) -> float:
    """申请方 vs 对照候选的软维度接近程度（near 对照用，越高越接近）。"""
    score = 0.0
    for field in ("schedule_type", "has_pet", "smoking"):
        left = applicant.get(field)
        right = getattr(member, field, None)
        if left and right and str(left) == str(right):
            score += 2
    try:
        tidiness_distance = abs(rules.TIDINESS_LEVELS.index(str(applicant.get("tidiness") or ""))
                                - rules.TIDINESS_LEVELS.index(str(member.tidiness or "")))
        score += 2 if tidiness_distance == 0 else (1 if tidiness_distance == 1 else 0)
    except ValueError:
        pass
    gap = rules.term_gap(applicant.get("lease_term") or "", member.lease_term)
    if gap == 0:
        score += 2
    elif gap == 1:
        score += 1
    try:
        budget_diff = abs(int(applicant.get("rent_budget")) - int(member.rent_budget))
        if budget_diff <= 500:
            score += 2
        elif budget_diff <= 1500:
            score += 1
    except (TypeError, ValueError):
        pass
    return score


def _near_pool(applicant: dict, approved: list, preferences: dict) -> list:
    """同性别、同片区、双向硬规则可匹配的 near 对照候选池。"""
    area = _area_of(applicant)
    gender = applicant.get("gender")
    if not area or not gender:
        return []
    applicant_member = member_from_person(applicant)
    applicant_pref = preference_from_person(applicant, applicant_member.id)
    pool = []
    for member in approved:
        if member.gender != gender:
            continue
        if rules.area_of(member.store_id) != area:
            continue
        candidate_pref = preferences.get(member.id) or seedmod.Preference(member_id=member.id)
        if not rules.is_hard_eligible(applicant_member, applicant_pref, member, candidate_pref):
            continue
        pool.append(member)
    return pool


def pick_control(applicant: dict, approved: list, preferences: dict, rng: random.Random,
                 mode: str, exclude_ids=()) -> object:
    """选对照候选。

    - random：随机池（旧口径，对照可能含硬冲突，偏弱）；
    - hard：同性别同片区但带一个软冲突的难负例；
    - near：同性别、同片区、双向硬规则可匹配，且软维度与申请方最接近的 near-miss
      （near-miss = 硬条件全过、只在作息/吸烟/宠物/整洁/预算/租期上小差异）；
      若硬可匹配池为空，退化为“同性别同片区且 >=2 个软维度接近”，再退化到同性别同片区。
    """
    applicant = applicant or {}
    approved = list(approved or [])
    excluded = {value for value in exclude_ids if value is not None}
    pool = [member for member in approved if getattr(member, "id", None) not in excluded] or approved
    if not pool:
        return None
    if mode == "random":
        return rng.choice(pool)
    if mode == "near":
        near = _near_pool(applicant, pool, preferences)
        if near:
            ordered = sorted(near, key=lambda member: (-_soft_match_count(applicant, member),
                                                       getattr(member, "id", 0) or 0))
            return rng.choice(ordered[:min(3, len(ordered))])
        area = _area_of(applicant)
        gender = applicant.get("gender")
        same_scope = [member for member in pool
                      if member.gender == gender and rules.area_of(member.store_id) == area]
        relaxed = [member for member in same_scope if _soft_match_count(applicant, member) >= 2]
        if relaxed:
            return rng.choice(relaxed)
        if same_scope:
            return rng.choice(same_scope)
        return rng.choice(pool)
    detail = preference_detail(applicant)
    area = _area_of(applicant)
    pet_accept = detail.get("pet_accept")
    schedule_accept = str(detail.get("schedule_accept") or "")
    budget_min = detail.get("budget_min")
    budget_max = detail.get("budget_max")
    candidates = []
    for member in pool:
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
    return rng.choice(pool)


def build_pairs(blind: dict, key: dict, data, limit: int, control: str = "random") -> list[dict]:
    """构造 judge 材料：只有 pair_id/applicant(safe)/A(safe)/B(safe)，不含 A_role/B_role。

    角色映射只存在于本函数内部（A=safe_person(delivered)、B=safe_person(control)）。
    applicant 同样过 safe_person：blind_set 可能直接来自 bundle 原始 applicant，
    portrait/moments 里可能带系统生成的 evidence 等元数据，不能进 prompt。
    assert_safe_material 在返回前做 fail-closed 检查。
    """
    approved = seedmod.approved_candidates(data)
    random.Random(DEFAULT_SEED).shuffle(approved)
    pair_ids = [pid for pid in sorted(key) if (key.get(pid) or {}).get("delivered")][:max(0, limit)]
    pairs = []
    for index, pid in enumerate(pair_ids):
        item = blind.get(pid) or {}
        applicant = item.get("applicant") or {}
        delivered = item.get("candidate") or {}
        exclude_ids = {_as_int(applicant.get("id")), _as_int(delivered.get("id"))} - {None}
        chosen = pick_control(applicant, approved, data.preferences,
                              random.Random(DEFAULT_SEED + index), control, exclude_ids)
        if chosen is None:
            continue
        control_person = person_from_member(chosen, data.preferences.get(chosen.id))
        pairs.append({
            "pair_id": pid,
            "applicant": safe_person(applicant),
            "A": safe_person(delivered),
            "B": safe_person(control_person),
        })
    assert_safe_material(pairs)
    return pairs


def call(env: dict, pairs: list[dict], max_tokens: int = 8192) -> list[dict]:
    assert_safe_material(pairs)
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
    win_ci = wilson_ci(wins, n)
    consistency_ci = wilson_ci(consistent, n)
    return {"n": n,
            "delivered_win_rate": round(wins / n, 4) if n else 0.0,
            "position_consistency": round(consistent / n, 4) if n else 0.0,
            "ci95": {"delivered_win_rate": win_ci, "position_consistency": consistency_ci},
            "usable": (consistent / n) >= 0.8 if n else False,
            "note": "position_consistency<0.8 时 win_rate 不可用（位置偏差）"}


def _load_blind_set(path: Path) -> tuple[dict, dict]:
    """读 blind_set；兼容 list 与 {"meta":..., "pairs":[...]} 两种形态，返回 (pairs, meta)。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("pairs"), list):
        meta = raw.get("meta") or raw.get("bundle_meta") or {}
        return {str(item["pair_id"]): item for item in raw["pairs"] if item.get("pair_id")}, meta
    if isinstance(raw, list):
        blind = {str(item["pair_id"]): item for item in raw if isinstance(item, dict) and item.get("pair_id")}
        meta = next((item.get("bundle_meta") or item.get("meta") for item in raw
                     if isinstance(item, dict) and (item.get("bundle_meta") or item.get("meta"))), {})
        return blind, meta
    raise SystemExit(f"blind-set 格式不支持：{path}")


def _load_key(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("pairs"), list):
        raw = raw["pairs"]
    if not isinstance(raw, list):
        raise SystemExit(f"key 格式不支持：{path}")
    return {str(item["pair_id"]): item for item in raw if isinstance(item, dict) and item.get("pair_id")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="成对质量评审（代理）")
    parser.add_argument("--blind-set", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env.eval"))
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--control", choices=("random", "hard", "near"), default="random")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    env = load_env(args.env_file)
    if not all(env.get(key) for key in ("EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY", "EVAL_JUDGE_MODEL")):
        raise SystemExit("缺少 EVAL_JUDGE_* 配置")
    blind, bundle_meta = _load_blind_set(args.blind_set)
    key = _load_key(args.key)
    data = seedmod.load_seed(REPO)
    pairs = build_pairs(blind, key, data, args.limit, args.control)
    if not pairs:
        raise SystemExit("没有可评审的 pair（检查 blind-set/key/limit）")
    forward = []
    for start in range(0, len(pairs), 4):
        forward.extend(call(env, pairs[start:start + 4]))
    # 位置交换：只在内部把 A/B 对调，不写任何角色标签进材料
    swapped = [{"pair_id": pair["pair_id"], "applicant": pair["applicant"],
                "A": pair["B"], "B": pair["A"]} for pair in pairs]
    assert_safe_material(swapped)
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
    result = {
        "summary": summary,
        "n": summary["n"],
        "control": args.control,
        "judge_model": env.get("EVAL_JUDGE_MODEL"),
        "judge_provider": env.get("EVAL_JUDGE_PROVIDER") or env.get("EVAL_PROVIDER"),
        "ci95": summary["ci95"],
        "ci95_method": _WILSON_SOURCE,
        "bundle_meta": bundle_meta,
        "rows": rows,
        "note": "成对代理评审，不是人工真值；对照为随机/难负例/near-miss，胜率只说明相对质量。",
    }
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    win_ci = summary["ci95"]["delivered_win_rate"]
    consistency_ci = summary["ci95"]["position_consistency"]
    lines = [f"# 成对质量评审（交付 vs {args.control} 对照，代理）", "",
             f"- 样本：{summary['n']} 对；delivered 胜率 {summary['delivered_win_rate']:.2%}"
             f"（95% CI {win_ci['lo']:.2%}–{win_ci['hi']:.2%}）；"
             f"位置一致性 **{summary['position_consistency']:.2f}**"
             f"（95% CI {consistency_ci['lo']:.2f}–{consistency_ci['hi']:.2f}）；"
             f"可用性 **{summary['usable']}**",
             f"- judge：{result['judge_model']}（{result['judge_provider'] or '未知供应商'}）；"
             f"CI 方法：Wilson（{result['ci95_method']}）",
             "", "| pair | forward | backward(归一) | delivered win |", "|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['pair_id']} | {row['forward']} | {row['backward']} | {row['delivered_win']} |")
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
