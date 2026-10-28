"""智能匹配编排的测试：整次运行超时收尾、主管进展优先读对账结论、交付口径不变。

这里的用例都不调模型：超时用 monkeypatch 把 graph.run_graph 换成直接抛超时，
进展文本与交付口径直接用造出来的步骤记录和候选池验证，跟模型是谁无关。
"""

import asyncio
import json
from datetime import datetime
from itertools import count
from uuid import uuid4

from ai import agents, graph
from ai import tools as tool_box
from common.times import now
from models import (AgentDefinition, AgentRun, AgentStep, MatchCandidate, MatchTask,
                    MemberProfile, User)
from service import match_service

TEST_MARK = "单元测试专用"
# 造出来的账号编号挑一个远大于正式数据的区间，和别的测试文件错开
USER_ID_SEED = count(900600000)


async def _make_member(**overrides) -> MemberProfile:
    """造一位租客（连账号一起造），昵称带测试标记，跑完由清扫夹具回收。"""
    user = await User.create(
        username=f"match{uuid4().hex[:8]}{TEST_MARK}", password="x",
        name=f"匹配测试{TEST_MARK}", role="USER")
    payload = {
        "user_id": user.id, "nickname": f"匹配租客{TEST_MARK}", "gender": "男",
        "birth_date": datetime(1994, 3, 12), "rent_budget": 3900, "tidiness": "整洁",
        "occupation": "产品经理", "lease_term": "1-2年", "store_id": 1,
        "schedule_type": "早睡早起", "self_intro": "平时喜欢爬山和看展。",
        "audit_status": "已通过",
    }
    payload.update(overrides)
    return await MemberProfile.create(**payload)


async def _open_task(member: MemberProfile,
                     status: str = match_service.TASK_RUNNING) -> MatchTask:
    return await MatchTask.create(
        member_id=member.id, task_no=f"MATCH-{TEST_MARK}-{uuid4().hex[:8]}",
        deliver_count=8, status=status)


async def _open_run(member: MemberProfile, task: MatchTask,
                    status: str = match_service.RUN_RUNNING) -> AgentRun:
    run = await AgentRun.create(
        run_no=f"MATCH-{TEST_MARK}-{uuid4().hex[:8]}", task_id=task.id,
        user_id=member.user_id, run_type=match_service.RUN_TYPE,
        run_status=status, current_round=0, start_time=now())
    await MatchTask.filter(id=task.id).update(run_id=run.id)
    task.run_id = run.id
    return run


async def _make_candidate(task: MatchTask, *, audit_status: str,
                          reject_code: str | None = None) -> MatchCandidate:
    """往候选池里放一位候选，审核结论按用例需要直接给定。"""
    candidate = await MemberProfile.create(
        user_id=next(USER_ID_SEED), nickname=f"匹配候选{TEST_MARK}", gender="男",
        birth_date=datetime(1997, 8, 6), rent_budget=3250, tidiness="一般",
        occupation="会计", lease_term="6-12个月", store_id=2,
        schedule_type="早睡早起", audit_status="已通过")
    return await MatchCandidate.create(
        task_id=task.id, candidate_member_id=candidate.id, found_round=1,
        screen_score=80, audit_status=audit_status, reject_code=reject_code,
        audit_round=None if audit_status == "待审核" else 1)


async def _make_step(run: AgentRun, *, round_no: int, step_index: int,
                     step_type: str, text: str) -> AgentStep:
    return await AgentStep.create(
        run_id=run.id, round_no=round_no, step_index=step_index,
        agent_code="SCREENER", step_type=step_type, step_name=f"{step_type}步骤",
        response_result=json.dumps(text, ensure_ascii=False),
        step_status=agents.STEP_DONE, start_time=now(), end_time=now())


# ---------------------------------------------------------------- 整次运行超时


async def test_execute_task_closes_the_run_and_task_on_timeout(db, monkeypatch):
    """整次运行超时按失败收尾：运行和任务都写成失败，原因里说明超时，供页面展示。"""
    member = await _make_member()
    task = await _open_task(member)
    run = await _open_run(member, task)

    async def timing_out(task_id: int, run_id: int):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(graph, "run_graph", timing_out)
    await match_service.execute_task(task.id, run.id)

    stored_task = await MatchTask.get(id=task.id)
    assert stored_task.status == match_service.TASK_FAILED
    assert "超时" in stored_task.error_message
    stored_run = await AgentRun.get(id=run.id)
    assert stored_run.run_status == match_service.RUN_FAILED
    assert "超时" in stored_run.error_message
    assert stored_run.end_time is not None and stored_run.cost_millis is not None


# ---------------------------------------------------------------- 对账结论


async def test_history_lines_prefer_the_reconciled_step(db):
    """主管看到的「已经发生的事」优先读对账结论，模型自报的角色结论不参与。"""
    member = await _make_member()
    task = await _open_task(member)
    run = await _open_run(member, task)
    await _make_step(run, round_no=1, step_index=3,
                     step_type=agents.STEP_CONCLUSION, text="模型给出候选 15 个")
    await _make_step(run, round_no=1, step_index=999,
                     step_type=agents.STEP_RECONCILED,
                     text="第 1 轮新增候选 6 人，放宽了「年龄上限+2」")

    lines = await graph._history_lines(run.id)

    assert len(lines) == 1
    assert "第 1 轮" in lines[0]
    assert "新增候选 6 人" in lines[0]
    assert "模型给出候选 15 个" not in lines[0]


async def test_history_lines_fall_back_to_the_role_conclusion(db):
    """老运行没有对账结论时回退读角色结论，历史数据仍然看得见。"""
    member = await _make_member()
    task = await _open_task(member)
    run = await _open_run(member, task)
    await _make_step(run, round_no=2, step_index=4,
                     step_type=agents.STEP_CONCLUSION, text="模型给出候选 3 个")

    lines = await graph._history_lines(run.id)

    assert len(lines) == 1
    assert "模型给出候选 3 个" in lines[0]


# ---------------------------------------------------------------- 交付口径


async def test_deliverable_keeps_the_same_rule(db):
    """交付口径不变：审核官启用时只算通过审核的候选，停用时按候选池全部交付。"""
    member = await _make_member()
    task = await _open_task(member, status=match_service.TASK_DONE)
    passed = await _make_candidate(task, audit_status=tool_box.AUDIT_PASS)
    await _make_candidate(task, audit_status=tool_box.AUDIT_REJECT,
                          reject_code="MISMATCH_HARD")
    await _make_candidate(task, audit_status="待审核")

    rows, note = await match_service.deliverable(task.id)
    assert [row.id for row in rows] == [passed.id]
    assert note is None

    auditor = await AgentDefinition.get(agent_code=agents.AGENT_AUDITOR)
    original = auditor.enabled
    try:
        await AgentDefinition.filter(id=auditor.id).update(enabled="否")
        rows, note = await match_service.deliverable(task.id)
    finally:
        await AgentDefinition.filter(id=auditor.id).update(enabled=original)
    assert len(rows) == 3
    assert note and "停用" in note
