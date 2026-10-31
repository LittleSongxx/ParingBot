"""候选审核接口、审核流程与否决校验的测试。

分四段看：第一段走接口，盯住发起审核之前的条件核对与拦截，条件不满足时提示里
要写清去哪做什么，而且要一条模型调用都不发出去；第二段用一个按剧本回话的假模型
替掉真实模型，把审核整条跑起来，盯住分批、回填、反查数据库、运行与步骤记录；
第三段盯住否决的校验边界：分类、理由、点名维度、候选不在池子里；第四段是纯函数：
一批能装几个人、代码复核怎么判、三类分类是不是固定列全。

用假模型是为了不依赖真实模型 Key：真调一次要联网、要花钱，还跑不出稳定的断言。
这一段要验的是分批和回填的规矩，跟模型是谁无关，剧本里给什么、结果就该是什么。
"""

import json
from datetime import datetime
from itertools import count
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from ai import agents
from ai import tools as tool_box
from common.exception_handler import CustomException
from common.times import now
from models import (AgentDefinition, AgentRun, AgentStep, AiModelConfig,
                    FunctionTool, MatchCandidate, MatchTask, RoommatePreference, MemberProfile,
                    PromptTemplate, ToolCallLog, User)
from service import auditor_service

TEST_MARK = "单元测试专用"
PASSWORD = "abc123456"
# 造出来的账号编号挑一个远大于正式数据的区间，和筛选那一批用例也错开
USER_ID_SEED = count(900400000)


class FakeModel:
    """按剧本回话的假模型。

    剧本是一串 AIMessage，每收到一次调用取一条；取完最后一条之后一直重复它。
    每一步模型看到的 messages 都留一份，用来断言提示词里带上了什么。
    """

    def __init__(self, script: list):
        self.script = list(script)
        self.calls = 0
        self.specs = []
        self.systems = []
        self.seen_messages = []

    def bind_tools(self, specs):
        self.specs = specs
        return self

    async def ainvoke(self, messages):
        self.seen_messages = list(messages)
        self.systems.append(agents.message_text(messages[0]))
        index = min(self.calls, len(self.script) - 1)
        self.calls += 1
        return self.script[index]


def _tool_call(name: str, args: dict | None = None, call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[
        {"name": name, "args": args or {}, "id": call_id}])


def _json_reply(payload: dict) -> AIMessage:
    return AIMessage(
        content=json.dumps(payload, ensure_ascii=False),
        usage_metadata={"input_tokens": 300, "output_tokens": 90, "total_tokens": 390})


def _reason(code: str | None) -> str:
    """一个分类对应的一条理由。判画像不够的那一条要点名缺哪个维度。"""
    if code == "PORTRAIT_INSUFFICIENT":
        return "缺作息：几点睡、几点起、周末怎么过都没有依据"
    if code == "PREFERENCE_CONFLICT":
        return "双方合住习惯冲突：候选方受不了烟味，申请方经常在屋里抽烟"
    return "候选方标为必须的预算项不满足"


def _audit_script(rows: list) -> list:
    """一批的剧本：一位一位读候选方的偏好与画像，读完把这一位的结论回填，最后按批给结论。"""
    script: list = []
    audited: list = []
    for member_id, status, code in rows:
        script.append(_tool_call("read_candidate_preference",
                                 {"candidate_member_id": member_id}, f"read{member_id}"))
        args = {"candidate_member_id": member_id, "audit_status": status}
        if status == auditor_service.AUDIT_REJECT:
            args["reject_code"] = code
            args["reject_reason"] = _reason(code)
        script.append(_tool_call("save_audit_result", args, f"save{member_id}"))
        audited.append({"candidate_member_id": member_id, "audit_status": status,
                        "reject_code": code})
    script.append(_json_reply({"audited": audited,
                               "summary": f"这一批审了 {len(rows)} 位"}))
    return script


def _use_fake_model(monkeypatch, script: list) -> FakeModel:
    """把模型调用换成假模型，执行器的其它环节全部照真跑。"""
    fake = FakeModel(script)

    async def fake_load(purpose):
        return SimpleNamespace(model_name=f"假模型{TEST_MARK}", api_key="test-key",
                               base_url=None, temperature=None, max_tokens=None,
                               model_purpose=purpose)

    monkeypatch.setattr(agents.model_factory, "load_for_purpose", fake_load)
    monkeypatch.setattr(agents.model_factory, "build_chat_model",
                        lambda config, temperature=0.0: fake)
    return fake


def _member_payload(**overrides) -> dict:
    payload = {
        "nickname": f"审核申请{TEST_MARK}", "gender": "男",
        "birth_date": datetime(1994, 3, 12), "rent_budget": 3900, "tidiness": "整洁",
        "occupation": "产品经理", "lease_term": "1-2年", "store_id": 1,
        "schedule_type": "早睡早起", "smoking": "不吸烟",
        "self_intro": "平时喜欢爬山和看展，周末常在家做饭。", "audit_status": "已通过",
    }
    payload.update(overrides)
    return payload


async def _make_applicant(**overrides) -> MemberProfile:
    """造一位资料完整、也填了合住偏好的申请方，连账号一起造。"""
    user = await User.create(
        username=f"audit{uuid4().hex[:8]}{TEST_MARK}", password="x",
        name=f"审核申请{TEST_MARK}", role="USER")
    member = await MemberProfile.create(user_id=user.id, **_member_payload(**overrides))
    await RoommatePreference.create(
        member_id=member.id,
        age_min=24, age_max=32, age_required="加分",
        budget_min=2900, budget_max=3500, budget_required="加分",
        tidiness_min="一般", tidiness_required="必须",
        store_scope="同片区", store_required="加分",
        schedule_accept="早睡早起,正常作息", schedule_required="加分",
        lease_min="6-12个月", lease_required="必须",
        pet_accept="无所谓", pet_required="加分")
    return member


