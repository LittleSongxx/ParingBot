#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给评测运行“实际交付名单”里的候选补画像（在 backend 容器内运行）。

content_quality 需要候选方 portrait 才能评分；此前 bundle 里候选 portrait 全为 null，
实际只评到 8 个申请方画像（n=8 且全 5.0）。本脚本只对交付名单里缺画像的候选调用
portrait_service.generate_for_candidate；没有公开动态的候选会被跳过（不硬造），

不修改匹配/审核结果，只补内容质量评测所需材料。

用法：
  docker compose exec -T -e EVAL_BUNDLE_TRIALS=1 backend python - < eval/warm_candidate_portraits.py
"""
import asyncio
import json
import os

from tortoise import Tortoise

from settings import TORTOISE_ORM
from models import AgentRun, MemberPortrait, User
from service import match_service, portrait_service

BUNDLE_TRIALS = max(1, int(os.environ.get("EVAL_BUNDLE_TRIALS", "1")))
WARM_LIMIT = max(1, int(os.environ.get("EVAL_WARM_PORTRAITS", "40")))


async def main() -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    users = await User.all()
    selected = [user for user in users
                if user.username == "member02" or user.username.startswith("TEST_SCENARIO_")]
    generated = 0
    skipped = 0
    details: list[dict] = []
    for user in selected:
        runs = await AgentRun.filter(
            user_id=user.id, run_type=match_service.RUN_TYPE
        ).order_by("-id").limit(BUNDLE_TRIALS)
        for run in runs:
            if run.task_id is None or generated + skipped >= WARM_LIMIT:
                continue
            breakdown = await match_service.delivery_breakdown(run.task_id)
            for row in breakdown["delivered"]:
                if generated + skipped >= WARM_LIMIT:
                    break
                existing = await MemberPortrait.filter(member_id=row.candidate_member_id).first()
                if existing is not None:
                    continue
                result = await portrait_service.generate_for_candidate(row.candidate_member_id)
                if result is None:
                    skipped += 1
                    details.append({"applicant": user.username,
                                    "candidate": row.candidate_member_id,
                                    "status": "skipped_no_moments"})
                else:
                    generated += 1
                    details.append({"applicant": user.username,
                                    "candidate": row.candidate_member_id,
                                    "status": "generated"})
    print(json.dumps({"generated": generated, "skipped": skipped,
                      "limit": WARM_LIMIT, "details": details}, ensure_ascii=False))
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())