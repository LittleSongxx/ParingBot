#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从当前数据库导出 quality bundle（必须在 backend 容器内运行）。

用法：
  docker compose exec -T backend python - < eval/build_quality_bundle.py > /tmp/bundle.json

默认导出 member02 + 所有 TEST_SCENARIO_* 申请人的最近 N 次「匹配编排」任务
（N = EVAL_BUNDLE_TRIALS，默认 1；N > 1 时同一申请人会输出多条 run，用于 pass^k）。
输出格式与 eval/quality_checks.py 复用；meta 记录 oracle/环境指纹（含 prompt 哈希）。
"""
import asyncio, hashlib, json, os
from datetime import datetime

from tortoise import Tortoise
from settings import TORTOISE_ORM
# PromptTemplate 定义在 backend/models/config.py，models 包统一导出
from models import (AgentRun, AiModelConfig, MatchTask, MatchCandidate, MemberProfile,
                    MemberPortrait, MemberMoment, PromptTemplate, RoommatePreference, User)
from service import auditor_service, match_service, member_service, trace_service

EVAL_BUNDLE_TRIALS = int(os.environ.get("EVAL_BUNDLE_TRIALS", "1"))


def dt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


async def prompt_templates_fingerprint():
    """Prompt 模板全表指纹：按 code 排序，对每条 code + "\\n" + content 累加 sha256。"""
    digest = hashlib.sha256()
    for row in await PromptTemplate.all().order_by("code"):
        code = row.code or ""
        digest.update(code.encode("utf-8"))
        digest.update(b"\n")
        digest.update((row.content or "").encode("utf-8"))
    return digest.hexdigest()


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
    data["store_area"] = member_service.area_name(profile.store_id) if profile.store_id else None
    return data


async def run_bundle(user, run):
    """把一条 AgentRun 导成 bundle；run/task 不完整时返回 None。"""
    if run is None or run.task_id is None:
        return None
    task = await MatchTask.get_or_none(id=run.task_id)
    if task is None:
        return None
    applicant = await profile_bundle(task.member_id)
    if applicant is not None:
        applicant["username"] = user.username
    # deliverable() 是“按规则有资格交付”的全集；页面实际展示要再叠加
    # task.deliver_count 上限。bundle 的 delivered 必须与页面口径一致，
    # 否则会把“通过但被截断”的候选误标为已交付（V3_05 曾出现 delivered=10 > 8）。
    breakdown = await match_service.delivery_breakdown(task.id)
    passed = breakdown["passed"]
    delivered_rows = breakdown["delivered"]
    passed_ids = {row.id for row in passed}
    delivered_ids = {row.id for row in delivered_rows}
    truncated_ids = {row.id for row in breakdown["truncated"]}
    delivered_rank = {row.id: rank for rank, row in enumerate(delivered_rows, 1)}
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
            "passed": row.id in passed_ids,
            "truncated": row.id in truncated_ids,
            "delivered": row.id in delivered_ids,
            "delivered_rank": delivered_rank.get(row.id),
        })
        candidates.append(candidate)
    return {
        "run": {"id": run.id, "run_no": run.run_no, "status": run.run_status,
                "total_round": run.total_round, "cost_millis": run.cost_millis,
                "prompt_tokens": run.prompt_tokens or 0,
                "completion_tokens": run.completion_tokens or 0,
                "total_tokens": (run.prompt_tokens or 0) + (run.completion_tokens or 0),
                "summary": run.output_summary, "error": run.error_message,
                "start": dt(run.start_time), "end": dt(run.end_time)},
        "task": {"id": task.id, "task_no": task.task_no, "status": task.status,
                 "deliver_count": task.deliver_count, "total_round": task.total_round},
        "applicant": applicant,
        "deliverable_passed_count": len(passed),
        "delivered_to_user": len(delivered_rows),
        "truncated_count": len(truncated_ids),
        "candidates": candidates,
        "rounds": await match_service.round_rows(run.id),
        "funnel": await trace_service.funnel(task.id),
    }


async def main():
    await Tortoise.init(config=TORTOISE_ORM)
    trials = max(1, EVAL_BUNDLE_TRIALS)
    users = await User.all()
    selected = [user for user in users
                if user.username == "member02" or user.username.startswith("TEST_SCENARIO_")]
    bundles = []
    for user in selected:
        # 每个申请人取最近 N 次运行；同一 applicant 可重复，保证 pass^k 的 trial 口径
        runs = await AgentRun.filter(
            user_id=user.id, run_type=match_service.RUN_TYPE
        ).order_by("-id").limit(trials)
        for run in runs:
            bundle = await run_bundle(user, run)
            if bundle is not None:
                bundles.append(bundle)
    # 稳定排序：按 run id 升序，单 trial 时与旧输出一致（每次只取最新一条）
    bundles.sort(key=lambda item: item["run"]["id"])
    model_rows = await AiModelConfig.filter(enabled="是").order_by("model_purpose")
    model_configs = [{
        "purpose": row.model_purpose,
        "model_name": row.model_name,
        "base_url": row.base_url,
        "temperature": str(row.temperature) if row.temperature is not None else None,
        "max_tokens": row.max_tokens,
    } for row in model_rows]
    prompts_sha256 = await prompt_templates_fingerprint()
    meta = {
        "generated_at": dt(datetime.now()),
        "code_commit": os.environ.get("GIT_COMMIT", "unknown"),
        "scenario_suite": os.environ.get("EVAL_SUITE", "unknown"),
        "db_profile": os.environ.get("DB_PROFILE", "unknown"),
        "labels_hash": os.environ.get("LABELS_HASH", ""),
        "scenarios_hash": os.environ.get("SCENARIOS_HASH", ""),
        "run_timeout_seconds": os.environ.get("MATCH_TIMEOUT_SECONDS", "600"),
        "warm_portraits": False,
        "bundle_trials": trials,
        "run_ids": [item["run"]["id"] for item in bundles],
        "prompts_sha256": prompts_sha256,
        "model_configs": model_configs,
    }
    print(json.dumps({"generated_at": dt(datetime.now()), "meta": meta, "runs": bundles},
                     ensure_ascii=False, indent=1))
    await Tortoise.close_connections()


asyncio.run(main())