async def _make_candidate(**overrides) -> MemberProfile:
    """造一位资料已通过审核的候选租客，昵称带测试标记，跑完由清扫夹具回收。"""
    payload = {
        "user_id": next(USER_ID_SEED), "nickname": f"审核候选{TEST_MARK}", "gender": "男",
        "birth_date": datetime(1997, 8, 6), "rent_budget": 3250, "tidiness": "一般",
        "occupation": "会计", "lease_term": "6-12个月", "store_id": 5,
        "schedule_type": "早睡早起", "smoking": "不吸烟", "audit_status": "已通过",
    }
    payload.update(overrides)
    return await MemberProfile.create(**payload)


async def _make_preference(member: MemberProfile, **overrides) -> RoommatePreference:
    """给候选方造一条合住偏好。默认七项都填、标为必须的只有整洁度和租期。"""
    payload = {
        "age_min": 26, "age_max": 36, "age_required": "加分",
        "budget_min": 3500, "budget_max": 4500, "budget_required": "加分",
        "tidiness_min": "一般", "tidiness_required": "必须",
        "store_scope": "不限", "store_required": "加分",
        "schedule_accept": "早睡早起,正常作息", "schedule_required": "加分",
        "lease_min": "6-12个月", "lease_required": "必须",
        "pet_accept": "无所谓", "pet_required": "加分",
    }
    payload.update(overrides)
    return await RoommatePreference.create(member_id=member.id, **payload)


async def _open_task(member: MemberProfile) -> MatchTask:
    return await MatchTask.create(
        member_id=member.id, task_no=f"SCREEN-{TEST_MARK}-{uuid4().hex[:8]}",
        deliver_count=8, status="已完成")


async def _open_run(task: MatchTask) -> AgentRun:
    return await AgentRun.create(
        run_no=f"AUDIT-{TEST_MARK}-{uuid4().hex[:8]}", task_id=task.id,
        run_type=auditor_service.RUN_TYPE, run_status=auditor_service.RUN_RUNNING,
        current_round=1, start_time=now())


async def _put(task: MatchTask, candidate: MemberProfile, **overrides) -> MatchCandidate:
    payload = {"task_id": task.id, "candidate_member_id": candidate.id, "found_round": 1,
               "screen_score": 80, "audit_status": auditor_service.AUDIT_WAIT}
    payload.update(overrides)
    return await MatchCandidate.create(**payload)


def _register(client, username: str) -> dict:
    return client.post("/register", json={
        "username": username, "password": PASSWORD, "confirmPassword": PASSWORD}).json()


def _login(client, username: str) -> dict:
    body = client.post("/login", json={"username": username, "password": PASSWORD}).json()
    assert body["code"] == "200", body["msg"]
    return {"token": body["data"]["token"]}


def _profile_payload(**overrides) -> dict:
    payload = {
        "nickname": f"审核租客{TEST_MARK}", "gender": "男", "birth_date": "1994-03-12",
        "rent_budget": 3900, "tidiness": "整洁", "occupation": "产品经理",
        "lease_term": "1-2年", "store_id": 1, "schedule_type": "早睡早起",
        "smoking": "不吸烟", "self_intro": "平时喜欢爬山和看展。",
    }
    payload.update(overrides)
    return payload


