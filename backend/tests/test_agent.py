"""子 Agent 定义与工具中心测试。

分三段看：第一段走接口，盯住四个角色的配置能不能改、编码写错时拦不拦得住；
第二段直接用服务层和工具层，盯住「停用之后模型手上真的没有这个工具了」这条；
第三段盯住工具调用日志：成功要记、失败也要记，页面上的试跑不记。

改动真实数据的用例都会在 finally 里改回去；试跑用例自己造租客、自己清掉。
"""

import pytest

from ai import tools
from common.exception_handler import CustomException
from models import FunctionTool, MemberProfile, ToolCallLog
from service import tool_service

TEST_MARK = "单元测试专用"
# 日志用例用的运行编号，挑一个远大于正式数据的数字，跑完按它清干净
TEST_RUN_ID = 900000001
# 初始化数据里就有的四个角色编码
ROLE_CODES = ("SUPERVISOR", "PORTRAIT", "SCREENER", "AUDITOR")


def _agents(client, admin_headers) -> list[dict]:
    body = client.get("/agentDefinition/list", headers=admin_headers).json()
    assert body["code"] == "200", body["msg"]
    return body["data"]["list"]


def _tool_row(client, admin_headers, code: str) -> dict:
    body = client.get("/functionTool/selectPage", params={"keyword": code},
                      headers=admin_headers).json()
    assert body["code"] == "200"
    return body["data"]["list"][0]


def test_list_returns_the_four_roles(client, admin_headers):
    """角色列表把四个角色和它们各自的提示词、工具池状态一起给出来。"""
    body = client.get("/agentDefinition/list", headers=admin_headers).json()
    data = body["data"]
    codes = [item["agent_code"] for item in data["list"]]
    for code in ROLE_CODES:
        assert code in codes, f"角色列表里少了 {code}"
    for item in data["list"]:
        for key in ("agent_name", "prompt_state", "tool_group", "tool_enabled",
                    "effective_max_tool_call", "max_tool_call_source", "is_supervisor"):
            assert key in item, f"角色里少了 {key}"
    assert data["default_max_tool_call"] >= 1
    assert isinstance(data["problems"], list)
    # 主管不调工具，它的分组本来就该是空的
    supervisor = next(item for item in data["list"] if item["agent_code"] == "SUPERVISOR")
    assert supervisor["is_supervisor"] is True
    assert not supervisor["tool_group"]


def test_options_list_prompts_and_groups(client, admin_headers):
    """编辑弹窗的两个下拉由后端给：可用的提示词和有工具的分组。"""
    body = client.get("/agentDefinition/options", headers=admin_headers).json()
    assert body["code"] == "200"
    data = body["data"]
    assert data["groups"], "工具分组不能是空的"
    assert data["prompts"], "可用的提示词模板不能是空的"
    for item in data["prompts"]:
        assert item["code"] and item["name"]


def test_update_rejects_unknown_prompt(client, admin_headers):
    """绑一个不存在的提示词编码时拦下，并说清去哪找。"""
    portrait = next(item for item in _agents(client, admin_headers)
                    if item["agent_code"] == "PORTRAIT")
    body = client.put("/agentDefinition/update",
                      json={"agent_id": portrait["id"], "agent_name": portrait["agent_name"],
                            "prompt_code": "NOT_EXIST_PROMPT", "tool_group": portrait["tool_group"],
                            "max_tool_call": portrait["max_tool_call"], "sort": portrait["sort"]},
                      headers=admin_headers).json()
    assert body["code"] == "500"
    assert "提示词模板" in body["msg"]
    # 拦住之后原配置没被动过
    again = next(item for item in _agents(client, admin_headers)
                 if item["agent_code"] == "PORTRAIT")
    assert again["prompt_code"] == portrait["prompt_code"]


def test_update_rejects_unknown_tool_group(client, admin_headers):
    """工具分组必须是清单里已有的分组，编一个不存在的分组拦下并指回工具中心。"""
    portrait = next(item for item in _agents(client, admin_headers)
                    if item["agent_code"] == "PORTRAIT")
    body = client.put("/agentDefinition/update",
                      json={"agent_id": portrait["id"], "agent_name": portrait["agent_name"],
                            "prompt_code": portrait["prompt_code"], "tool_group": "不存在的分组",
                            "max_tool_call": portrait["max_tool_call"], "sort": portrait["sort"]},
                      headers=admin_headers).json()
    assert body["code"] == "500"
    assert "工具分组" in body["msg"]


