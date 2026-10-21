"""子 Agent 定义业务逻辑。

四个角色在库里各占一行，一行就是「用哪套人格提示词 + 能调哪几个工具 + 单次能调几次工具」。
四个角色跑的是同一套执行器，所以这一页改的是执行器的输入，不是四份代码的参数。

三条规则写在这里：

1. 角色编码是执行器取角色的键，四个编码由执行器认，多一个不会被执行、少一个那条路就断了，
   所以这一页不支持增删角色，只支持改配置和开关。
2. 主管是调度的入口，它一停整次匹配就跑不起来，所以它不能停用。
3. 角色绑定的提示词要过「存在 / 启用 / 内容非空」三项，工具分组下至少要有一个启用工具。
   这两条不满足，执行到那一步才会报错，现场离问题也远了，所以启用角色时就拦下并说清去哪改。
"""

from common.exception_handler import CustomException
from common.times import format_datetime
from models import AgentDefinition, FunctionTool, PromptTemplate
from service import config_service

# 执行器认识的四个角色编码
AGENT_CODES = ("SUPERVISOR", "PORTRAIT", "SCREENER", "AUDITOR")
# 主管是调度的入口，它不停用
SUPERVISOR = "SUPERVISOR"
YES_NO_OPTIONS = ("是", "否")
# 单角色工具调用上限的填写区间
MIN_TOOL_CALL = 1
MAX_TOOL_CALL = 200
MAX_NAME_LENGTH = 100
MAX_SORT = 999
# 角色单次工具调用上限留空时取这个系统参数
MAX_TOOL_CALL_KEY = "AGENT_MAX_TOOL_CALL"
MAX_TOOL_CALL_DEFAULT = 30


def _check_yes_no(value, label: str) -> str:
    text = str(value or "").strip()
    if text not in YES_NO_OPTIONS:
        raise CustomException(f"{label}请从这几项里选：{'、'.join(YES_NO_OPTIONS)}")
    return text


