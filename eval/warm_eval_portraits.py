#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本次 live-eval 选中任务已交付候选的画像补齐（可选 workflow 步骤）。

只在 backend 容器内运行；补的是交付候选，不是全量 841 人，避免无谓 token。
"""
import asyncio
from tortoise import Tortoise
from settings import TORTOISE_ORM
from models import AgentRun, MatchTask, MatchCandidate, MemberPortrait, User
from service import match_service, portrait_service


async def main():
    await Tortoise.init(config=TORTOISE_ORM)
    users = await User.all()
    selected = [u for u in users if u.username == "member02" or u.username.startswith("TEST_SCENARIO_")]
    generated = 0
    skipped = 0
    for user in selected:
        run = await AgentRun.filter(user_id=user.id, run_type=match_service.RUN_TYPE).order_by("-id").first()
        if run is None or run.task_id is None:
            continue
        task = await MatchTask.get_or_none(id=run.task_id)
        if task is None:
            continue
        delivered, _note = await match_service.deliverable(task.id)
        for candidate_row in delivered:
            if await MemberPortrait.filter(member_id=candidate_row.candidate_member_id).count():
                continue
            portrait = await portrait_service.generate_for_candidate(candidate_row.candidate_member_id)
            if portrait is None:
                skipped += 1
            else:
                generated += 1
    print(f"warm portraits generated={generated} skipped={skipped}")
    await Tortoise.close_connections()


asyncio.run(main())