def test_supervisor_cannot_be_disabled(client, admin_headers):
    """主管是调度的入口，停用它整次匹配都跑不起来，接口直接拦住。"""
    supervisor = next(item for item in _agents(client, admin_headers)
                      if item["agent_code"] == "SUPERVISOR")
    result = client.post("/agentDefinition/updateEnabled",
                         json={"agent_id": supervisor["id"], "enabled": "否"},
                         headers=admin_headers).json()
    assert result["code"] == "500"
    assert "主管" in result["msg"]
    # 拦住之后主管还是启用状态，没有被改坏
    now = next(item for item in _agents(client, admin_headers)
               if item["agent_code"] == "SUPERVISOR")
    assert now["enabled"] == "是"


def test_enable_blocks_when_prompt_is_unusable(client, admin_headers):
    """绑定的提示词被停用时，启用这个角色会被拦下并指出去哪改。"""
    portrait = next(item for item in _agents(client, admin_headers)
                    if item["agent_code"] == "PORTRAIT")
    page = client.get("/promptTemplate/selectPage",
                      params={"keyword": portrait["prompt_code"], "page_size": 50},
                      headers=admin_headers).json()
    template = page["data"]["list"][0]
    assert template["code"] == portrait["prompt_code"]
    client.post("/promptTemplate/updateEnabled",
                json={"template_id": template["id"], "enabled": "否"}, headers=admin_headers)
    try:
        blocked = client.post("/agentDefinition/updateEnabled",
                              json={"agent_id": portrait["id"], "enabled": "是"},
                              headers=admin_headers).json()
        assert blocked["code"] == "500"
        assert "已停用" in blocked["msg"]
        # 配置问题的清单里也要能看到这一条
        problems = client.get("/agentDefinition/list", headers=admin_headers).json()["data"]["problems"]
        assert any("已停用" in item for item in problems)
    finally:
        client.post("/promptTemplate/updateEnabled",
                    json={"template_id": template["id"], "enabled": "是"}, headers=admin_headers)
    passed = client.post("/agentDefinition/updateEnabled",
                         json={"agent_id": portrait["id"], "enabled": "是"},
                         headers=admin_headers).json()
    assert passed["code"] == "200", passed["msg"]


def test_tool_summary_covers_all_tools(client, admin_headers):
    """工具总览把八个工具和三个分组都算出来，健康检查没有问题项。"""
    body = client.get("/functionTool/summary", headers=admin_headers).json()
    assert body["code"] == "200"
    data = body["data"]
    assert data["total"] >= 8
    assert data["read_only_count"] >= 6
    assert data["write_count"] >= 2
    groups = [item["tool_group"] for item in data["groups"]]
    for name in ("画像", "筛选", "审核"):
        assert name in groups
    assert data["problems"] == []


def test_tool_update_rejects_broken_schema(client, admin_headers):
    """参数 Schema 写坏时保存就被拦下，库里那条工具的 Schema 保持原样。"""
    row = _tool_row(client, admin_headers, "search_members")
    body = client.put("/functionTool/update",
                      json={"id": row["id"], "tool_name": row["tool_name"],
                            "description": row["description"],
                            "input_schema": "{不是 JSON}", "tool_group": row["tool_group"],
                            "max_return_rows": row["max_return_rows"],
                            "enabled": row["enabled"], "sort": row["sort"]},
                      headers=admin_headers).json()
    assert body["code"] == "500"
    assert "JSON" in body["msg"]
    again = _tool_row(client, admin_headers, "search_members")
    assert again["input_schema"] == row["input_schema"]


def test_tool_code_cannot_be_changed(client, admin_headers):
    """工具编码是取实现的依据，改编码等于把这条工具的历史切断，接口拦住不让改。"""
    row = _tool_row(client, admin_headers, "search_members")
    body = client.put("/functionTool/update",
                      json={"id": row["id"], "tool_code": "save_candidates",
                            "tool_name": row["tool_name"], "description": row["description"],
                            "input_schema": row["input_schema"], "tool_group": row["tool_group"],
                            "max_return_rows": row["max_return_rows"],
                            "enabled": row["enabled"], "sort": row["sort"]},
                      headers=admin_headers).json()
    assert body["code"] == "500"
    assert "不能改" in body["msg"]
    assert _tool_row(client, admin_headers, "search_members")["tool_code"] == "search_members"


def test_tool_update_rejects_unknown_implementation(client, admin_headers):
    """新增工具时，编码必须能在程序里找到对应实现。"""
    body = client.post("/functionTool/add",
                       json={"tool_code": "not_a_real_tool", "tool_name": "编的工具",
                             "description": "拿来验证编码校验的",
                             "input_schema": "{\"type\": \"object\", \"properties\": {}}",
                             "tool_group": "画像", "enabled": "否", "sort": 99},
                       headers=admin_headers).json()
    assert body["code"] == "500"
    assert "实现" in body["msg"]


