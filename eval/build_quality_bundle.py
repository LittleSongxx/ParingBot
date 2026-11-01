#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从当前数据库导出 quality bundle（必须在 backend 容器内运行）。

用法：
  docker compose exec -T backend python - < eval/build_quality_bundle.py > /tmp/bundle.json

默认导出 member02 + 所有 TEST_SCENARIO_* 申请人的最新一次「匹配编排」任务。
输出格式与 eval/quality_checks.py、eval/golden_matching.py 共用。
"""
import asyncio, json
from datetime import datetime

from tortoise import Tortoise
from settings import TORTOISE_ORM
from models import (AgentRun, MatchTask, MatchCandidate, MemberProfile, MemberPortrait,
                    MemberMoment, RoommatePreference, User)
from service import auditor_service, match_service, trace_service


def dt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


async def profile_bundle(member_id):
    profile = await MemberProfile.get_or_none(id=member_id)
    if profile is None:
        return None
    preference = await RoommatePreference.get_or_none(member_id=member_id)
    portrait = await MemberPortrait.filter(member_id=member_id).order_by("-version", "-id").first()
    moments = await MemberMoment.filter(member_id=member_id).order_by("-create_time").limit(4)
    data = {field: getattr(profile, field) for field in (
        "id", "nickname", "gender", "rent_budget", "tidiness", "occupation", "lease_term",
        "store_id", "schedule_type", "has_pet", "smoking", "self_intro",
        "roommate_expectation", "interest_tags")}
    data["birth_date"] = dt(profile.birth_date)
    data["preference"] = ({field: str(getattr(preference, field))
                           for field in preference._meta.fields_map
                           if field not in ("id", "member_id")} if preference else None)
    data["portrait"] = ({field: (dt(getattr(portrait, field)) if field.endswith("_time")
                                else getattr(portrait, field))
                         for field in portrait._meta.fields_map
                         if field not in ("id", "member_id")} if portrait else None)
    data["moments"] = [{"content": moment.content, "time": dt(moment.create_time)}
                       for moment in moments]
    return data


async def main():
    await Tortoise.init(config=TORTOISE_ORM)
    users = await User.all()
    selected = [user for user in users
                if user.username == "member02" or user.username.startswith("TEST_SCENARIO_")]
    bundles = []
    for user in selected:
        run = await AgentRun.filter(user_id=user.id, run_type=match_service.RUN_TYPE).order_by("-id").first()
        if run is None or run.task_id is None:
            continue
        task = await MatchTask.get_or_none(id=run.task_id)
        if task is None:
            continue
        applicant = await profile_bundle(task.member_id)
        if applicant is not None:
            applicant["username"] = user.username
        delivered, note = await match_service.deliverable(task.id)
        delivered_ids = {row.id for row in delivered}
        rows = await MatchCandidate.filter(task_id=task.id).order_by("id")
        applicant_profile = await MemberProfile.get(id=task.member_id)
        applicant_preference = await RoommatePreference.get_or_none(member_id=task.member_id)
        candidate_preferences = {item.member_id: item for item in await RoommatePreference.filter(
            member_id__in=[row.candidate_member_id for row in rows])}
        candidates = []
        for row in rows:
            candidate = dict(await profile_bundle(row.candidate_member_id) or {})
            candidate_profile = await MemberProfile.get_or_none(id=row.candidate_member_id)
            if candidate_profile is not None:
                candidate["evidence"] = auditor_service.match_evidence(
                    applicant_profile, candidate_profile, row,
                    applicant_preference, candidate_preferences.get(candidate_profile.id))
            candidate.update({
                "candidate_row_id": row.id, "screen_score": row.screen_score,
                "found_round": row.found_round, "relax_note": row.relax_note,
                "audit_status": row.audit_status, "reject_code": row.reject_code,
                "reject_reason": row.reject_reason, "audit_round": row.audit_round,
                "delivered": row.id in delivered_ids,
            })
            candidates.append(candidate)
        bundles.append({
            "run": {"id": run.id, "run_no": run.run_no, "status": run.run_status,
                    "total_round": run.total_round, "cost_millis": run.cost_millis,
                    "summary": run.output_summary, "error": run.error_message,
                    "start": dt(run.start_time), "end": dt(run.end_time)},
            "task": {"id": task.id, "task_no": task.task_no, "status": task.status,
                     "deliver_count": task.deliver_count, "total_round": task.total_round},
            "applicant": applicant,
            "deliverable_passed_count": len(delivered),
            "delivered_to_user": min(len(delivered), task.deliver_count),
            "candidates": candidates,
            "rounds": await match_service.round_rows(run.id),
            "funnel": await trace_service.funnel(task.id),
        })
    print(json.dumps({"generated_at": dt(datetime.now()), "runs": bundles},
                     ensure_ascii=False, indent=1))
    await Tortoise.close_connections()


asyncio.run(main())
