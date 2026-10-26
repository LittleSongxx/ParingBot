"""租客画像接口、执行器与标签核验的测试。

分三段看：第一段走接口，盯住「生成画像」之前的条件核对与拦截，条件不满足时
提示里要写清去哪做什么，而且要一条模型调用都不发出去；
第二段用一个按剧本回话的假模型替掉真实模型，把执行器的循环整条跑起来，
盯住步骤落库、工具调用日志、标签依据核验、版本累加和两道闸；
第三段盯住纯函数：模型输出里的 JSON 怎么取、标签怎么核。

用假模型是为了不依赖真实模型 Key：真调一次要联网、要花钱，还跑不出稳定的断言。
这一段要验的是执行器和业务规则，跟模型是谁无关，所以剧本里给什么、结果就该是什么。
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
                    MemberMoment, MemberPortrait, MemberProfile, SysConfig, ToolCallLog, User)
from service import portrait_service

TEST_MARK = "单元测试专用"
PASSWORD = "abc123456"
# 造出来的租客用户编号挑一个远大于正式数据的区间
USER_ID_SEED = count(900100000)

# 给模型看的材料和后面核验依据用的是同一份原文
INTRO = "工作日做设计，周末喜欢和朋友爬山，也爱在家做饭。"
MATE = "希望遇到一个愿意一起过日子的人。"
MOMENTS = ("上周末去了西湖边走了一大圈。", "最近在学做甜品，做了两次芝士蛋糕才成功。")


class FakeModel:
    """按剧本回话的假模型。

    剧本是一串 AIMessage：要它调工具就给带 tool_calls 的，要它交结论就给一段 JSON 文本。
    剧本用完最后一轮，之后每一轮都重复最后一条，方便测「模型一直不下结论」的闸。
    """

    def __init__(self, script: list):
        self.script = list(script)
        self.calls = 0
        self.specs = []
        self.seen_messages = []

    def bind_tools(self, specs):
        self.specs = specs
        return self

    async def ainvoke(self, messages):
        self.seen_messages = list(messages)
        index = min(self.calls, len(self.script) - 1)
        self.calls += 1
        return self.script[index]


def _tool_call(name: str, args: dict | None = None, call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[
        {"name": name, "args": args or {}, "id": call_id}])


def _json_reply(payload: dict) -> AIMessage:
    return AIMessage(
        content=json.dumps(payload, ensure_ascii=False),
        usage_metadata={"input_tokens": 120, "output_tokens": 60, "total_tokens": 180})


def _payload() -> dict:
    return {
        "personality_tags": ["开朗", "细心"],
        "lifestyle_tags": ["运动", "下厨"],
        "cohabit_need_tags": ["期待稳定"],
        "summary": "一位喜欢运动和做饭的设计师。",
        "evidence": {
            "开朗": "周末喜欢和朋友爬山",
            "细心": "做了两次芝士蛋糕才成功",
            "运动": "周末喜欢和朋友爬山",
            "下厨": "也爱在家做饭",
            "期待稳定": "希望遇到一个愿意一起过日子的人",
        },
    }


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


async def _make_member(intro: str = INTRO, mate: str | None = MATE,
                       moments: tuple = MOMENTS) -> MemberProfile:
    """造一位材料齐全的租客，昵称带测试标记，跑完由清扫夹具回收。"""
    member = await MemberProfile.create(
        user_id=next(USER_ID_SEED), nickname=f"画像租客{TEST_MARK}", gender="女",
        birth_date=datetime(1996, 5, 20), rent_budget=3250, tidiness="一般",
        occupation="设计师", lease_term="6-12个月", store_id=5, schedule_type="早睡早起",
        self_intro=intro, roommate_expectation=mate, interest_tags="爬山,看书",
        audit_status="已通过")
    for content in moments:
        await MemberMoment.create(member_id=member.id, content=content,
                                  visible="公开", publish_time=now())
    return member


async def _open_run() -> AgentRun:
    return await AgentRun.create(
        run_no=f"PORTRAIT-{TEST_MARK}-{uuid4().hex[:8]}", run_type="画像提取",
        run_status="运行中", current_round=1, start_time=now())


def _register(client, username: str) -> dict:
    return client.post("/register", json={
        "username": username, "password": PASSWORD, "confirmPassword": PASSWORD}).json()


def _login(client, username: str) -> dict:
    body = client.post("/login", json={"username": username, "password": PASSWORD}).json()
    assert body["code"] == "200", body["msg"]
    return {"token": body["data"]["token"]}


def _profile_payload(**overrides) -> dict:
    payload = {
        "nickname": f"画像租客{TEST_MARK}",
        "gender": "女",
        "birth_date": "1996-05-20",
        "rent_budget": 3250,
        "tidiness": "一般",
        "occupation": "设计师",
        "lease_term": "6-12个月",
        "store_id": 5,
        "schedule_type": "早睡早起",
        "self_intro": INTRO,
        "roommate_expectation": MATE,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- 接口层


def test_my_portrait_points_to_profile_first(client):
    """还没填资料时，页面第一句要指到租客档案页，画像和历史都是空的。"""
    username = f"huaxiang1{TEST_MARK}"
    assert _register(client, username)["code"] == "200"
    headers = _login(client, username)
    data = client.get("/portrait/my", headers=headers).json()["data"]
    assert data["has_profile"] is False
    assert data["portrait"] is None
    assert data["history"] == []
    blocker = data["readiness"]["blocker"]
    assert blocker["key"] == "profile"
    assert blocker["action_path"] == "/front/memberProfile"
    assert "租客档案" in blocker["message"]
    assert data["readiness"]["can_generate"] is False


def test_my_portrait_asks_for_moment_after_profile(client):
    """资料填好但一条动态都没有时，指向发动态；检查清单按顺序只列到卡住的那一项。"""
    username = f"huaxiang2{TEST_MARK}"
    _register(client, username)
    headers = _login(client, username)
    saved = client.post("/member/saveMy", json=_profile_payload(), headers=headers).json()
    assert saved["code"] == "200", saved["msg"]
    data = client.get("/portrait/my", headers=headers).json()["data"]
    assert data["has_profile"] is True
    checks = data["readiness"]["checks"]
    assert [item["key"] for item in checks] == ["profile", "moment"]
    assert checks[0]["ok"] is True
    assert data["readiness"]["blocker"]["action_path"] == "/front/myMoment"


def test_generate_stops_before_calling_the_model(client):
    """画像没有独立执行入口，只能由智能匹配里的主管调度。"""
    assert client.post("/portrait/generate").status_code == 404


def test_my_portrait_is_closed_to_admin(client, admin_headers):
    """管理员账号不参与合租匹配，进这一页要提示换成租客账号。"""
    body = client.get("/portrait/my", headers=admin_headers).json()
    # 权限不够的返回码是 403，前端按这个码提示换成租客账号
    assert body["code"] == "403"
    assert "租客账号" in body["msg"]


def test_select_one_of_missing_version(client, user_headers):
    """查一个不存在的版本时，提示要能指回页面刷新。"""
    body = client.get("/portrait/selectOne", params={"portrait_id": 999999999},
                      headers=user_headers).json()
    assert body["code"] == "500"
    assert "刷新" in body["msg"]


# ---------------------------------------------------------------- 执行器与服务层


async def test_portrait_written_with_steps_and_evidence(db, monkeypatch):
    """跑通一次提取：画像落库、步骤落库、工具日志落库、模型调用留痕。"""
    member = await _make_member()
    run = await _open_run()
    _use_fake_model(monkeypatch, [
        _tool_call("read_member_detail", {}, "c1"),
        _tool_call("read_member_moments", {"limit": 20}, "c2"),
        _json_reply(_payload()),
    ])

    result = await portrait_service.build_portrait(member.id, run.id)

    assert result.gate is None
    assert result.tool_calls == 2
    assert "画像 v1 已生成" in result.conclusion
    # 反查数据库，页面上的数字全部以库里的为准
    saved = await MemberPortrait.get(member_id=member.id)
    assert saved.version == 1
    assert saved.personality_tags == "开朗,细心"
    assert saved.lifestyle_tags == "运动,下厨"
    assert saved.cohabit_need_tags == "期待稳定"
    assert saved.run_id == run.id
    assert json.loads(saved.evidence)["运动"] == "周末喜欢和朋友爬山"

    steps = await AgentStep.filter(run_id=run.id).order_by("step_index")
    assert [step.step_type for step in steps] == ["工具调用", "工具调用", "角色结论"]
    assert [step.tool_code for step in steps[:2]] == ["read_member_detail", "read_member_moments"]
    assert steps[0].agent_code == "PORTRAIT" and steps[0].round_no == 1
    assert steps[-1].step_status == "已完成"

    logs = await ToolCallLog.filter(run_id=run.id).order_by("id")
    assert [log.tool_code for log in logs] == ["read_member_detail", "read_member_moments"]
    assert all(log.success == "是" for log in logs)
    assert logs[0].row_count == 1
    assert logs[1].row_count == len(MOMENTS)



async def test_portrait_version_accumulates_and_keeps_history(db, monkeypatch):
    """再提取一次产生新版本，旧版本原地留着，两个版本都能查到。"""
    member = await _make_member()
    for expected in (1, 2):
        run = await _open_run()
        _use_fake_model(monkeypatch, [
            _tool_call("read_member_detail", {}, "c1"),
            _json_reply(_payload()),
        ])
        result = await portrait_service.build_portrait(member.id, run.id)
        assert result.portrait is not None
        assert result.portrait.version == expected
    versions = await MemberPortrait.filter(member_id=member.id).order_by("version")
    assert [item.version for item in versions] == [1, 2]


async def test_tags_without_evidence_are_dropped(db, monkeypatch):
    """依据在原文里找不到的标签要被丢掉，丢掉了哪几个写进结论。"""
    member = await _make_member()
    run = await _open_run()
    payload = _payload()
    payload["personality_tags"] = ["开朗", "爱跑步"]
    payload["evidence"]["爱跑步"] = "我每天都跑十公里"
    _use_fake_model(monkeypatch, [
        _tool_call("read_member_detail", {}, "c1"),
        _json_reply(payload),
    ])

    result = await portrait_service.build_portrait(member.id, run.id)

    saved = await MemberPortrait.get(member_id=member.id)
    assert saved.personality_tags == "开朗"
    assert "爱跑步" in result.conclusion
    assert "原文里找不到依据" in result.conclusion
    assert result.dropped == ["爱跑步（原文里找不到依据）"]


async def test_no_verifiable_tag_means_no_portrait(db, monkeypatch):
    """三类标签一个都没验上时判这次提取失败：不落库，也不报成功。"""
    member = await _make_member()
    run = await _open_run()
    payload = _payload()
    payload["personality_tags"] = ["爱跑步"]
    payload["lifestyle_tags"] = ["露营"]
    payload["cohabit_need_tags"] = ["喜欢旅行"]
    payload["evidence"] = {"爱跑步": "我每天都跑十公里", "露营": "每年都出去露营",
                           "喜欢旅行": "走遍了很多国家"}
    _use_fake_model(monkeypatch, [
        _tool_call("read_member_detail", {}, "c1"),
        _json_reply(payload),
    ])

    result = await portrait_service.build_portrait(member.id, run.id)

    assert result.portrait is None
    assert "没有落库" in result.conclusion
    assert await MemberPortrait.filter(member_id=member.id).count() == 0


async def test_tool_call_gate_interrupts_the_role(db, monkeypatch):
    """工具调用次数用满时中断当前角色，把触发了哪道闸作为结论返回，不抛异常。"""
    member = await _make_member()
    run = await _open_run()
    agent = await AgentDefinition.get(agent_code="PORTRAIT")
    original = agent.max_tool_call
    try:
        await AgentDefinition.filter(id=agent.id).update(max_tool_call=2)
        _use_fake_model(monkeypatch, [
            _tool_call("read_member_moments", {}, f"c{index}") for index in range(6)])
        result = await portrait_service.build_portrait(member.id, run.id)
    finally:
        await AgentDefinition.filter(id=agent.id).update(max_tool_call=original)

    assert result.gate == agents.GATE_TOOL_CALL
    assert result.portrait is None
    assert "工具调用次数已经用满 2 次" in result.conclusion
    steps = await AgentStep.filter(run_id=run.id).order_by("step_index")
    assert [step.step_type for step in steps] == ["工具调用", "工具调用", "角色结论"]
    assert steps[-1].step_status == "运行失败"
    assert "达到上限" in steps[-1].error_message
    assert await MemberPortrait.filter(member_id=member.id).count() == 0


async def test_same_tool_gate_interrupts_the_role(db, monkeypatch):
    """同一个工具连续调用超过上限时同样中断，闸的口径从系统参数里读。"""
    member = await _make_member()
    run = await _open_run()
    row = await SysConfig.get(config_key="AGENT_MAX_SAME_TOOL")
    original = row.config_value
    try:
        await SysConfig.filter(id=row.id).update(config_value="2")
        _use_fake_model(monkeypatch, [
            _tool_call("list_interest_tags", {}, f"c{index}") for index in range(6)])
        result = await portrait_service.build_portrait(member.id, run.id)
    finally:
        await SysConfig.filter(id=row.id).update(config_value=original)

    assert result.gate == agents.GATE_SAME_TOOL
    assert "连续调用了 3 次" in result.conclusion
    # 前两次调用照常执行并留痕，第三次刚越线就被拦住，没有真的发出去
    assert await ToolCallLog.filter(run_id=run.id).count() == 2


async def test_missing_required_tool_is_sent_back(db, monkeypatch):
    """模型没读资料就想交结论时，执行器把它打回去，工具真的被调用之后才收结论。"""
    member = await _make_member()
    run = await _open_run()
    fake = _use_fake_model(monkeypatch, [
        _json_reply(_payload()),
        _tool_call("read_member_detail", {}, "c1"),
        _json_reply(_payload()),
    ])

    result = await portrait_service.build_portrait(member.id, run.id)

    assert result.portrait is not None
    assert fake.calls == 3
    texts = [agents.message_text(item) for item in fake.seen_messages]
    assert any("还没有调用" in text for text in texts)
    assert await ToolCallLog.filter(
        run_id=run.id, tool_code="read_member_detail").count() == 1
    assert await MemberPortrait.filter(member_id=member.id).count() == 1


async def test_non_json_answer_is_sent_back(db, monkeypatch):
    """模型回了一段话而不是 JSON 时纠正一次，第二次给对了就照常落库。"""
    member = await _make_member()
    run = await _open_run()
    fake = _use_fake_model(monkeypatch, [
        _tool_call("read_member_detail", {}, "c1"),
        AIMessage(content="好的，我马上帮你整理这位租客的标签。"),
        _json_reply(_payload()),
    ])

    result = await portrait_service.build_portrait(member.id, run.id)

    assert result.portrait is not None
    assert fake.calls == 3
    texts = [agents.message_text(item) for item in fake.seen_messages]
    assert any("JSON" in text for text in texts)


async def test_disabled_role_is_refused_before_anything_is_written(db, monkeypatch):
    """画像师被停用时直接拦住，提示指回子 Agent 定义，画像表一条都不写。"""
    member = await _make_member()
    run = await _open_run()
    agent = await AgentDefinition.get(agent_code="PORTRAIT")
    try:
        await AgentDefinition.filter(id=agent.id).update(enabled="否")
        with pytest.raises(CustomException) as error:
            await portrait_service.build_portrait(member.id, run.id)
    finally:
        await AgentDefinition.filter(id=agent.id).update(enabled="是")
    assert "停用" in error.value.message
    assert "子 Agent 定义" in error.value.message
    assert await MemberPortrait.filter(member_id=member.id).count() == 0


async def test_readiness_reports_missing_model_config(db):
    """六项检查里最后一项是模型配置：它没配好时提示指向 AI模型配置。"""
    member = await _make_member()
    config = await AiModelConfig.filter(model_purpose="画像", enabled="是").order_by("-id").first()
    assert config is not None, "初始化数据里应该有一条画像用途的模型配置"
    try:
        await AiModelConfig.filter(id=config.id).update(enabled="否")
        state = await portrait_service.readiness(member)
    finally:
        await AiModelConfig.filter(id=config.id).update(enabled="是")
    assert state["can_generate"] is False
    assert state["blocker"]["key"] == "model"
    assert "AI模型配置" in state["blocker"]["message"]
    # 前面几项都过了，清单停在这一项
    assert [item["key"] for item in state["checks"]] == [
        "profile", "moment", "agent", "prompt", "tool", "model"]
    assert all(item["ok"] for item in state["checks"][:-1])


async def test_run_agent_requires_a_run_record(db):
    """没有运行编号时不往下走：步骤记录没有地方落，跑了也说不清做过什么。"""
    with pytest.raises(CustomException) as error:
        await agents.run_agent("PORTRAIT", tool_box.ToolContext(member_id=1))
    assert "运行编号" in error.value.message


# ---------------------------------------------------------------- 纯函数


async def test_clean_portrait_rules(db):
    """标签核验的四条规则：留得下的、重复的、太长的、超额的、没依据的。"""
    long_tag = "特别特别长的标签" * 5
    data = {
        "summary": "性格开朗，热爱运动，也重视稳定关系。",
        "personality_tags": ["开朗", "开朗", long_tag, "爱跑步", "细心", "果断",
                             "幽默", "内向", "热情", "稳重"],
        "lifestyle_tags": ["运动"],
        "cohabit_need_tags": [],
        "evidence": {
            "开朗": "周末喜欢和朋友爬山",
            "爱跑步": "我每天都跑十公里",
            "细心": "做了两次芝士蛋糕才成功",
            "果断": "也爱在家做饭",
            "幽默": "也爱在家做饭",
            "内向": "也爱在家做饭",
            "热情": "也爱在家做饭",
            "稳重": "也爱在家做饭",
            "运动": "周末喜欢和朋友爬山",
        },
    }
    sources = f"自我介绍：{INTRO}\n动态1：{MOMENTS[0]}\n动态2：{MOMENTS[1]}"
    values, evidence, dropped, counts = portrait_service.clean_portrait(data, sources)

    assert values["summary"] == "性格开朗，热爱运动，也重视稳定关系。"
    assert values["personality_tags"] == "开朗,细心,果断,幽默,内向,热情"
    assert values["lifestyle_tags"] == "运动"
    assert values["cohabit_need_tags"] is None
    assert counts == {"personality_tags": 6, "lifestyle_tags": 1, "cohabit_need_tags": 0}
    assert evidence["运动"] == "周末喜欢和朋友爬山"
    assert "爱跑步（原文里找不到依据）" in dropped
    assert "稳重（超过每类 6 个）" in dropped
    assert any("标签太长" in item for item in dropped)


async def test_clean_portrait_keeps_nothing_when_evidence_is_empty(db):
    """模型一条依据都没给时，三类标签全被丢掉，调用方据此判失败。"""
    values, evidence, dropped, counts = portrait_service.clean_portrait(
        {"personality_tags": ["开朗"], "lifestyle_tags": ["运动"],
         "cohabit_need_tags": ["期待稳定"]}, INTRO)
    assert not any(counts.values())
    assert len(dropped) == 3
    assert evidence == {}
    assert values["personality_tags"] is None


async def test_first_json_object_handles_model_noise(db):
    """模型输出外面的解释文字和代码块标记都要能剥掉。"""
    assert agents.first_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert agents.first_json_object('结果如下：{"a": {"b": 2}}\n希望有帮助') == {"a": {"b": 2}}
    assert agents.first_json_object("抱歉，我不能这么做") is None
    assert agents.first_json_object("[1, 2]") is None