def _preference_payload(**overrides) -> dict:
    payload = {
        "age_min": 24, "age_max": 32, "age_required": "加分",
        "budget_min": 3000, "budget_max": 3750, "budget_required": "加分",
        "tidiness_min": "一般", "tidiness_required": "必须",
        "store_scope": "同片区", "store_required": "加分",
        "schedule_accept": ["早睡早起"], "schedule_required": "加分",
        "lease_min": "6-12个月", "lease_required": "必须",
        "pet_accept": "接受", "pet_required": "加分",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- 接口层


def test_my_audit_points_to_profile_first(client):
    """还没填资料时，页面第一句要指到租客档案页，候选和审核记录都是空的。"""
    username = f"audit1{TEST_MARK}"
    assert _register(client, username)["code"] == "200"
    headers = _login(client, username)
    data = client.get("/auditor/my", headers=headers).json()["data"]
    assert data["has_profile"] is False
    assert data["task"] is None and data["run"] is None
    assert data["candidates"] == [] and data["rejected"] == []
    blocker = data["readiness"]["blocker"]
    assert blocker["key"] == "profile"
    assert blocker["action_path"] == "/front/memberProfile"
    assert data["readiness"]["can_run"] is False


def test_my_audit_asks_for_match_after_profile(client):
    """资料填好但还没运行智能匹配时，第二项卡住并指向统一执行入口。"""
    username = f"audit2{TEST_MARK}"
    _register(client, username)
    headers = _login(client, username)
    saved = client.post("/member/saveMy", json=_profile_payload(), headers=headers).json()
    assert saved["code"] == "200", saved["msg"]
    data = client.get("/auditor/my", headers=headers).json()["data"]
    assert data["has_profile"] is True
    checks = data["readiness"]["checks"]
    assert [item["key"] for item in checks] == ["profile", "candidate"]
    assert checks[0]["ok"] is True
    assert data["readiness"]["blocker"]["action_path"] == "/front/myMatch"
    assert "候选结果" in data["readiness"]["blocker"]["message"]


def test_generate_stops_before_calling_the_model(client):
    """审核没有独立执行入口，只能由智能匹配里的主管调度。"""
    assert client.post("/auditor/generate").status_code == 404


def test_my_audit_is_closed_to_admin(client, admin_headers):
    """管理员账号不参与合租匹配，进这一页要提示换成租客账号。"""
    body = client.get("/auditor/my", headers=admin_headers).json()
    # 权限不够的返回码是 403，前端按这个码提示换成租客账号
    assert body["code"] == "403"
    assert "租客账号" in body["msg"]


def test_select_candidate_of_missing_row(client, user_headers):
    """查一个不存在的候选时，提示要能指回页面刷新。"""
    body = client.get("/auditor/selectCandidate",
                      params={"candidate_id": 999999999},
                      headers=user_headers).json()
    assert body["code"] == "500"
    assert "刷新" in body["msg"]


# ---------------------------------------------------------------- 审核流程


async def test_one_batch_audits_the_whole_pool(db, monkeypatch):
    """候选不多时一批审完：通过与否决都回填到候选池，步骤与工具日志逐条留痕。"""
    member = await _make_applicant()
    first, second = await _make_candidate(), await _make_candidate()
    await _make_preference(first)
    await _make_preference(second)
    task = await _open_task(member)
    await _put(task, first)
    await _put(task, second)
    run = await _open_run(task)
    _use_fake_model(monkeypatch, _audit_script([
        (first.id, auditor_service.AUDIT_PASS, None),
        (second.id, auditor_service.AUDIT_REJECT, "PREFERENCE_CONFLICT")]))

    result = await auditor_service.build_audit(member.id, task.id, run.id)

    assert result.gate is None
    assert len(result.batches) == 1
    assert result.batches[0].written == 2
    assert result.passed == 1 and result.rejected == 1
    assert result.pending == 0
    assert "一共审了 1 批：通过 1 人，否决 1 人" in result.conclusion
    # 反查数据库：页面上的数字全部以库里的为准
    rows = {row.candidate_member_id: row for row in await MatchCandidate.filter(task_id=task.id)}
    assert rows[first.id].audit_status == auditor_service.AUDIT_PASS
    assert rows[first.id].reject_code is None and rows[first.id].audit_round == 1
    assert rows[second.id].audit_status == auditor_service.AUDIT_REJECT
    assert rows[second.id].reject_code == "PREFERENCE_CONFLICT"
    assert rows[second.id].reject_reason == _reason("PREFERENCE_CONFLICT")

    steps = await AgentStep.filter(run_id=run.id).order_by("step_index")
    assert [step.step_type for step in steps] == [
        "工具调用", "工具调用", "工具调用", "工具调用", "角色结论"]
    assert [step.tool_code for step in steps[:4]] == [
        "read_candidate_preference", "save_audit_result",
        "read_candidate_preference", "save_audit_result"]
    assert steps[0].agent_code == "AUDITOR" and steps[0].round_no == 1

    logs = await ToolCallLog.filter(run_id=run.id).order_by("id")
    assert [log.tool_code for log in logs] == [
        "read_candidate_preference", "save_audit_result",
        "read_candidate_preference", "save_audit_result"]
    assert all(log.success == "是" for log in logs)
    assert logs[3].row_count == 1


async def test_pool_is_split_into_batches(db, monkeypatch):
    """候选比一批能装的人数多时接着开下一批：每批各写各的结论，审的批次记在行上。"""
    member = await _make_applicant()
    candidates = []
    for _ in range(5):
        one = await _make_candidate()
        await _make_preference(one)
        candidates.append(one)
    task = await _open_task(member)
    for one in candidates:
        await _put(task, one)
    run = await _open_run(task)
    agent = await AgentDefinition.get(agent_code="AUDITOR")
    original = agent.max_tool_call
    # 上限 8 时一批只能装两位：(8 - 4) / 2 = 2
    rows = [(one.id, auditor_service.AUDIT_PASS, None) for one in candidates]
    _use_fake_model(monkeypatch, _audit_script(rows[:2]) + _audit_script(rows[2:4])
                    + _audit_script(rows[4:]))
    try:
        await AgentDefinition.filter(id=agent.id).update(max_tool_call=8)
        result = await auditor_service.build_audit(member.id, task.id, run.id)
    finally:
        await AgentDefinition.filter(id=agent.id).update(max_tool_call=original)

    assert result.gate is None
    assert [item.written for item in result.batches] == [2, 2, 1]
    assert result.passed == 5 and result.pending == 0
    assert "一共审了 3 批" in result.conclusion
    rounds = {row.candidate_member_id: row.audit_round
              for row in await MatchCandidate.filter(task_id=task.id)}
    assert [rounds[one.id] for one in candidates] == [1, 1, 2, 2, 3]


async def test_a_batch_that_wrote_nothing_stops_the_loop(db, monkeypatch):
    """模型审的是名单外的候选时这一批一条也没回填：停下来，并把对不上的地方写进结论。"""
    member = await _make_applicant()
    first = await _make_candidate()
    await _make_preference(first)
    task = await _open_task(member)
    await _put(task, first)
    run = await _open_run(task)
    _use_fake_model(monkeypatch, [
        _tool_call("read_candidate_preference", {"candidate_member_id": first.id}, "read1"),
        # 这个编号不在候选池里，工具会拒绝，这一批等于什么也没写
        _tool_call("save_audit_result",
                   {"candidate_member_id": 999999999,
                    "audit_status": auditor_service.AUDIT_PASS}, "save1"),
        _json_reply({"audited": [{"candidate_member_id": 999999999,
                                  "audit_status": auditor_service.AUDIT_PASS}],
                     "summary": "审了一位"}),
    ])

    result = await auditor_service.build_audit(member.id, task.id, run.id)

    assert result.gate is None
    assert len(result.batches) == 1 and result.batches[0].written == 0
    assert result.pending == 1 and result.passed == 0
    assert "回填了 0 位" in result.batches[0].mismatch
    assert "模型报的和库里的对不上的地方" in result.conclusion
    row = await MatchCandidate.get(task_id=task.id, candidate_member_id=first.id)
    assert row.audit_status == auditor_service.AUDIT_WAIT


async def test_candidates_with_a_conclusion_are_not_audited_again(db, monkeypatch):
    """已经有结论的候选不再进批：只审还挂着待审核的那几位。"""
    member = await _make_applicant()
    done = await _make_candidate()
    todo = await _make_candidate()
    await _make_preference(done)
    await _make_preference(todo)
    task = await _open_task(member)
    await _put(task, done, audit_status=auditor_service.AUDIT_PASS, audit_round=1)
    await _put(task, todo)
    run = await _open_run(task)
    fake = _use_fake_model(monkeypatch, _audit_script([
        (todo.id, auditor_service.AUDIT_REJECT, "MISMATCH_HARD")]))

    result = await auditor_service.build_audit(member.id, task.id, run.id)

    assert result.batches[0].written == 1 and result.passed == 1 and result.rejected == 1
    # 三位动作对应一位候选：读一次、回填一次、给结论一次，后面没有再开一批
    assert fake.calls == 3
    assert await MatchCandidate.filter(
        task_id=task.id, audit_status=auditor_service.AUDIT_WAIT).count() == 0
    row = await MatchCandidate.get(task_id=task.id, candidate_member_id=done.id)
    assert row.audit_round == 1 and row.reject_code is None


async def test_code_recheck_turns_a_passed_candidate_into_a_reject(db, monkeypatch):
    """模型判通过的候选，代码按候选方的必须项复核对不上时当场改判否决，不留在通过里。"""
    member = await _make_applicant()
    # 候选方把预算标成必须，且要求 3000-3500；申请方 3900，这一项代码验不过
    candidate = await _make_candidate()
    await _make_preference(candidate, budget_min=3000, budget_max=3500,
                           budget_required="必须")
    task = await _open_task(member)
    await _put(task, candidate)
    run = await _open_run(task)
    _use_fake_model(monkeypatch, _audit_script([
        (candidate.id, auditor_service.AUDIT_PASS, None)]))

    result = await auditor_service.build_audit(member.id, task.id, run.id)

    assert result.passed == 0 and result.rejected == 1
    assert "代码复核改判 1 人" in result.batches[0].conclusion
    assert "预算" in result.batches[0].conclusion
    row = await MatchCandidate.get(task_id=task.id, candidate_member_id=candidate.id)
    assert row.audit_status == auditor_service.AUDIT_REJECT
    assert row.reject_code == "MISMATCH_HARD"
    assert "预算" in row.reject_reason
    assert "模型报的和库里的对不上的地方" in result.conclusion


async def test_code_recheck_turns_an_opposite_gender_pass_into_a_reject(db, monkeypatch):
    """合租只找同性：历史数据里已经判通过的异性候选，代码复核时改判否决。"""
    member = await _make_applicant()  # 男
    legacy = await _make_candidate(gender="女")
    await _make_preference(legacy)
    fresh = await _make_candidate()
    await _make_preference(fresh)
    task = await _open_task(member)
    # 这一条是性别复核补上之前留下的「已通过」，和这一批同批再审一次
    legacy_row = await _put(task, legacy, audit_status=auditor_service.AUDIT_PASS,
                            audit_round=1)
    fresh_row = await _put(task, fresh)
    run = await _open_run(task)
    _use_fake_model(monkeypatch, _audit_script([
        (fresh.id, auditor_service.AUDIT_PASS, None)]))

    result = await auditor_service.audit_batch(
        member, task, run.id, batch_no=1, pending=1,
        rows=[(legacy_row, legacy), (fresh_row, fresh)], round_no=2)

    assert result.passed == 1 and result.rejected == 1
    stored = await MatchCandidate.get(id=legacy_row.id)
    assert stored.audit_status == auditor_service.AUDIT_REJECT
    assert stored.reject_code == "MISMATCH_HARD"
    assert "合租只找同性" in stored.reject_reason
    assert stored.audit_round == 2
    assert "代码复核改判 1 人" in result.conclusion


async def test_code_recheck_turns_a_reverse_must_violation_into_a_reject(db, monkeypatch):
    """反向复核：候选方不满足申请方标为必须的条件时，同样改判否决。"""
    member = await _make_applicant()  # 申请方偏好：整洁度一般、租期 6-12 个月标为必须
    # 候选方租期只有 3 个月以下，低于申请方的必须项
    candidate = await _make_candidate(lease_term="3个月以下")
    await _make_preference(candidate)
    task = await _open_task(member)
    await _put(task, candidate)
    run = await _open_run(task)
    _use_fake_model(monkeypatch, _audit_script([
        (candidate.id, auditor_service.AUDIT_PASS, None)]))

    result = await auditor_service.build_audit(member.id, task.id, run.id)

    assert result.passed == 0 and result.rejected == 1
    row = await MatchCandidate.get(task_id=task.id, candidate_member_id=candidate.id)
    assert row.audit_status == auditor_service.AUDIT_REJECT
    assert row.reject_code == "MISMATCH_HARD"
    assert "租期" in row.reject_reason
    assert "候选方不满足申请方" in row.reject_reason
    assert "代码复核改判 1 人" in result.batches[0].conclusion


async def test_recheck_rows_checks_both_directions(db):
    """交付前复核与审核改判共用一份判断：双向必须项都验，返回结构化方向。"""
    applicant = await _make_applicant()
    reverse = await _make_candidate(lease_term="3个月以下")
    await _make_preference(reverse)
    ok = await _make_candidate()
    await _make_preference(ok)
    task = await _open_task(applicant)
    reverse_row = await _put(task, reverse, audit_status=auditor_service.AUDIT_PASS)
    ok_row = await _put(task, ok, audit_status=auditor_service.AUDIT_PASS)

    records = await auditor_service.recheck_rows(applicant, [reverse_row, ok_row])

    assert [item.row.id for item in records] == [reverse_row.id]
    assert records[0].reverse_violations == ["租期"]
    assert records[0].violations == []
    assert records[0].gender_conflict is False
    assert "候选方不满足申请方" in records[0].rejected_because()


async def test_lease_term_gap_is_a_bidirectional_hard_conflict(db):
    """计划租期相差两档及以上判硬冲突；相邻档位仍可协商。"""
    applicant = await _make_applicant()  # 1-2年
    far = await _make_candidate(lease_term="3个月以下")
    adjacent = await _make_candidate(lease_term="6-12个月")
    task = await _open_task(applicant)
    far_row = await _put(task, far, audit_status=auditor_service.AUDIT_PASS)
    adjacent_row = await _put(task, adjacent, audit_status=auditor_service.AUDIT_PASS)

    records = await auditor_service.recheck_rows(applicant, [far_row, adjacent_row])

    assert [item.row.id for item in records] == [far_row.id]
    assert records[0].lease_conflict is True
    assert "计划租期" in records[0].rejected_because()


async def test_disabled_role_is_refused_before_anything_is_written(db, monkeypatch):
    """审核官被停用时直接拦住，提示指回子 Agent 定义，候选池一条都不动。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    await _make_preference(candidate)
    task = await _open_task(member)
    await _put(task, candidate)
    run = await _open_run(task)
    agent = await AgentDefinition.get(agent_code="AUDITOR")
    _use_fake_model(monkeypatch, _audit_script([
        (candidate.id, auditor_service.AUDIT_PASS, None)]))
    try:
        await AgentDefinition.filter(id=agent.id).update(enabled="否")
        with pytest.raises(CustomException) as error:
            await auditor_service.build_audit(member.id, task.id, run.id)
    finally:
        await AgentDefinition.filter(id=agent.id).update(enabled="是")
    assert "停用" in error.value.message
    assert "子 Agent 定义" in error.value.message
    row = await MatchCandidate.get(task_id=task.id, candidate_member_id=candidate.id)
    assert row.audit_status == auditor_service.AUDIT_WAIT


async def test_tool_call_gate_interrupts_the_batch(db, monkeypatch):
    """工具调用次数用满时中断这一批，把触发了哪道闸作为结论返回，不抛异常。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    await _make_preference(candidate)
    task = await _open_task(member)
    await _put(task, candidate)
    run = await _open_run(task)
    agent = await AgentDefinition.get(agent_code="AUDITOR")
    original = agent.max_tool_call
    try:
        await AgentDefinition.filter(id=agent.id).update(max_tool_call=2)
        _use_fake_model(monkeypatch, [
            _tool_call("read_candidate_preference",
                       {"candidate_member_id": candidate.id}, f"read{index}")
            for index in range(6)])
        result = await auditor_service.build_audit(member.id, task.id, run.id)
    finally:
        await AgentDefinition.filter(id=agent.id).update(max_tool_call=original)
    assert result.gate == agents.GATE_TOOL_CALL
    assert "上限" in result.conclusion
    row = await MatchCandidate.get(task_id=task.id, candidate_member_id=candidate.id)
    assert row.audit_status == auditor_service.AUDIT_WAIT


async def test_readiness_reports_missing_model_config(db):
    """七项检查里最后一项是模型配置：它没配好时提示指向 AI模型配置。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    task = await _open_task(member)
    await _put(task, candidate)
    config = await AiModelConfig.filter(
        model_purpose="审核", enabled="是").order_by("-id").first()
    assert config is not None, "初始化数据里应该有一条审核用途的模型配置"
    try:
        await AiModelConfig.filter(id=config.id).update(enabled="否")
        state = await auditor_service.readiness(member)
    finally:
        await AiModelConfig.filter(id=config.id).update(enabled="是")
    assert state["can_run"] is False
    assert state["blocker"]["key"] == "model"
    assert "AI模型配置" in state["blocker"]["message"]
    assert [item["key"] for item in state["checks"]] == [
        "profile", "candidate", "pending", "agent", "prompt", "tool", "model"]
    assert all(item["ok"] for item in state["checks"][:-1])


async def test_readiness_marks_complete_when_everyone_is_audited(db):
    """候选池里的人都有结论时标记完成，不再错误引导用户原样重新筛选。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    task = await _open_task(member)
    await _put(task, candidate, audit_status=auditor_service.AUDIT_PASS, audit_round=1)
    state = await auditor_service.readiness(member)
    assert state["can_run"] is False
    assert state["blocker"]["key"] == "complete"
    assert state["blocker"]["ok"] is True
    assert state["blocker"]["action_path"] is None


async def test_my_page_recognizes_audit_done_inside_match_run(db):
    """MATCH-* 的审核属于匹配编排，页面不能因为没有 AUDIT-* 运行就说没审核过。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    task = await MatchTask.create(
        member_id=member.id, task_no=f"MATCH-{TEST_MARK}-{uuid4().hex[:8]}",
        deliver_count=8, status="已完成")
    await _put(task, candidate, audit_status=auditor_service.AUDIT_PASS, audit_round=3)
    run = await AgentRun.create(
        run_no=f"MATCH-{TEST_MARK}-{uuid4().hex[:8]}", task_id=task.id,
        user_id=member.user_id, run_type=auditor_service.MATCH_RUN_TYPE,
        run_status="已完成", total_round=4, output_summary="智能匹配完成")

    page = await auditor_service.my_page(await User.get(id=member.user_id))

    assert page["counts"] == {"total": 1, "passed": 1, "rejected": 0, "pending": 0}
    assert page["readiness"]["blocker"]["key"] == "complete"
    assert page["run"]["id"] == run.id
    assert page["run"]["run_type"] == auditor_service.MATCH_RUN_TYPE


async def test_generate_fills_the_pool_and_records_a_run(db, monkeypatch):
    """租客点一次反向审核走完整条路：开运行、分批审、收尾，页面读到的都是库里的数。"""
    member = await _make_applicant()
    first, second = await _make_candidate(), await _make_candidate()
    await _make_preference(first)
    await _make_preference(second)
    task = await _open_task(member)
    await _put(task, first)
    await _put(task, second)
    user = await User.get(id=member.user_id)
    config = await AiModelConfig.filter(
        model_purpose="审核", enabled="是").order_by("-id").first()
    # 用的是开发库里那条正式配置，跑完要原样还回去：密钥那一列尤其不能写成空，
    # 那等于把管理员填好的密钥冲掉，后面再跑这条链路就连不上模型了
    key_original = config.api_key
    _use_fake_model(monkeypatch, _audit_script([
        (first.id, auditor_service.AUDIT_PASS, None),
        (second.id, auditor_service.AUDIT_REJECT, "PORTRAIT_INSUFFICIENT")]))
    try:
        await AiModelConfig.filter(id=config.id).update(api_key="test-key")
        data = await auditor_service.generate(user)
    finally:
        await AiModelConfig.filter(id=config.id).update(api_key=key_original)

    assert data["batches"] == 1 and data["passed"] == 1 and data["rejected"] == 1
    assert data["pending"] == 0
    run = await AgentRun.get(run_no=data["run_no"])
    assert run.run_type == auditor_service.RUN_TYPE and run.task_id == task.id
    assert run.run_status == "已完成" and run.total_round == 1
    assert "补上对应的维度之后这一批可以再审一次" in run.output_summary
    assert run.cost_millis is not None and run.end_time is not None

    page = await auditor_service.my_page(user)
    assert page["counts"] == {"total": 2, "passed": 1, "rejected": 1, "pending": 0}
    assert page["run"]["run_no"] == run.run_no
    assert [item["count"] for item in page["distribution"]] == [0, 0, 1]
    assert len(page["rejected"]) == 1
    assert page["rejected"][0]["member_id"] == second.id


# ---------------------------------------------------------------- 详情


async def test_candidate_detail_lists_the_must_need(db):
    """弹窗里的详情：他在意的必须项、代码复核结论、全部条件三块都要有。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    await _make_preference(candidate, budget_min=3000, budget_max=3500,
                           budget_required="必须")
    task = await _open_task(member)
    row = await _put(task, candidate, audit_status=auditor_service.AUDIT_PASS,
                     audit_round=1)
    user = await User.get(id=member.user_id)

    data = await auditor_service.candidate_detail(user, row.id)

    assert data["audit_status"] == auditor_service.AUDIT_PASS
    assert data["audit_round"] == 1
    names = [item["name"] for item in data["must_need"]]
    assert "预算" in names and "整洁度" in names
    height = [item for item in data["must_need"] if item["name"] == "预算"][0]
    assert height["need"] == "3000-3500 元"
    assert data["recheck"]["violations"] == ["预算"]
    assert "预算" in data["recheck"]["note"]
    # 全部条件那一块带必须与加分的标注，看的人分得清哪些能让步
    assert "（必须）" in data["preference_text"]
    assert data["self_intro"] == candidate.self_intro


async def test_detail_of_another_pool_is_refused(db):
    """拿别人的候选编号来查看会被挡住：只能看自己候选池里的人。"""
    owner = await _make_applicant()
    other = await _make_applicant()
    candidate = await _make_candidate()
    task = await _open_task(owner)
    row = await _put(task, candidate)
    viewer = await User.get(id=other.user_id)
    with pytest.raises(CustomException) as error:
        await auditor_service.candidate_detail(viewer, row.id)
    assert "不在你的候选池里" in error.value.message


# ---------------------------------------------------------------- 否决的校验边界


async def _context(member: MemberProfile, task: MatchTask,
                   round_no: int = 1) -> tool_box.ToolContext:
    return tool_box.ToolContext(agent_code=auditor_service.AGENT_CODE, task_id=task.id,
                                member_id=member.id, round_no=round_no)


async def test_reject_without_code_is_refused(db):
    """否决必须分类：不给分类的调用被拒，候选池里那条还是待审核。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    task = await _open_task(member)
    row = await _put(task, candidate)
    with pytest.raises(CustomException) as error:
        await tool_box.save_audit_result(
            await _context(member, task), candidate.id,
            auditor_service.AUDIT_REJECT, None, "不合适")
    assert "否决原因请从这几项里选" in error.value.message
    assert (await MatchCandidate.get(id=row.id)).audit_status == auditor_service.AUDIT_WAIT


async def test_reject_with_unknown_code_is_refused(db):
    """分类只认三种，自己造一个分类名会被拒。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    task = await _open_task(member)
    row = await _put(task, candidate)
    with pytest.raises(CustomException) as error:
        await tool_box.save_audit_result(
            await _context(member, task), candidate.id,
            auditor_service.AUDIT_REJECT, "NOT_MATCH", "不合适")
    assert "MISMATCH_HARD" in error.value.message
    assert (await MatchCandidate.get(id=row.id)).audit_status == auditor_service.AUDIT_WAIT


async def test_portrait_insufficient_without_dimension_is_refused(db):
    """判画像不够时理由要点名缺哪个维度，没点名的调用被拒。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    task = await _open_task(member)
    row = await _put(task, candidate)
    context = await _context(member, task)
    with pytest.raises(CustomException) as error:
        await tool_box.save_audit_result(
            context, candidate.id, auditor_service.AUDIT_REJECT,
            "PORTRAIT_INSUFFICIENT", "信息不够，判断不了")
    assert "点名缺的是哪个维度" in error.value.message
    # 点名了维度就写得进去，这个维度会被拿去安排补画像
    saved = await tool_box.save_audit_result(
        context, candidate.id, auditor_service.AUDIT_REJECT,
        "PORTRAIT_INSUFFICIENT", _reason("PORTRAIT_INSUFFICIENT"))
    assert saved["reject_code"] == "PORTRAIT_INSUFFICIENT"
    stored = await MatchCandidate.get(id=row.id)
    assert stored.audit_status == auditor_service.AUDIT_REJECT
    assert stored.audit_round == 1 and "作息" in stored.reject_reason


async def test_reject_without_reason_is_refused(db):
    """否决要写明理由，只给分类不给理由的调用被拒。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    task = await _open_task(member)
    await _put(task, candidate)
    with pytest.raises(CustomException) as error:
        await tool_box.save_audit_result(
            await _context(member, task), candidate.id,
            auditor_service.AUDIT_REJECT, "MISMATCH_HARD", "   ")
    assert "否决要写明理由" in error.value.message


async def test_save_result_of_candidate_outside_the_pool_is_refused(db):
    """回填一位不在候选池里的租客会被拒：先筛出来才谈得上审。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    task = await _open_task(member)
    with pytest.raises(CustomException) as error:
        await tool_box.save_audit_result(
            await _context(member, task), candidate.id, auditor_service.AUDIT_PASS)
    assert "不在本次任务的候选池里" in error.value.message


async def test_pass_of_another_gender_is_refused(db):
    """合租只找同性：给异性候选判通过时工具层直接拒绝，候选池里那条不动。"""
    member = await _make_applicant()  # 男
    candidate = await _make_candidate(gender="女")
    task = await _open_task(member)
    row = await _put(task, candidate)
    context = await _context(member, task)
    with pytest.raises(CustomException) as error:
        await tool_box.save_audit_result(
            context, candidate.id, auditor_service.AUDIT_PASS)
    assert "合租只找同性" in error.value.message
    assert "不能判通过" in error.value.message
    assert (await MatchCandidate.get(id=row.id)).audit_status == auditor_service.AUDIT_WAIT
    # 判否决不受这条限制：性别不同本来就该否决
    saved = await tool_box.save_audit_result(
        context, candidate.id, auditor_service.AUDIT_REJECT,
        "MISMATCH_HARD", "性别不同，合租只找同性")
    assert saved["audit_status"] == auditor_service.AUDIT_REJECT


async def test_audit_result_can_only_be_written_once(db):
    """审核结论只回填一次：同一批里重复回填不能再改结论。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    task = await _open_task(member)
    row = await _put(task, candidate)
    context = await _context(member, task, round_no=2)
    saved = await tool_box.save_audit_result(
        context, candidate.id, auditor_service.AUDIT_PASS)
    assert saved["audit_status"] == auditor_service.AUDIT_PASS
    with pytest.raises(CustomException) as error:
        await tool_box.save_audit_result(
            context, candidate.id, auditor_service.AUDIT_REJECT,
            "MISMATCH_HARD", "想改成否决")
    assert "已经有审核结论" in error.value.message
    assert "只能回填一次" in error.value.message
    stored = await MatchCandidate.get(id=row.id)
    assert stored.audit_status == auditor_service.AUDIT_PASS
    assert stored.reject_code is None and stored.reject_reason is None
    assert stored.audit_round == 2


async def test_audit_result_of_a_decided_row_is_refused(db):
    """跨批/重审覆盖同样拒绝：已经审过的行不能再被另一条结论改写。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    task = await _open_task(member)
    row = await _put(task, candidate, audit_status=auditor_service.AUDIT_REJECT,
                     reject_code="MISMATCH_HARD", reject_reason="之前判过", audit_round=1)
    with pytest.raises(CustomException) as error:
        await tool_box.save_audit_result(
            await _context(member, task, round_no=2), candidate.id,
            auditor_service.AUDIT_PASS)
    assert "已经有审核结论" in error.value.message
    stored = await MatchCandidate.get(id=row.id)
    assert stored.audit_status == auditor_service.AUDIT_REJECT
    assert stored.reject_code == "MISMATCH_HARD"
    assert stored.reject_reason == "之前判过"
    assert stored.audit_round == 1


# ---------------------------------------------------------------- 纯函数


def test_summarize_accepts_a_single_audited_object():
    """模型只审一位时可能把 audited 写成单个对象，计数要按 1 条算。"""
    text = auditor_service._summarize({"audited": {
        "candidate_member_id": 1, "audit_status": auditor_service.AUDIT_PASS}})
    assert "1 条" in text and "通过 1 人、否决 0 人" in text


async def test_batch_size_follows_the_role_limit(db):
    """一批能装几位按角色的工具调用上限算，一个人两次调用，还要留收尾的余量。"""
    agent = await AgentDefinition.get(agent_code="AUDITOR")
    original = agent.max_tool_call
    try:
        await AgentDefinition.filter(id=agent.id).update(max_tool_call=30)
        assert await auditor_service.batch_size(await AgentDefinition.get(id=agent.id)) == 10
        await AgentDefinition.filter(id=agent.id).update(max_tool_call=8)
        assert await auditor_service.batch_size(await AgentDefinition.get(id=agent.id)) == 2
        # 上限小到装不下一个人时也至少审一位，不能一批都不跑
        await AgentDefinition.filter(id=agent.id).update(max_tool_call=4)
        assert await auditor_service.batch_size(await AgentDefinition.get(id=agent.id)) == 1
        # 角色没填上限时按系统参数里的统一上限算
        await AgentDefinition.filter(id=agent.id).update(max_tool_call=None)
        assert await auditor_service.batch_size(await AgentDefinition.get(id=agent.id)) == 10
    finally:
        await AgentDefinition.filter(id=agent.id).update(max_tool_call=original)


async def test_hard_violations_reads_the_must_dimensions(db):
    """代码复核按候选方标为必须的条件逐项比对申请方，验不过的维度名要列出来。"""
    # 宠物那一项比的是是否养宠，先造一位养宠的申请方，
    # 「不接受室友养宠」这条才有东西可比
    applicant = await _make_applicant(has_pet="有")
    cases = [
        ({"budget_min": 3000, "budget_max": 3500, "budget_required": "必须"}, "预算"),
        ({"tidiness_min": "洁癖", "tidiness_required": "必须"}, "整洁度"),
        ({"lease_min": "2年以上", "lease_required": "必须"}, "租期"),
        ({"store_scope": "同片区", "store_required": "必须"}, "门店"),
        ({"schedule_accept": "夜猫子", "schedule_required": "必须"}, "作息"),
        ({"pet_accept": "不接受", "pet_required": "必须"}, "宠物态度"),
        ({"age_min": 20, "age_max": 30, "age_required": "必须"}, "年龄"),
    ]
    for overrides, expected in cases:
        candidate = await _make_candidate()
        preference = await _make_preference(candidate, **overrides)
        bad = auditor_service.hard_violations(applicant, candidate, preference)
        assert bad == [expected], f"候选方的必须项应该判在 {expected} 上"


async def test_must_dimensions_without_constraint_are_skipped(db):
    """标了必须但填成不限的维度对谁都成立，不该算不满足。"""
    applicant = await _make_applicant()
    candidate = await _make_candidate()
    preference = await _make_preference(
        candidate, tidiness_min=None, tidiness_required="必须",
        lease_min="3个月以下", lease_required="必须",
        store_scope="不限", store_required="必须",
        schedule_accept="早睡早起,正常作息,夜猫子", schedule_required="必须",
        pet_accept="无所谓", pet_required="必须")
    assert auditor_service.hard_violations(applicant, candidate, preference) == []
    # 申请方那一项没填时也不在这里判：那是判断不了，归审核官去分类
    silent = await _make_applicant(rent_budget=None)
    other = await _make_candidate()
    preference = await _make_preference(other, budget_min=3000, budget_max=3500,
                                        budget_required="必须")
    assert auditor_service.hard_violations(silent, other, preference) == []


async def test_instruction_lists_the_batch_and_the_rules(db):
    """交给审核官的交代要写清审谁、一位一位审、三种分类怎么判、结论的格式。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    task = await _open_task(member)
    row = await _put(task, candidate)
    text = auditor_service.instruction([(row, candidate)], pending=3, batch_no=2)
    assert str(candidate.id) in text and "第 2 批" in text
    assert "候选池里还有 3 位等着审" in text
    for code in tool_box.REJECT_CODES:
        assert code in text
    assert "一位一位来" in text and "名单外的候选不要动" in text


async def test_candidate_text_keeps_the_preference_out(db):
    """给模型看的候选名单里不放他们各自的合住偏好：偏好要审核官自己去读。"""
    member = await _make_applicant()
    candidate = await _make_candidate()
    await _make_preference(candidate)
    task = await _open_task(member)
    row = await _put(task, candidate)
    text = auditor_service.candidate_text([(row, candidate)])
    assert f"候选编号 {candidate.id}" in text and candidate.nickname in text
    assert "必须" not in text and "加分" not in text


async def test_distribution_lists_three_codes(db):
    """否决分类固定列三类，没有出现的那一类补 0，每一类都带上下一步做什么。"""
    rows = [{"reject_code": "PORTRAIT_INSUFFICIENT"},
            {"reject_code": "PORTRAIT_INSUFFICIENT"},
            {"reject_code": None}]
    items = auditor_service.distribution(rows)
    assert [item["code"] for item in items] == list(tool_box.REJECT_CODES)
    assert [item["count"] for item in items] == [0, 0, 2]
    assert items[2]["label"] == "申请方画像缺候选方在意的维度，判断不了"
    assert items[2]["solution"] == "补充资料后再匹配"
    assert items[0]["solution"] == "本候选不匹配"
