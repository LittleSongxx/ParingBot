"""智能匹配编排的测试。

覆盖四块：整次运行超时收尾、主管进展优先读对账结论、交付名单的当前规则复核与稳定
排序、调度图的分支行为（主管失败落痕、角色被上限拦下、角色表与图的一致性、实时轮次、
同轮步骤排序）。这里的用例都不真调模型：需要模型时用 monkeypatch 换掉主管决策，
其余数据用造出来的任务、候选池和步骤记录验证。
"""

import asyncio
import json
from datetime import datetime
from itertools import count
from uuid import uuid4

import pytest

from ai import agents, graph
from ai import tools as tool_box
from common.exception_handler import CustomException
from common.times import now
from models import (AgentDefinition, AgentRun, AgentStep, MatchCandidate, MatchTask,
                    MemberProfile, RoommatePreference, ToolCallLog, User)
from service import match_service, trace_service

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
                          reject_code: str | None = None, gender: str = "男",
                          lease_term: str = "6-12个月", tidiness: str = "一般",
                          screen_score: int = 80,
                          audit_round: int | None = None) -> MatchCandidate:
    """往候选池里放一位候选，档案字段和审核结论按用例需要直接给定。"""
    candidate = await MemberProfile.create(
        user_id=next(USER_ID_SEED), nickname=f"匹配候选{TEST_MARK}", gender=gender,
        birth_date=datetime(1997, 8, 6), rent_budget=3250, tidiness=tidiness,
        occupation="会计", lease_term=lease_term, store_id=2,
        schedule_type="早睡早起", audit_status="已通过")
    if audit_round is None and audit_status != "待审核":
        audit_round = 1
    return await MatchCandidate.create(
        task_id=task.id, candidate_member_id=candidate.id, found_round=1,
        screen_score=screen_score, audit_status=audit_status,
        reject_code=reject_code, audit_round=audit_round)


async def _make_preference(member: MemberProfile, **overrides) -> RoommatePreference:
    """给申请方造一条合住偏好；默认必须项是整洁度「一般」和租期「6-12 个月」。"""
    payload = {
        "age_min": 24, "age_max": 32, "age_required": "加分",
        "budget_min": 2900, "budget_max": 3500, "budget_required": "加分",
        "tidiness_min": "一般", "tidiness_required": "必须",
        "store_scope": "不限", "store_required": "加分",
        "schedule_accept": "早睡早起,正常作息", "schedule_required": "加分",
        "lease_min": "6-12个月", "lease_required": "必须",
        "pet_accept": "无所谓", "pet_required": "加分",
    }
    payload.update(overrides)
    return await RoommatePreference.create(member_id=member.id, **payload)


def _state(task: MatchTask, run: AgentRun, round_no: int = 0) -> dict:
    """手工拼一个图状态，直接调节点用。"""
    return {"task_id": task.id, "run_id": run.id, "round_no": round_no,
            "next_agent": "", "instruction": "", "last_summary": "",
            "finish_reason": ""}


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
    """交付口径：审核官启用时只算通过审核且复核得上的；停用时排除否决，待审核可算。"""
    member = await _make_member()
    task = await _open_task(member, status=match_service.TASK_DONE)
    passed = await _make_candidate(task, audit_status=tool_box.AUDIT_PASS)
    await _make_candidate(task, audit_status=tool_box.AUDIT_REJECT,
                          reject_code="MISMATCH_HARD")
    pending = await _make_candidate(task, audit_status="待审核")

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
    # 停用审核官：明确否决的不算交付，待审核也算（这批人没有经过反向审核）
    assert [row.id for row in rows] == [passed.id, pending.id]
    assert note and "停用" in note


async def test_deliverable_filters_history_violations(db):
    """历史数据不再交付异性/复核违规者：交付名单按当前硬规则重新验一遍。"""
    member = await _make_member()
    await _make_preference(member)  # 申请方必须项：整洁度一般、租期 6-12 个月
    task = await _open_task(member, status=match_service.TASK_DONE)
    good = await _make_candidate(task, audit_status=tool_box.AUDIT_PASS)
    await _make_candidate(task, audit_status=tool_box.AUDIT_PASS, gender="女")
    # 正向违规：候选方把预算标成必须，申请方预算超出上限
    strict = await _make_candidate(task, audit_status=tool_box.AUDIT_PASS)
    await RoommatePreference.create(
        member_id=strict.candidate_member_id,
        age_min=24, age_max=40, age_required="加分",
        budget_min=2000, budget_max=3000, budget_required="必须",
        tidiness_min="一般", tidiness_required="加分",
        store_scope="不限", store_required="加分",
        schedule_accept="早睡早起,正常作息", schedule_required="加分",
        lease_min="3个月以下", lease_required="加分",
        pet_accept="无所谓", pet_required="加分")
    # 反向违规：候选方租期低于申请方标为必须的「6-12 个月」
    await _make_candidate(task, audit_status=tool_box.AUDIT_PASS,
                          lease_term="3个月以下")

    rows, note = await match_service.deliverable(task.id)

    assert [row.id for row in rows] == [good.id]
    assert note and "3 人" in note and "不可交付" in note