def _check_sort(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise CustomException("排序号要填整数")
    if number < 0 or number > MAX_SORT:
        raise CustomException(f"排序号请填 0 到 {MAX_SORT} 之间的整数")
    return number


def _check_max_tool_call(value) -> int | None:
    """单角色工具调用上限。留空表示跟随系统参数里的统一上限。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise CustomException("单次工具调用上限要填整数，留空表示跟随系统参数")
    if number < MIN_TOOL_CALL or number > MAX_TOOL_CALL:
        raise CustomException(
            f"单次工具调用上限请填 {MIN_TOOL_CALL} 到 {MAX_TOOL_CALL} 之间的整数，留空表示跟随系统参数")
    return number


def _check_name(value) -> str:
    text = str(value or "").strip()
    if not text:
        raise CustomException("角色名称不能为空")
    if len(text) > MAX_NAME_LENGTH:
        raise CustomException(f"角色名称最长 {MAX_NAME_LENGTH} 个字符")
    return text


def prompt_state(prompt: PromptTemplate | None) -> str:
    """一条提示词模板能不能用：存在 / 启用 / 内容非空，三项都要过。"""
    if prompt is None:
        return "没有这条模板"
    if prompt.enabled != "是":
        return "已停用"
    if not (prompt.content or "").strip():
        return "内容为空"
    return "正常"


async def _default_max_tool_call() -> int:
    """系统参数里的统一上限，角色自己没填时按它算。"""
    raw = await config_service.get_value(MAX_TOOL_CALL_KEY, str(MAX_TOOL_CALL_DEFAULT))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return MAX_TOOL_CALL_DEFAULT
    return value if value > 0 else MAX_TOOL_CALL_DEFAULT


async def _tool_counts() -> dict[str, dict]:
    """按工具分组数出每个分组下有几个工具、其中几个是启用状态。"""
    counts: dict[str, dict] = {}
    for tool in await FunctionTool.all():
        group = tool.tool_group or ""
        row = counts.setdefault(group, {"total": 0, "enabled": 0})
        row["total"] += 1
        if tool.enabled == "是":
            row["enabled"] += 1
    return counts


async def _prompt_map() -> dict[str, PromptTemplate]:
    prompts = await PromptTemplate.all()
    return {prompt.code: prompt for prompt in prompts}


def agent_dict(agent: AgentDefinition, prompt: PromptTemplate | None,
               tool_count: dict | None, default_max: int) -> dict:
    """手写转字典：挑字段、把提示词和工具池的情况摊平，页面直接用。"""
    state = prompt_state(prompt)
    counts = tool_count or {"total": 0, "enabled": 0}
    return {
        "id": agent.id,
        "agent_code": agent.agent_code,
        "agent_name": agent.agent_name,
        "prompt_code": agent.prompt_code,
        "prompt_name": prompt.name if prompt else None,
        "prompt_state": state,
        # 主管不调工具，它的工具分组本来就是空的，不参与「有没有工具」的检查
        "is_supervisor": agent.agent_code == SUPERVISOR,
        "tool_group": agent.tool_group,
        "tool_total": counts["total"],
        "tool_enabled": counts["enabled"],
        "max_tool_call": agent.max_tool_call,
        # 页面上要能看出「这个角色一次最多调几次工具」到底是自己填的还是跟随系统参数
        "effective_max_tool_call": agent.max_tool_call or default_max,
        "max_tool_call_source": "角色单独设置" if agent.max_tool_call else "跟随系统参数",
        "enabled": agent.enabled,
        "sort": agent.sort,
        "update_time": format_datetime(agent.update_time),
    }


async def _problems(agents: list[dict]) -> list[str]:
    """启用中的角色各自的配置问题，页面上摆在最前面。"""
    issues: list[str] = []
    for item in agents:
        if item["enabled"] != "是":
            continue
        if item["prompt_state"] != "正常":
            issues.append(
                f"{item['agent_name']}：绑定的提示词「{item['prompt_name'] or item['prompt_code']}」"
                f"当前是「{item['prompt_state']}」，执行时会取不到提示词，"
                f"请到「Prompt模板」里把它改成启用且内容非空")
        if not item["is_supervisor"] and not item["tool_enabled"]:
            issues.append(
                f"{item['agent_name']}：工具分组「{item['tool_group'] or '未设置'}」下没有启用的工具，"
                f"它接不到任何工具就干不了活，请到「工具中心」至少启用一个")
    return issues


async def list_all() -> dict:
    """四个角色的完整配置，外加一份问题清单。"""
    agents = await AgentDefinition.all().order_by("sort", "id")
    prompts = await _prompt_map()
    counts = await _tool_counts()
    default_max = await _default_max_tool_call()
    rows = [
        agent_dict(agent, prompts.get(agent.prompt_code or ""),
                   counts.get(agent.tool_group or ""), default_max)
        for agent in agents
    ]
    return {
        "total": len(rows),
        "enabled_count": len([item for item in rows if item["enabled"] == "是"]),
        "default_max_tool_call": default_max,
        "problems": await _problems(rows),
        "list": rows,
    }


async def _get(agent_id: int | None) -> AgentDefinition:
    agent = await AgentDefinition.get_or_none(id=agent_id)
    if agent is None:
        raise CustomException("没有找到这个 Agent 角色，请刷新页面后重试")
    return agent


async def group_options() -> list[dict]:
    """工具分组下拉：分组来自工具注册表，页面不自己维护一份。"""
    counts = await _tool_counts()
    return [
        {"tool_group": group, "tool_total": row["total"], "tool_enabled": row["enabled"]}
        for group, row in sorted(counts.items()) if group
    ]


async def prompt_options() -> list[dict]:
    """提示词下拉：只列还能用的模板，避免绑一个取不到的。"""
    prompts = await PromptTemplate.filter(enabled="是").order_by("id")
    return [
        {"code": prompt.code, "name": prompt.name, "scene": prompt.scene}
        for prompt in prompts if (prompt.content or "").strip()
    ]


async def update(agent_id: int | None, payload: dict) -> None:
    """改一个角色的配置。

    提示词只校验「这条模板存在」：选了停用或空内容的模板先存下来也行，
    页面上会把状态标红，启用这个角色时会再拦一次——那时候才真的执行得到。
    但编码写错等于这个角色直接失联，必须在保存时就拦。
    """
    agent = await _get(agent_id)
    prompt_code = str(payload.get("prompt_code") or "").strip()
    if not prompt_code:
        raise CustomException("请给这个角色选一套提示词模板")
    prompt = await PromptTemplate.get_or_none(code=prompt_code)
    if prompt is None:
        raise CustomException(
            f"没有编码为 {prompt_code} 的提示词模板，请到「Prompt模板」里确认它的编码，"
            f"或者换成已有的一条")
    if agent.agent_code == SUPERVISOR:
        # 主管只做调度不调工具，给它挂分组会让页面上看起来「主管有工具」，
        # 实际执行器并不会给它构建工具清单
        group = None
    else:
        group = str(payload.get("tool_group") or "").strip() or None
        if group is None:
            raise CustomException(
                f"{agent.agent_name}要做的事都要靠工具完成，请给它指定一个工具分组")
        counts = await _tool_counts()
        if group not in counts:
            raise CustomException(
                f"没有「{group}」这个工具分组，请到「工具中心」确认分组名，"
                f"或者从下拉里选已有分组")
    await AgentDefinition.filter(id=agent.id).update(
        agent_name=_check_name(payload.get("agent_name")),
        prompt_code=prompt_code,
        tool_group=group,
        max_tool_call=_check_max_tool_call(payload.get("max_tool_call")),
        sort=_check_sort(payload.get("sort", agent.sort)),
    )


async def update_enabled(agent_id: int | None, enabled: str) -> None:
    """启用或停用角色。

    这是真开关：停用之后主管派不了它。所以启用之前先把两件事查清——
    提示词能不能取到、手上有没有启用的工具，缺一样这个角色起来也是白跑一轮。
    """
    agent = await _get(agent_id)
    flag = _check_yes_no(enabled, "启用状态")
    if agent.agent_code == SUPERVISOR and flag != "是":
        raise CustomException(
            "主管是调度的入口，停用它之后整次匹配都跑不起来。"
            "如果只是想暂停匹配，请从匹配任务那一侧处理")
    if flag == "是":
        prompt = await PromptTemplate.get_or_none(code=agent.prompt_code or "")
        state = prompt_state(prompt)
        if state != "正常":
            raise CustomException(
                f"{agent.agent_name}绑定的提示词当前是「{state}」，启用之前请先到「Prompt模板」"
                f"把它改成启用且内容非空，或者换一条能用的")
        if agent.agent_code != SUPERVISOR:
            counts = await _tool_counts()
            row = counts.get(agent.tool_group or "", {"total": 0, "enabled": 0})
            if not row["enabled"]:
                raise CustomException(
                    f"{agent.agent_name}的工具分组「{agent.tool_group or '未设置'}」下没有启用的工具，"
                    f"请先到「工具中心」启用至少一个")
    await AgentDefinition.filter(id=agent.id).update(enabled=flag)
