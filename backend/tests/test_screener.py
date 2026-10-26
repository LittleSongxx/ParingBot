"""候选筛选接口、筛选流程与放宽校验的测试。

分三段看：第一段走接口，盯住发起筛选之前的条件核对与拦截，条件不满足时
提示里要写清去哪做什么，而且要一条模型调用都不发出去；第二段用一个按剧本
回话的假模型替掉真实模型，把筛选的每一轮整条跑起来，盯住候选落库、每一轮的
放宽说明、轮次人数、步骤与工具调用日志；第三段盯住纯函数与放宽边界：说明怎么解析、
越界怎么拒、偏好文本有没有带上必须加分的标注。

用假模型是为了不依赖真实模型 Key：真调一次要联网、要花钱，还跑不出稳定的断言。
这一段要验的是筛选流程和放宽边界，跟模型是谁无关，剧本里给什么、结果就该是什么。
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
                    MatchCandidate, MatchTask, RoommatePreference, MemberProfile, SysConfig,
                    ToolCallLog, User)
from service import screener_service

TEST_MARK = "单元测试专用"
PASSWORD = "abc123456"
# 造出来的账号编号挑一个远大于正式数据的区间
USER_ID_SEED = count(900200000)


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
        usage_metadata={"input_tokens": 200, "output_tokens": 80, "total_tokens": 280})


def _round_script(ids: list, found_round: int, note: str = "", score: int = 80) -> list:
    """一轮的剧本：先读偏好，再检索，把候选写进池子，最后给出结构化结论。"""
    rows = [{"candidate_member_id": item, "screen_score": score} for item in ids]
    return [
        _tool_call("read_roommate_preference", {}, f"read{found_round}"),
        _tool_call("search_members", {"gender": "男"}, f"search{found_round}"),
        _tool_call("save_candidates",
                   {"candidates": rows, "found_round": found_round, "relax_note": note},
                   f"save{found_round}"),
        _json_reply({"candidates": rows, "relax_note": note,
                     "summary": f"这一轮筛出 {len(rows)} 人"}),
    ]


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


async def _make_applicant() -> MemberProfile:
    """造一位填写完整、也填了合住偏好的申请方，连账号一起造。"""
    user = await User.create(
        username=f"screen{uuid4().hex[:8]}{TEST_MARK}", password="x",
        name=f"筛选申请{TEST_MARK}", role="USER")
    member = await MemberProfile.create(
        user_id=user.id, nickname=f"筛选申请{TEST_MARK}", gender="男",
        birth_date=datetime(1994, 3, 12), rent_budget=3900, tidiness="整洁",
        occupation="产品经理", lease_term="1-2年", store_id=1, schedule_type="早睡早起",
        self_intro="平时喜欢爬山和看展，周末常在家做饭。", audit_status="已通过")
    await RoommatePreference.create(
        member_id=member.id,
        age_min=24, age_max=32, age_required="加分",
        budget_min=3000, budget_max=3750, budget_required="加分",
        tidiness_min="一般", tidiness_required="必须",
        store_scope="同片区", store_required="加分",
        schedule_accept="早睡早起", schedule_required="加分",
        lease_min="6-12个月", lease_required="必须",
        pet_accept="接受", pet_required="加分")
    return member


async def _make_candidate(**overrides) -> MemberProfile:
    """造一位资料已通过审核的候选租客，昵称带测试标记，跑完由清扫夹具回收。"""
    payload = {
        "user_id": next(USER_ID_SEED), "nickname": f"筛选候选{TEST_MARK}", "gender": "男",
        "birth_date": datetime(1997, 8, 6), "rent_budget": 3250, "tidiness": "一般",
        "occupation": "会计", "lease_term": "6-12个月", "store_id": 2,
        "schedule_type": "早睡早起", "interest_tags": "爬山,看电影", "audit_status": "已通过",
    }
    payload.update(overrides)
    return await MemberProfile.create(**payload)


async def _open_task(member: MemberProfile) -> MatchTask:
    return await MatchTask.create(
        member_id=member.id, task_no=f"SCREEN-{TEST_MARK}-{uuid4().hex[:8]}",
        deliver_count=8, status=screener_service.TASK_RUNNING)


async def _open_run(task: MatchTask) -> AgentRun:
    run = await AgentRun.create(
        run_no=f"SCREEN-{TEST_MARK}-{uuid4().hex[:8]}", task_id=task.id,
        run_type=screener_service.RUN_TYPE, run_status=screener_service.RUN_RUNNING,
        current_round=1, start_time=now())
    await MatchTask.filter(id=task.id).update(run_id=run.id)
    task.run_id = run.id
    return run


async def _context(member: MemberProfile, task: MatchTask, run: AgentRun,
                   round_no: int = 1) -> tool_box.ToolContext:
    return tool_box.ToolContext(run_id=run.id, agent_code=screener_service.AGENT_CODE,
                                task_id=task.id, member_id=member.id, round_no=round_no)


def _register(client, username: str) -> dict:
    return client.post("/register", json={
        "username": username, "password": PASSWORD, "confirmPassword": PASSWORD}).json()


def _login(client, username: str) -> dict:
    body = client.post("/login", json={"username": username, "password": PASSWORD}).json()
    assert body["code"] == "200", body["msg"]
    return {"token": body["data"]["token"]}


def _profile_payload(**overrides) -> dict:
    payload = {
        "nickname": f"筛选租客{TEST_MARK}",
        "gender": "男",
        "birth_date": "1994-03-12",
        "rent_budget": 3900,
        "tidiness": "整洁",
        "occupation": "产品经理",
        "lease_term": "1-2年",
        "store_id": 1,
        "schedule_type": "早睡早起",
        "self_intro": "平时喜欢爬山和看展。",
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


def test_target_gender_is_the_same_as_applicant():
    """合租按同性匹配：申请方是男就只在男租客里找，是女就只在女租客里找。"""
    assert screener_service.target_gender(SimpleNamespace(gender="男")) == "男"
    assert screener_service.target_gender(SimpleNamespace(gender="女")) == "女"


def test_my_candidates_points_to_profile_first(client):
    """还没填资料时，页面第一句要指到租客档案页，候选和轮次都是空的。"""
    username = f"screen1{TEST_MARK}"
    assert _register(client, username)["code"] == "200"
    headers = _login(client, username)
    data = client.get("/screener/my", headers=headers).json()["data"]
    assert data["has_profile"] is False
    assert data["task"] is None
    assert data["rounds"] == [] and data["candidates"] == []
    blocker = data["readiness"]["blocker"]
    assert blocker["key"] == "profile"
    assert blocker["action_path"] == "/front/memberProfile"
    assert data["readiness"]["can_run"] is False


def test_my_candidates_asks_for_preference_after_profile(client):
    """资料填好但还没填合住偏好时，第二项卡住并指向合住偏好页。"""
    username = f"screen2{TEST_MARK}"
    _register(client, username)
    headers = _login(client, username)
    saved = client.post("/member/saveMy", json=_profile_payload(), headers=headers).json()
    assert saved["code"] == "200", saved["msg"]
    data = client.get("/screener/my", headers=headers).json()["data"]
    assert data["has_profile"] is True
    checks = data["readiness"]["checks"]
    assert [item["key"] for item in checks] == ["profile", "preference"]
    assert checks[0]["ok"] is True
    assert data["readiness"]["blocker"]["action_path"] == "/front/myPreference"


def test_generate_stops_before_calling_the_model(client):
    """筛选没有独立执行入口，只能由智能匹配里的主管调度。"""
    assert client.post("/screener/generate").status_code == 404


def test_my_candidates_is_closed_to_admin(client, admin_headers):
    """管理员账号不参与合租匹配，进这一页要提示换成租客账号。"""
    body = client.get("/screener/my", headers=admin_headers).json()
    # 权限不够的返回码是 403，前端按这个码提示换成租客账号
    assert body["code"] == "403"
    assert "租客账号" in body["msg"]


def test_select_candidate_of_missing_row(client, user_headers):
    """查一个不存在的候选时，提示要能指回页面刷新。"""
    body = client.get("/screener/selectCandidate",
                      params={"candidate_id": 999999999},
                      headers=user_headers).json()
    assert body["code"] == "500"
    assert "刷新" in body["msg"]


# ---------------------------------------------------------------- 筛选流程


async def test_one_round_is_enough(db, monkeypatch):
    """候选够交付人数时只跑硬筛一轮：候选落库、步骤与工具日志留痕。"""
    member = await _make_applicant()
    first, second = await _make_candidate(), await _make_candidate()
    task = await _open_task(member)
    run = await _open_run(task)
    _use_fake_model(monkeypatch, _round_script([first.id, second.id], 1))

    result = await screener_service.build_candidates(
        member.id, task.id, run.id, deliver_count=2)

    assert result.gate is None
    assert len(result.rounds) == 1 and result.total == 2
    assert "一共筛了 1 轮，候选池累计 2 人" in result.conclusion
    assert "已经达到交付要求的 2 人" in result.conclusion
    # 反查数据库：页面上的数字全部以库里的为准
    rows = await MatchCandidate.filter(task_id=task.id).order_by("candidate_member_id")
    assert [row.candidate_member_id for row in rows] == sorted([first.id, second.id])
    assert all(row.found_round == 1 for row in rows)
    assert all(row.relax_note is None for row in rows)
    assert all(row.audit_status == "待审核" for row in rows)
    assert all(row.screen_score == 80 for row in rows)

    steps = await AgentStep.filter(run_id=run.id).order_by("step_index")
    assert [step.step_type for step in steps] == ["工具调用", "工具调用", "工具调用", "角色结论"]
    assert [step.tool_code for step in steps[:3]] == [
        "read_roommate_preference", "search_members", "save_candidates"]
    assert steps[0].agent_code == "SCREENER" and steps[0].round_no == 1
    assert steps[-1].step_status == "已完成"

    logs = await ToolCallLog.filter(run_id=run.id).order_by("id")
    assert [log.tool_code for log in logs] == [
        "read_roommate_preference", "search_members", "save_candidates"]
    assert all(log.success == "是" for log in logs)
    assert logs[2].row_count == 2



async def test_short_of_deliver_count_relaxes_one_dimension(db, monkeypatch):
    """第一轮不够交付人数时，第二轮放宽一个加分维度再筛，放宽说明挂在新筛出来的人身上。"""
    member = await _make_applicant()
    first = await _make_candidate()
    second, third = await _make_candidate(), await _make_candidate()
    task = await _open_task(member)
    run = await _open_run(task)
    fake = _use_fake_model(monkeypatch, _round_script([first.id], 1)
                           + _round_script([second.id, third.id], 2, note="年龄上限+2"))

    result = await screener_service.build_candidates(
        member.id, task.id, run.id, deliver_count=3)

    assert result.gate is None
    assert len(result.rounds) == 2 and result.total == 3
    assert result.rounds[0].note is None
    assert result.rounds[1].note == "年龄上限+2"
    assert "第 2 轮放宽了「年龄上限+2」" in result.conclusion
    rows = await MatchCandidate.filter(task_id=task.id, found_round=2)
    assert len(rows) == 2
    assert all(row.relax_note == "年龄上限+2" for row in rows)
    # 第 1 轮那一条不带放宽说明：放宽说明只挂在放宽那一轮筛出来的人身上
    assert await MatchCandidate.filter(task_id=task.id, relax_note__not_isnull=True).count() == 2

    # 第 2 轮的提示词里说明这是第几轮、最多动一个加分维度、还能放宽几轮
    second_round_system = fake.systems[4]
    assert "第 2 轮候选" in second_round_system
    assert "最多放宽一个标为加分的维度" in second_round_system
    assert "这次运行还能再放宽 3 轮" in second_round_system
    assert "可以放宽的维度：年龄" in second_round_system

    # 步骤按轮记：两轮各三条工具调用加一条结论
    steps = await AgentStep.filter(run_id=run.id).order_by("round_no", "step_index")
    assert [step.round_no for step in steps] == [1, 1, 1, 1, 2, 2, 2, 2]
    assert [step.step_type for step in steps] == (
        ["工具调用", "工具调用", "工具调用", "角色结论"] * 2)


async def test_round_rows_keep_a_round_that_found_nobody(db, monkeypatch):
    """放宽了但一个人也没新增的那一轮也要出现在轮次表里：那一轮确实发生过。"""
    member = await _make_applicant()
    first = await _make_candidate()
    second, third = await _make_candidate(), await _make_candidate()
    task = await _open_task(member)
    run = await _open_run(task)
    _use_fake_model(monkeypatch, _round_script([first.id], 1)
                    + _round_script([], 2, note="门店+1级")
                    + _round_script([second.id, third.id], 3, note="作息+1级"))

    result = await screener_service.build_candidates(
        member.id, task.id, run.id, deliver_count=3)

    assert len(result.rounds) == 3 and result.total == 3
    rounds = await screener_service.round_rows(task)
    assert [item["round"] for item in rounds] == [1, 2, 3]
    assert [item["added"] for item in rounds] == [1, 0, 2]
    assert [item["total"] for item in rounds] == [1, 1, 3]
    assert rounds[1]["relax_note"] == "门店+1级"


async def test_stops_when_a_round_relaxes_nothing(db, monkeypatch):
    """放宽轮没有放宽条件时收尾：再来一轮还是同一批人，白跑一次。"""
    member = await _make_applicant()
    first, second = await _make_candidate(), await _make_candidate()
    task = await _open_task(member)
    run = await _open_run(task)
    fake = _use_fake_model(monkeypatch, _round_script([first.id], 1)
                           + _round_script([second.id], 2, note="年龄上限+2")
                           + _round_script([], 3))

    result = await screener_service.build_candidates(
        member.id, task.id, run.id, deliver_count=10)

    assert result.gate is None
    assert len(result.rounds) == 3 and result.total == 2
    assert "还差 8 人" in result.conclusion
    # 三轮各 4 次模型来回，第 4 轮没有发生
    assert fake.calls == 12


async def test_relax_rounds_are_capped_by_config(db, monkeypatch):
    """放宽轮数按系统参数封顶：参数改成 1 时，硬筛之后只再放宽一轮就收。"""
    config = await SysConfig.get(config_key="SCREENER_MAX_RELAX")
    original = config.config_value
    member = await _make_applicant()
    first, second, third = await _make_candidate(), await _make_candidate(), await _make_candidate()
    task = await _open_task(member)
    run = await _open_run(task)
    fake = _use_fake_model(monkeypatch, _round_script([first.id], 1)
                           + _round_script([second.id], 2, note="预算下限-200")
                           + _round_script([third.id], 3, note="门店+1级"))
    try:
        await SysConfig.filter(id=config.id).update(config_value="1")
        result = await screener_service.build_candidates(
            member.id, task.id, run.id, deliver_count=10)
    finally:
        await SysConfig.filter(id=config.id).update(config_value=original)
    assert len(result.rounds) == 2 and result.total == 2
    # 第 3 轮压根没跑，剧本里那一段没有用上
    assert fake.calls == 8
    assert await MatchCandidate.filter(task_id=task.id, found_round=3).count() == 0


async def test_candidate_of_another_pool_is_refused(db):
    """拿别人的候选编号来查看会被挡住：只能看自己候选池里的人。"""
    owner = await _make_applicant()
    other = await _make_applicant()
    candidate = await _make_candidate()
    task = await _open_task(owner)
    row = await MatchCandidate.create(
        task_id=task.id, candidate_member_id=candidate.id, found_round=1,
        screen_score=70, audit_status="待审核")
    viewer = await User.get(id=other.user_id)
    with pytest.raises(CustomException) as error:
        await screener_service.candidate_detail(viewer, row.id)
    assert "不在你的候选池里" in error.value.message


async def test_disabled_role_is_refused_before_anything_is_written(db, monkeypatch):
    """筛选官被停用时直接拦住，提示指回子 Agent 定义，候选池一条都不写。"""
    member = await _make_applicant()
    first = await _make_candidate()
    task = await _open_task(member)
    run = await _open_run(task)
    agent = await AgentDefinition.get(agent_code="SCREENER")
    _use_fake_model(monkeypatch, _round_script([first.id], 1))
    try:
        await AgentDefinition.filter(id=agent.id).update(enabled="否")
        with pytest.raises(CustomException) as error:
            await screener_service.build_candidates(member.id, task.id, run.id, deliver_count=2)
    finally:
        await AgentDefinition.filter(id=agent.id).update(enabled="是")
    assert "停用" in error.value.message
    assert "子 Agent 定义" in error.value.message
    assert await MatchCandidate.filter(task_id=task.id).count() == 0


async def test_readiness_reports_missing_model_config(db):
    """七项检查里最后一项是模型配置：它没配好时提示指向 AI模型配置。"""
    member = await _make_applicant()
    config = await AiModelConfig.filter(
        model_purpose="筛选", enabled="是").order_by("-id").first()
    assert config is not None, "初始化数据里应该有一条筛选用途的模型配置"
    try:
        await AiModelConfig.filter(id=config.id).update(enabled="否")
        state = await screener_service.readiness(member)
    finally:
        await AiModelConfig.filter(id=config.id).update(enabled="是")
    assert state["can_run"] is False
    assert state["blocker"]["key"] == "model"
    assert "AI模型配置" in state["blocker"]["message"]
    assert [item["key"] for item in state["checks"]] == [
        "profile", "preference", "agent", "prompt", "tool", "model"]
    assert all(item["ok"] for item in state["checks"][:-1])


async def test_tool_call_gate_interrupts_the_role(db, monkeypatch):
    """工具调用次数用满时中断当前角色，把触发了哪道闸作为结论返回，不抛异常。"""
    member = await _make_applicant()
    task = await _open_task(member)
    run = await _open_run(task)
    agent = await AgentDefinition.get(agent_code="SCREENER")
    original = agent.max_tool_call
    try:
        await AgentDefinition.filter(id=agent.id).update(max_tool_call=2)
        _use_fake_model(monkeypatch, [
            _tool_call("search_members", {}, f"g{index}") for index in range(6)])
        result = await screener_service.build_candidates(
            member.id, task.id, run.id, deliver_count=2)
    finally:
        await AgentDefinition.filter(id=agent.id).update(max_tool_call=original)
    assert result.gate == agents.GATE_TOOL_CALL
    assert "上限" in result.conclusion


async def test_generate_creates_task_and_run(db, monkeypatch):
    """租客点一次筛选走完整条路：开任务、开运行、筛完收尾，任务和运行都有结论。"""
    member = await _make_applicant()
    first, second = await _make_candidate(), await _make_candidate()
    user = await User.get(id=member.user_id)
    config = await AiModelConfig.filter(
        model_purpose="筛选", enabled="是").order_by("-id").first()
    # 用的是开发库里那条正式配置，跑完要原样还回去：密钥那一列尤其不能写成空，
    # 那等于把管理员填好的密钥冲掉，后面再跑这条链路就连不上模型了
    key_original = config.api_key
    deliver = await SysConfig.get(config_key="MATCH_DELIVER_COUNT")
    deliver_original = deliver.config_value
    _use_fake_model(monkeypatch, _round_script([first.id, second.id], 1))
    try:
        await AiModelConfig.filter(id=config.id).update(api_key="test-key")
        await SysConfig.filter(id=deliver.id).update(config_value="2")
        data = await screener_service.generate(user)
    finally:
        await AiModelConfig.filter(id=config.id).update(api_key=key_original)
        await SysConfig.filter(id=deliver.id).update(config_value=deliver_original)

    assert data["total"] == 2 and data["rounds"] == 1
    task = await MatchTask.get(id=data["task_id"])
    assert task.status == "已完成"
    assert task.total_round == 1 and task.member_id == member.id
    assert task.error_message is None
    run = await AgentRun.get(id=task.run_id)
    assert run.run_status == "已完成" and run.task_id == task.id
    assert run.output_summary and "已经达到交付要求" in run.output_summary
    assert run.cost_millis is not None and run.end_time is not None

    page = await screener_service.my_page(user)
    assert page["task"]["id"] == task.id
    assert [item["round"] for item in page["rounds"]] == [1]
    assert len(page["candidates"]) == 2


async def test_generate_fails_when_nothing_is_found(db, monkeypatch):
    """一个人都没筛出来时判失败：任务和运行都记下失败原因，页面看得到。"""
    member = await _make_applicant()
    user = await User.get(id=member.user_id)
    config = await AiModelConfig.filter(
        model_purpose="筛选", enabled="是").order_by("-id").first()
    key_original = config.api_key
    # 第一轮一个人都没筛到、也没有放宽说明，筛选会再跑一轮；两轮都写空
    _use_fake_model(monkeypatch, _round_script([], 1) + _round_script([], 2))
    try:
        await AiModelConfig.filter(id=config.id).update(api_key="test-key")
        with pytest.raises(CustomException) as error:
            await screener_service.generate(user)
    finally:
        await AiModelConfig.filter(id=config.id).update(api_key=key_original)
    assert "一位候选都没有筛出来" in error.value.message
    assert "合住偏好" in error.value.message
    task = await MatchTask.filter(member_id=member.id).order_by("-id").first()
    assert task.status == "执行失败"
    assert task.total_round == 2
    assert "一位候选都没有筛出来" in task.error_message
    run = await AgentRun.get(id=task.run_id)
    assert run.run_status == "运行失败"
    assert await MatchCandidate.filter(task_id=task.id).count() == 0


# ---------------------------------------------------------------- 放宽边界


async def test_relax_over_accumulated_limit_is_refused(db):
    """同一个维度累计放宽到头之后再放宽会被拒绝，原因回到调用方手上。"""
    member = await _make_applicant()
    people = [await _make_candidate() for _ in range(4)]
    task = await _open_task(member)
    run = await _open_run(task)
    context = await _context(member, task, run)
    for index in range(3):
        await tool_box.invoke("save_candidates", {
            "candidates": [{"candidate_member_id": people[index].id, "screen_score": 70}],
            "found_round": index + 1, "relax_note": "年龄上限+2"}, context)
    with pytest.raises(CustomException) as error:
        await tool_box.invoke("save_candidates", {
            "candidates": [{"candidate_member_id": people[3].id, "screen_score": 70}],
            "found_round": 4, "relax_note": "年龄上限+2"}, context)
    assert "累计最多放宽 6岁" in error.value.message
    assert await MatchCandidate.filter(task_id=task.id).count() == 3


async def test_relax_round_limit_is_refused(db):
    """整次运行的放宽轮次用满之后再放宽会被拒绝，提示指回合住偏好。"""
    config = await SysConfig.get(config_key="SCREENER_MAX_RELAX")
    original = config.config_value
    member = await _make_applicant()
    people = [await _make_candidate() for _ in range(3)]
    task = await _open_task(member)
    run = await _open_run(task)
    context = await _context(member, task, run)
    try:
        await SysConfig.filter(id=config.id).update(config_value="2")
        await tool_box.invoke("save_candidates", {
            "candidates": [{"candidate_member_id": people[0].id, "screen_score": 70}],
            "found_round": 1, "relax_note": "年龄上限+2"}, context)
        await tool_box.invoke("save_candidates", {
            "candidates": [{"candidate_member_id": people[1].id, "screen_score": 70}],
            "found_round": 2, "relax_note": "预算下限-200"}, context)
        with pytest.raises(CustomException) as error:
            await tool_box.invoke("save_candidates", {
                "candidates": [{"candidate_member_id": people[2].id, "screen_score": 70}],
                "found_round": 3, "relax_note": "门店+1级"}, context)
    finally:
        await SysConfig.filter(id=config.id).update(config_value=original)
    assert "最多放宽 2 轮" in error.value.message
    assert "合住偏好" in error.value.message


async def test_must_dimension_cannot_be_relaxed(db):
    """标为必须的维度任何情况下都不许放宽。"""
    member = await _make_applicant()
    person = await _make_candidate()
    task = await _open_task(member)
    run = await _open_run(task)
    context = await _context(member, task, run)
    with pytest.raises(CustomException) as error:
        await tool_box.invoke("save_candidates", {
            "candidates": [{"candidate_member_id": person.id, "screen_score": 70}],
            "found_round": 1, "relax_note": "整洁度+1档"}, context)
    assert "必须" in error.value.message
    assert await MatchCandidate.filter(task_id=task.id).count() == 0


async def test_one_round_can_only_relax_one_dimension(db):
    """同一轮里第二次放宽会被拒绝：一轮只动一个维度。"""
    member = await _make_applicant()
    people = [await _make_candidate() for _ in range(2)]
    task = await _open_task(member)
    run = await _open_run(task)
    context = await _context(member, task, run)
    await tool_box.invoke("save_candidates", {
        "candidates": [{"candidate_member_id": people[0].id, "screen_score": 70}],
        "found_round": 1, "relax_note": "年龄上限+2"}, context)
    with pytest.raises(CustomException) as error:
        await tool_box.invoke("save_candidates", {
            "candidates": [{"candidate_member_id": people[1].id, "screen_score": 70}],
            "found_round": 1, "relax_note": "预算下限-200"}, context)
    assert "一轮最多放宽一个维度" in error.value.message


async def test_relax_note_must_be_readable(db):
    """说不清放宽了多少的说明一律拒绝：累计上限算不出来，页面也没法显示。"""
    member = await _make_applicant()
    person = await _make_candidate()
    task = await _open_task(member)
    run = await _open_run(task)
    context = await _context(member, task, run)
    for note, tip in (("接受晚睡的人", "可放宽的维度"),
                      ("年龄放宽到35", "上限还是下限"),
                      ("年龄上限+3", "一次最多放宽 2岁"),
                      ("年龄上限-2", "只能往上放宽")):
        with pytest.raises(CustomException) as error:
            await tool_box.invoke("save_candidates", {
                "candidates": [{"candidate_member_id": person.id, "screen_score": 70}],
                "found_round": 1, "relax_note": note}, context)
        assert tip in error.value.message, note
    assert await MatchCandidate.filter(task_id=task.id).count() == 0


async def test_model_claim_that_is_not_recorded_is_flagged(db, monkeypatch):
    """模型在结论里说放宽了、但候选池里没有这一轮的放宽说明时，结论里要点出来。"""
    member = await _make_applicant()
    first = await _make_candidate()
    task = await _open_task(member)
    run = await _open_run(task)
    script = _round_script([first.id], 1)
    script[-1] = _json_reply({"candidates": [{"candidate_member_id": first.id,
                                              "screen_score": 80}],
                              "relax_note": "年龄上限+2", "summary": "筛出 1 人"})
    _use_fake_model(monkeypatch, script)

    result = await screener_service.build_candidates(
        member.id, task.id, run.id, deliver_count=1)

    assert result.rounds[0].note is None
    assert "但这一轮的放宽没有写进候选池" in result.rounds[0].mismatch
    assert "放宽没有写进候选池" in result.conclusion


# ---------------------------------------------------------------- 纯函数


async def test_parse_relax_reads_a_readable_note(db):
    """能算得出幅度的说明都要认：全角半角、带不带单位、写加还是写加号。"""
    assert tool_box.parse_relax("年龄上限+2")["amount"] == 2
    assert tool_box.parse_relax("年龄下限减 2")["amount"] == 2
    assert tool_box.parse_relax("预算下限-200元")["name"] == "预算"
    assert tool_box.parse_relax("片区放宽1级")["name"] == "门店"
    assert tool_box.parse_relax("整洁度+1档")["rule"]["total"] == 2
    assert tool_box.parse_relax("作息+1级")["rule"]["total"] == 1


async def test_parse_relax_rejects_unreadable_notes(db):
    """含混的说明一律拒绝，并且要说清该怎么写。"""
    with pytest.raises(CustomException) as empty:
        tool_box.parse_relax("   ")
    assert "这一轮没放宽就留空" in empty.value.message
    with pytest.raises(CustomException) as unknown:
        tool_box.parse_relax("宠物态度+1级")
    assert "可放宽的维度是" in unknown.value.message
    with pytest.raises(CustomException) as two:
        tool_box.parse_relax("年龄上限+2，门店+1级")
    assert "一轮最多放宽一个维度" in two.value.message
    with pytest.raises(CustomException) as no_number:
        tool_box.parse_relax("门店放宽")
    assert "要有幅度数字" in no_number.value.message


async def test_preference_text_marks_every_dimension(db):
    """偏好文本每个维度都要带上必须或加分，筛选官才分得清哪些能让步。"""
    member = await _make_applicant()
    context = tool_box.ToolContext(member_id=member.id)
    preference = await tool_box.read_roommate_preference(context)
    text = screener_service.preference_text(preference)
    assert "年龄：24-32岁（加分）" in text
    assert "整洁度：一般及以上（必须）" in text
    assert "门店：同片区（加分）" in text
    assert "作息：可接受 早睡早起（加分）" in text
    assert text.count("（必须）") == 2


async def test_relaxable_dimensions_skip_dimensions_without_rules(db):
    """可放宽清单按放宽规则表过滤：宠物态度即使标了加分也不在里面。"""
    member = await _make_applicant()
    preference = await RoommatePreference.get(member_id=member.id)
    names = [item["name"] for item in screener_service.relaxable_dimensions(preference)]
    assert names == ["年龄", "预算", "门店", "作息"]
    # 整洁度和租期标的是必须，宠物态度没有放宽规则，三种都不进来
    assert "整洁度" not in names and "租期" not in names and "宠物态度" not in names