async def test_delivery_breakdown_records_truncated_candidates(db):
    """通过人数超过交付上限时，必须留下被截断的候选记录，不能悄悄丢掉。"""
    member = await _make_member()
    task = await _open_task(member, status=match_service.TASK_DONE)
    await MatchTask.filter(id=task.id).update(deliver_count=2)
    task.deliver_count = 2
    for score in (90, 80, 70):
        await _make_candidate(task, audit_status=tool_box.AUDIT_PASS, screen_score=score)

    detail = await match_service.delivery_breakdown(task.id)

    assert len(detail["passed"]) == 3
    assert len(detail["delivered"]) == 2
    assert len(detail["truncated"]) == 1
    assert "未展示的候选" in detail["note"]
    assert str(detail["truncated"][0].candidate_member_id) in detail["note"]


async def test_deliverable_is_sorted_and_stable(db):
    """交付名单排序稳定：初筛得分降序，同分按审核轮次降序，最后用 id 兜底。"""
    member = await _make_member()
    task = await _open_task(member, status=match_service.TASK_DONE)
    low = await _make_candidate(task, audit_status=tool_box.AUDIT_PASS,
                                screen_score=70, audit_round=2)
    high = await _make_candidate(task, audit_status=tool_box.AUDIT_PASS,
                                 screen_score=90, audit_round=1)
    newer = await _make_candidate(task, audit_status=tool_box.AUDIT_PASS,
                                  screen_score=80, audit_round=3)
    older = await _make_candidate(task, audit_status=tool_box.AUDIT_PASS,
                                  screen_score=80, audit_round=1)

    rows, _ = await match_service.deliverable(task.id)
    assert [row.id for row in rows] == [high.id, newer.id, older.id, low.id]
    # 再查一次顺序不变（页面和总结读的是同一份名单）
    again, _ = await match_service.deliverable(task.id)
    assert [row.id for row in again] == [row.id for row in rows]


# ---------------------------------------------------------------- 调度图分支


async def test_supervisor_step_and_current_round_are_updated(db, monkeypatch):
    """主管调度：step_index=0、入参只存摘要、运行中 current_round 实时推进。"""
    member = await _make_member()
    task = await _open_task(member)
    run = await _open_run(member, task)

    async def fake_ask(progress, context):
        return {"next_agent": agents.AGENT_FINISH, "instruction": "收尾", "reason": "够了"}

    monkeypatch.setattr(graph, "ask_supervisor", fake_ask)

    result = await graph.supervisor_node(_state(task, run, 0))
    assert result["round_no"] == 1 and result["next_agent"] == agents.AGENT_FINISH
    stored_run = await AgentRun.get(id=run.id)
    assert stored_run.current_round == 1
    step = await AgentStep.get(run_id=run.id, step_type=agents.STEP_SCHEDULE)
    assert step.step_index == 0
    params = json.loads(step.request_params)
    assert params["round_no"] == 1
    assert "candidate_counts" in params and "instruction" in params
    # 进展全文不再进步骤表：request_params 是摘要，不是整段【任务】…
    assert "【任务】" not in step.request_params

    # 下一轮把 current_round 继续推进
    await graph.supervisor_node(_state(task, run, 1))
    assert (await AgentRun.get(id=run.id)).current_round == 2


async def test_supervisor_failure_is_recorded_as_a_failed_step(db, monkeypatch):
    """主管两次不合规/接口失败时，先落一条失败步骤再抛错，复盘看得到断点。"""
    member = await _make_member()
    task = await _open_task(member)
    run = await _open_run(member, task)

    async def boom(progress, context):
        raise CustomException("合租管家连续两次没有给出可用的调度决定")

    monkeypatch.setattr(graph, "ask_supervisor", boom)
    with pytest.raises(CustomException):
        await graph.supervisor_node(_state(task, run, 0))

    step = await AgentStep.get(run_id=run.id, step_type=agents.STEP_CONCLUSION)
    assert step.step_status == agents.STEP_FAILED
    assert "调度失败" in step.step_name
    assert "连续两次" in step.error_message


async def test_role_blocked_writes_a_reconciled_step(db):
    """角色被上限拦下时：失败结论和对账结论都要写，对账结论带「被上限拦下」。"""
    member = await _make_member()
    task = await _open_task(member)
    run = await _open_run(member, task)
    context = tool_box.ToolContext(run_id=run.id, agent_code=agents.AGENT_PORTRAIT,
                                   task_id=task.id, member_id=member.id, round_no=3)

    result = await graph._role_blocked(context, 3, "画像师", "补画像次数已经用满")

    assert "被上限拦下" in result["last_summary"]
    steps = await AgentStep.filter(run_id=run.id).order_by("step_index", "id")
    types = [step.step_type for step in steps]
    assert agents.STEP_CONCLUSION in types and agents.STEP_RECONCILED in types
    conclusion = next(step for step in steps if step.step_type == agents.STEP_CONCLUSION)
    assert conclusion.step_status == agents.STEP_FAILED and conclusion.step_index == 2
    reconciled = next(step for step in steps if step.step_type == agents.STEP_RECONCILED)
    assert reconciled.step_status == agents.STEP_FAILED
    assert "被上限拦下" in agents.step_text(reconciled.response_result)


