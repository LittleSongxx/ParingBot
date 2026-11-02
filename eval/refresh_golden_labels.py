#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 backend 容器内按当前数据库重算 golden 标签。

用途：候选池/供给变化后，golden 的 top8 会过期；live-eval 每次跑完场景后
先调本脚本，再算 consensus 和指标，避免用旧标签误判。

  docker compose exec -T backend python - < eval/refresh_golden_labels.py > eval/golden/matching_labels.json
"""
import asyncio, json
from tortoise import Tortoise
from settings import TORTOISE_ORM
from models import MemberProfile, RoommatePreference, User
from service import auditor_service, member_service


def rank(one, levels):
    try:
        return levels.index(one)
    except (ValueError, AttributeError):
        return None


async def score(applicant, preference, candidate):
    value = 0
    if candidate.store_id == applicant.store_id:
        value += 3
    elif member_service.area_name(candidate.store_id) == member_service.area_name(applicant.store_id):
        value += 1
    if candidate.schedule_type and candidate.schedule_type in str(preference.schedule_accept or "").split(","):
        value += 2
    age = member_service.calc_age(candidate.birth_date)
    if age is not None and preference.age_min <= age <= preference.age_max:
        value += 1
    if candidate.rent_budget is not None and preference.budget_min <= candidate.rent_budget <= preference.budget_max:
        value += 2
    left = rank(candidate.tidiness, member_service.TIDINESS_LEVELS)
    right = rank(preference.tidiness_min, member_service.TIDINESS_LEVELS) if preference.tidiness_min else None
    if left is not None and right is not None and left >= right:
        value += 1
    gap = member_service.lease_term_gap(applicant.lease_term, candidate.lease_term)
    if gap == 0:
        value += 2
    elif gap == 1:
        value += 1
    applicant_interests = set(str(applicant.interest_tags or "").replace("，", ",").split(",")) - {""}
    candidate_interests = set(str(candidate.interest_tags or "").replace("，", ",").split(",")) - {""}
    if applicant_interests & candidate_interests:
        value += min(2, len(applicant_interests & candidate_interests))
    return value


async def main():
    await Tortoise.init(config=TORTOISE_ORM)
    preferences = {item.member_id: item for item in await RoommatePreference.all()}
    users = await User.all()
    labels = []
    for user in users:
        if user.username != "member02" and not user.username.startswith("TEST_SCENARIO_"):
            continue
        applicant = await MemberProfile.get_or_none(user_id=user.id)
        if applicant is None:
            continue
        preference = preferences.get(applicant.id)
        if preference is None:
            continue
        candidates = await MemberProfile.filter(
            audit_status="已通过", enabled="是", gender=applicant.gender).exclude(id=applicant.id)
        ranked = []
        hard_eligible = 0
        for candidate in candidates:
            candidate_preference = preferences.get(candidate.id)
            if candidate_preference is not None and auditor_service.hard_violations(
                    applicant, candidate, candidate_preference):
                continue
            if auditor_service.hard_violations(candidate, applicant, preference):
                continue
            if auditor_service.lease_term_conflict(applicant, candidate):
                continue
            hard_eligible += 1
            ranked.append({"id": candidate.id, "nickname": candidate.nickname,
                           "score": await score(applicant, preference, candidate)})
        ranked.sort(key=lambda item: (-item["score"], item["id"]))
        labels.append({"member_id": applicant.id, "username": user.username,
                       "nickname": applicant.nickname, "hard_eligible": hard_eligible,
                       "gold_ids": [item["id"] for item in ranked[:8]],
                       "ranked": ranked[:30]})
    labels.sort(key=lambda item: (item["username"] != "member02", item["username"]))
    print(json.dumps({"version": 7, "method": "heuristic-auto-v7",
                      "note": "按当前数据库自动重算，覆盖 member02 + TEST_SCENARIO_*；仅用于回归基线，非人工真值",
                      "labels": labels}, ensure_ascii=False, indent=1))
    await Tortoise.close_connections()


asyncio.run(main())