def test_trial_rejects_write_tool(client, admin_headers):
    """写入类工具不能在页面试跑，提示要说清它归谁调。"""
    body = client.post("/functionTool/testCall",
                       json={"tool_code": "save_candidates", "params": {}},
                       headers=admin_headers).json()
    assert body["code"] == "500"
    assert "匹配运行" in body["msg"]


def test_call_log_options(client, admin_headers):
    """日志筛选的下拉里角色、工具、结果三项都要有。"""
    body = client.get("/toolCallLog/options", headers=admin_headers).json()
    assert body["code"] == "200"
    data = body["data"]
    assert data["agents"] and data["tools"]
    assert data["results"] == ["是", "否"]


def test_call_log_detail_of_missing_row(client, admin_headers):
    """查一条已经不存在的日志时，提示要能指回列表刷新。"""
    body = client.get("/toolCallLog/selectOne", params={"log_id": 999999999},
                      headers=admin_headers).json()
    assert body["code"] == "500"
    assert "刷新" in body["msg"]


async def test_disabled_tool_leaves_the_model_hand(db):
    """停用一个工具之后，模型看到的工具清单里真的没有它，调用也会被拒绝。

    这是「真开关」的验法：不是页面上灰一个按钮，而是构建给模型的清单里从此少一条。
    """
    tool = await FunctionTool.get(tool_code="list_interest_tags")
    try:
        await FunctionTool.filter(id=tool.id).update(enabled="否")
        names = [item["function"]["name"] for item in await tools.build_tool_specs("画像")]
        assert "list_interest_tags" not in names
        assert "read_member_detail" in names
        with pytest.raises(CustomException) as error:
            await tools.invoke("list_interest_tags", {}, tools.ToolContext(member_id=1))
        assert "停用" in error.value.message
    finally:
        await FunctionTool.filter(id=tool.id).update(enabled="是")
    # 改回去之后工具又回到清单里
    names = [item["function"]["name"] for item in await tools.build_tool_specs("画像")]
    assert "list_interest_tags" in names


async def test_specs_carry_description_and_schema(db):
    """发给模型的工具清单里，描述和参数都来自注册表。"""
    specs = await tools.build_tool_specs("筛选")
    by_name = {item["function"]["name"]: item["function"] for item in specs}
    assert "search_members" in by_name
    function = by_name["search_members"]
    assert function["description"] and len(function["description"]) > 10
    assert function["parameters"]["type"] == "object"
    assert "gender" in function["parameters"]["properties"]


async def test_trial_call_reads_one_member(db):
    """试跑一个读取类工具：给定租客编号就能把资料读出来。"""
    member = await MemberProfile.create(
        user_id=900000001, nickname=f"校验租客{TEST_MARK}", gender="女", store_id=5,
        self_intro="平时喜欢爬山和看书", interest_tags="爬山,看书", audit_status="已通过")
    try:
        result = await tool_service.test_call("read_member_detail", member.id, {})
        assert result["tool_code"] == "read_member_detail"
        assert result["result"]["member_id"] == member.id
        assert "爬山" in result["result"]["interest_tags"]
        assert result["cost_millis"] >= 0
    finally:
        await MemberProfile.filter(id=member.id).delete()


async def test_call_log_records_success_and_failure(db):
    """成功和失败都要留下调用记录，失败那条的入参和原因也要有。"""
    await ToolCallLog.filter(run_id=TEST_RUN_ID).delete()
    context = tools.ToolContext(run_id=TEST_RUN_ID, agent_code="PORTRAIT", member_id=900000002)
    await tools.invoke("list_interest_tags", {}, context)
    with pytest.raises(CustomException):
        await tools.invoke("read_member_detail", {"member_id": 999999999}, context)
    logs = await ToolCallLog.filter(run_id=TEST_RUN_ID).order_by("id")
    assert len(logs) == 2
    assert logs[0].success == "是" and logs[0].tool_code == "list_interest_tags"
    assert logs[0].row_count and logs[0].row_count > 0
    assert logs[1].success == "否" and logs[1].tool_code == "read_member_detail"
    assert logs[1].error_message
    assert "999999999" in (logs[1].request_params or "")
    await ToolCallLog.filter(run_id=TEST_RUN_ID).delete()


async def test_trial_call_does_not_write_log(db):
    """页面上的试跑不写调用日志：日志是给匹配运行复盘用的。"""
    await ToolCallLog.filter(run_id=TEST_RUN_ID).delete()
    await tool_service.test_call("list_interest_tags", None, {})
    assert await ToolCallLog.filter(run_id=TEST_RUN_ID).count() == 0