async def test_unknown_enabled_role_is_refused_with_readable_error(db):
    """角色表里启用了一个调度图不认识的角色时，给出可读错误而不是 KeyError。"""
    member = await _make_member()
    task = await _open_task(member)
    run = await _open_run(member, task)
    role = await AgentDefinition.create(
        agent_code=f"REVIEWER{TEST_MARK}", agent_name="未知审核员", enabled="是", sort=99)
    try:
        with pytest.raises(CustomException) as error:
            await graph.ask_supervisor(
                "进展文本", tool_box.ToolContext(
                    run_id=run.id, agent_code=agents.AGENT_SUPERVISOR,
                    task_id=task.id, member_id=member.id, round_no=1))
    finally:
        await AgentDefinition.filter(id=role.id).delete()
    assert "调度图不认识" in error.value.message
    assert "停用" in error.value.message


def test_next_node_reports_an_unknown_agent():
    """条件边拿到图外的角色编码时，抛一句能照做的错误，不是 langgraph 的 KeyError。"""
    with pytest.raises(CustomException) as error:
        graph.next_node({"next_agent": "REVIEWER"})
    assert "调度图里没有" in error.value.message


async def test_timeline_keeps_same_round_order_with_id_tiebreak(db):
    """同一轮 step_index 相同的步骤按 id 兜底排序，时间线顺序稳定。"""
    member = await _make_member()
    task = await _open_task(member)
    run = await _open_run(member, task)
    schedule = await AgentStep.create(
        run_id=run.id, round_no=1, step_index=0, agent_code=agents.AGENT_SUPERVISOR,
        step_type=agents.STEP_SCHEDULE, step_name="第 1 轮调度",
        response_result=json.dumps(
            {"next_agent": agents.AGENT_SCREENER, "instruction": "筛一轮"},
            ensure_ascii=False),
        step_status=agents.STEP_DONE, start_time=now(), end_time=now())
    first = await _make_step(run, round_no=1, step_index=2,
                             step_type=agents.STEP_TOOL, text="第一次工具返回")
    second = await _make_step(run, round_no=1, step_index=2,
                              step_type=agents.STEP_TOOL, text="第二次工具返回")

    rounds = await trace_service.timeline(run.id)

    assert len(rounds) == 1
    assert [step["id"] for step in rounds[0]["steps"]] == [
        schedule.id, first.id, second.id]
    assert rounds[0]["tool_calls"] == 2


# ---------------------------------------------------------------- 日志脱敏


async def test_logs_and_steps_are_redacted_before_writing(db):
    """工具日志与步骤记录里出现手机号/邮箱时，写库前统一打码。"""
    member = await _make_member(
        self_intro="我的手机号是 13812345678，邮箱 test@example.com，欢迎联系。")
    task = await _open_task(member)
    run = await _open_run(member, task)
    context = tool_box.ToolContext(run_id=run.id, agent_code=agents.AGENT_PORTRAIT,
                                   task_id=task.id, member_id=member.id, round_no=1)

    await tool_box.invoke("read_member_detail", {}, context)
    log = await ToolCallLog.filter(run_id=run.id).order_by("-id").first()
    assert log is not None
    assert "13812345678" not in (log.response_result or "")
    assert "test@example.com" not in (log.response_result or "")
    assert "****" in (log.response_result or "")

    await agents.write_step(
        context, 1, 2, agents.STEP_TOOL, step_name="调用工具脱敏校验",
        request_params={"phone": "13812345678"},
        response_result={"email": "test@example.com"})
    step = await AgentStep.filter(run_id=run.id, step_type=agents.STEP_TOOL).first()
    assert "13812345678" not in (step.request_params or "")
    assert "test@example.com" not in (step.response_result or "")


def test_lease_compatible_terms_are_adjacent_only():
    """计划租期相邻档可协商，相差 2 档及以上不在同一池。"""
    from service import match_service
    assert match_service.lease_compatible_terms("3个月以下") == ["3个月以下", "3-6个月"]
    assert match_service.lease_compatible_terms("6-12个月") == ["3-6个月", "6-12个月", "1-2年"]
    assert match_service.lease_compatible_terms("2年以上") == ["1-2年", "2年以上"]
    assert match_service.lease_compatible_terms(None) == []


def test_supervisor_accepts_chinese_agent_names_as_codes():
    """主管偶尔会把「审计官」这类页面称呼当编码输出，代码应归一而不是中断整次运行。"""
    from ai import graph
    assert graph._normalize_agent_code("审计官") == "AUDITOR"
    assert graph._normalize_agent_code("画像师") == "PORTRAIT"
    assert graph._normalize_agent_code("筛选官") == "SCREENER"
    assert graph._normalize_agent_code("合租管家") == "SUPERVISOR"
    assert graph._normalize_agent_code("finish") == "FINISH"
    assert graph._normalize_agent_code("AUDITOR") == "AUDITOR"
