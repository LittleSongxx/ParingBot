"""工具中心业务逻辑。

工具清单存在 function_tool 表里，代码按 tool_code 找实现，所以这一页改的每一条都直接影响
模型能做什么：描述写清楚，模型才知道什么时候该调；参数 Schema 写对，模型才传得对参数；
停用之后，模型手上的工具清单里直接没有它。

四条约束：

1. 编码必须和代码里的实现对得上。能选的编码由代码给出，页面自己编一个没有意义——
   模型点名调用时会取不到工具，整轮执行失败。
2. 已登记的工具不许改编码：模型、日志、步骤记录都按编码找它，改一个编码等于把它的历史切断。
3. 参数 Schema 保存时就校验，必须是 object 形式的 JSON。写坏了要到模型传参时才报错，
   那时候错误信息已经离现场很远。
4. 分组决定这个工具给哪个角色用，取值必须是角色正在用的那几个分组之一。
"""

import json
import re

from tortoise.expressions import Q

from ai import tools
from common.exception_handler import CustomException
from common.result import PageInfo
from common.times import cost_millis, format_datetime, precise_now
from models import AgentDefinition, FunctionTool, MemberProfile, ToolCallLog

YES_NO_OPTIONS = ("是", "否")
# 工具编码的写法：小写字母开头，后面跟小写字母、数字或下划线，例如 search_members
CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,99}$")
MAX_NAME_LENGTH = 255
MAX_DESCRIPTION_LENGTH = 1000
MAX_SCHEMA_LENGTH = 5000
MIN_RETURN_ROWS = 1
MAX_RETURN_ROWS = 200
MAX_SORT = 999
MAX_PAGE_SIZE = 100
# 试跑时最多能挑几个租客出来选
MEMBER_OPTION_LIMIT = 20


def _check_yes_no(value, label: str) -> str:
    text = str(value or "").strip()
    if text not in YES_NO_OPTIONS:
        raise CustomException(f"{label}请从这几项里选：{'、'.join(YES_NO_OPTIONS)}")
    return text


def _check_name(value) -> str:
    text = str(value or "").strip()
    if not text:
        raise CustomException("工具名称不能为空")
    if len(text) > MAX_NAME_LENGTH:
        raise CustomException(f"工具名称最长 {MAX_NAME_LENGTH} 个字符")
    return text


def _check_description(value) -> str:
    text = str(value or "").strip()
    if not text:
        raise CustomException(
            "工具描述不能为空：这段文字会原样发给模型，模型靠它判断什么时候该调这个工具")
    if len(text) > MAX_DESCRIPTION_LENGTH:
        raise CustomException(
            f"工具描述最长 {MAX_DESCRIPTION_LENGTH} 个字符，请把不关键的说明删掉")
    return text


def _check_schema(value) -> str:
    """参数 Schema：必须是 object 形式的 JSON。"""
    text = str(value or "").strip()
    if not text:
        raise CustomException(
            "参数 Schema 不能为空，没有参数也要写成 {\"type\": \"object\", \"properties\": {}}")
    if len(text) > MAX_SCHEMA_LENGTH:
        raise CustomException(f"参数 Schema 最长 {MAX_SCHEMA_LENGTH} 个字符")
    try:
        schema = json.loads(text)
    except (TypeError, ValueError):
        raise CustomException("参数 Schema 要是合法的 JSON，请检查花括号、引号和逗号有没有配对")
    if not isinstance(schema, dict):
        raise CustomException("参数 Schema 要是一个 JSON 对象，以花括号开头")
    if schema.get("type") != "object":
        raise CustomException("参数 Schema 里的 type 要写成 object，模型是按对象形式传参的")
    if not isinstance(schema.get("properties", {}), dict):
        raise CustomException("参数 Schema 里的 properties 要写成对象，每个参数名对应一项")
    return text


def _check_group(value) -> str:
    text = str(value or "").strip()
    if not text:
        raise CustomException("请给这个工具指定一个分组，分组决定它被哪个角色拿去用")
    return text


def _check_return_rows(value) -> int | None:
    """单次返回行数上限。留空表示不截断，由工具自己决定返回多少。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise CustomException("返回行数上限要填整数，留空表示不限制")
    if number < MIN_RETURN_ROWS or number > MAX_RETURN_ROWS:
        raise CustomException(
            f"返回行数上限请填 {MIN_RETURN_ROWS} 到 {MAX_RETURN_ROWS} 之间的整数，留空表示不限制")
    return number


def _check_sort(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise CustomException("排序号要填整数")
    if number < 0 or number > MAX_SORT:
        raise CustomException(f"排序号请填 0 到 {MAX_SORT} 之间的整数")
    return number


def _check_code(value) -> str:
    """工具编码：写法要对，而且必须能在代码的实现表里找到。"""
    text = str(value or "").strip()
    if not CODE_PATTERN.match(text):
        raise CustomException(
            "工具编码用小写字母、数字和下划线，以小写字母开头，例如 search_members")
    if text not in tools.IMPLEMENTATIONS:
        raise CustomException(
            f"代码里没有 {text} 这个工具的对应实现，登记进来模型也调不动。"
            f"当前能登记的编码有：{'、'.join(sorted(tools.IMPLEMENTATIONS))}")
    return text


def tool_dict(tool: FunctionTool) -> dict:
    """手写转字典：挑字段，把「代码里有没有实现」也算出来给页面看。"""
    return {
        "id": tool.id,
        "tool_code": tool.tool_code,
        "tool_name": tool.tool_name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "tool_group": tool.tool_group,
        "max_return_rows": tool.max_return_rows,
        "enabled": tool.enabled,
        "sort": tool.sort,
        # 编码对不上实现是这条工具最要命的故障，页面上直接标出来
        "has_implementation": tool.tool_code in tools.IMPLEMENTATIONS,
        # 读取类工具可以在页面上试跑，写入类只能在匹配运行里调用
        "read_only": tools.is_read_only(tool.tool_code),
        "update_time": format_datetime(tool.update_time),
    }


async def select_page(keyword: str = "", tool_group: str = "", enabled: str = "",
                      page_num: int = 1, page_size: int = 10) -> PageInfo:
    """工具分页查询。关键词同时匹编码和名称。"""
    query = FunctionTool.all()
    if keyword:
        query = query.filter(Q(tool_code__contains=keyword) | Q(tool_name__contains=keyword))
    if tool_group:
        query = query.filter(tool_group=tool_group)
    if enabled:
        query = query.filter(enabled=enabled)
    total = await query.count()
    rows = await query.order_by("sort", "id").offset(
        (page_num - 1) * page_size).limit(page_size)
    return PageInfo(total=total, list=[tool_dict(row) for row in rows])


async def group_options() -> list[dict]:
    """分组下拉：分组由工具自己带出来，页面不自己维护一份。"""
    counts: dict[str, dict] = {}
    for tool in await FunctionTool.all():
        group = tool.tool_group or ""
        row = counts.setdefault(group, {"total": 0, "enabled": 0})
        row["total"] += 1
        if tool.enabled == "是":
            row["enabled"] += 1
    return [
        {"tool_group": group, "tool_total": row["total"], "tool_enabled": row["enabled"]}
        for group, row in sorted(counts.items()) if group
    ]


async def code_options() -> list[dict]:
    """新增工具时能选的编码：代码里有实现、清单里还没有的那些。

    正常情况下八个工具都在表里，这个下拉是空的；它是给「表里少了一条」这种情况留的补救入口。
    """
    registered = {tool.tool_code for tool in await FunctionTool.all()}
    return [
        {"tool_code": code} for code in sorted(tools.IMPLEMENTATIONS)
        if code not in registered
    ]


async def summary() -> dict:
    """工具总览与健康检查。"""
    rows = [tool_dict(tool) for tool in await FunctionTool.all().order_by("sort", "id")]
    problems: list[str] = []
    for item in rows:
        if item["enabled"] == "是" and not item["has_implementation"]:
            problems.append(
                f"工具「{item['tool_name']}」（{item['tool_code']}）是启用状态，"
                f"但代码里找不到对应实现，模型点名调用时会取不到，请先把它停用")
    registered = {item["tool_code"] for item in rows}
    for code in sorted(tools.IMPLEMENTATIONS):
        if code not in registered:
            problems.append(
                f"代码里的 {code} 还没有登记到工具清单里，模型看不到它，"
                f"请新增一条工具并把编码填成 {code}")
    read_only = [item for item in rows if item["read_only"]]
    return {
        "total": len(rows),
        "enabled_count": len([item for item in rows if item["enabled"] == "是"]),
        "read_only_count": len(read_only),
        "write_count": len(rows) - len(read_only),
        "groups": await group_options(),
        "problems": problems,
    }


async def _get(tool_id: int | None) -> FunctionTool:
    tool = await FunctionTool.get_or_none(id=tool_id)
    if tool is None:
        raise CustomException("没有找到这个工具，请刷新页面后重试")
    return tool


async def add(payload: dict) -> None:
    """登记一个已经写好的工具。编码只能从代码里已有实现的那几个里选。"""
    code = _check_code(payload.get("tool_code"))
    if await FunctionTool.get_or_none(tool_code=code):
        raise CustomException(f"清单里已经有 {code} 了，请直接改那一条，不要重复登记")
    await FunctionTool.create(
        tool_code=code,
        tool_name=_check_name(payload.get("tool_name")),
        description=_check_description(payload.get("description")),
        input_schema=_check_schema(payload.get("input_schema")),
        tool_group=_check_group(payload.get("tool_group")),
        max_return_rows=_check_return_rows(payload.get("max_return_rows")),
        enabled=_check_yes_no(payload.get("enabled"), "启用状态"),
        sort=_check_sort(payload.get("sort", 0)),
    )


async def update(tool_id: int | None, payload: dict) -> None:
    """改一个工具。编码不能改，其余字段都能改。"""
    tool = await _get(tool_id)
    code = str(payload.get("tool_code") or "").strip()
    if code and code != tool.tool_code:
        raise CustomException(
            f"工具编码不能改：「{tool.tool_code}」是模型、步骤记录和调用日志找这个工具的依据，"
            f"改了之后它的历史记录就对不上了。要换编码请新增一条工具，再把这一条停用")
    await FunctionTool.filter(id=tool.id).update(
        tool_name=_check_name(payload.get("tool_name")),
        description=_check_description(payload.get("description")),
        input_schema=_check_schema(payload.get("input_schema")),
        tool_group=_check_group(payload.get("tool_group")),
        max_return_rows=_check_return_rows(payload.get("max_return_rows")),
        enabled=_check_yes_no(payload.get("enabled"), "启用状态"),
        sort=_check_sort(payload.get("sort", tool.sort)),
    )


async def update_enabled(tool_id: int | None, enabled: str) -> None:
    """启用或停用工具，这是真开关：停用之后模型手上的工具清单里就没有它了。"""
    tool = await _get(tool_id)
    flag = _check_yes_no(enabled, "启用状态")
    if flag == "是" and tool.tool_code not in tools.IMPLEMENTATIONS:
        raise CustomException(
            f"代码里没有 {tool.tool_code} 这个工具的对应实现，启用之后模型调用它会直接失败。"
            f"请先把这条工具删掉，或者改成已实现的编码")
    await FunctionTool.filter(id=tool.id).update(enabled=flag)


async def remove(tool_id: int | None) -> None:
    """删除一个工具。删掉之后模型再也看不到它，已经产生的调用日志保留。"""
    tool = await _get(tool_id)
    await FunctionTool.filter(id=tool.id).delete()


async def member_options(keyword: str = "") -> list[dict]:
    """试跑时要选一个租客当上下文，这里给一个能搜的下拉。"""
    query = MemberProfile.all()
    if keyword:
        query = query.filter(nickname__contains=keyword)
    rows = await query.order_by("-id").limit(MEMBER_OPTION_LIMIT)
    return [
        {"id": row.id, "nickname": row.nickname, "audit_status": row.audit_status}
        for row in rows
    ]


async def test_call(tool_code: str, member_id: int | None = None,
                    params: dict | None = None) -> dict:
    """在页面上试跑一个读取类工具。

    只让读取类试跑：写入类改的是某一次匹配任务的候选池，离开那次任务去写，
    写出来的数据没有归属，只能当成垃圾清掉。所以写入类的试跑入口在页面上就不给。
    """
    tool = await FunctionTool.get_or_none(tool_code=tool_code)
    if tool is None:
        raise CustomException("没有找到这个工具，请刷新页面后重试")
    if not tools.is_read_only(tool_code):
        raise CustomException(
            f"「{tool.tool_name}」会把结果写进匹配任务的候选池，只能在匹配运行里由角色调用。"
            f"想看它的效果，请等匹配跑起来之后到调用日志里看它的入参和返回")
    context = tools.ToolContext(
        member_id=int(member_id) if member_id else None,
        max_return_rows=tool.max_return_rows,
    )
    started = precise_now()
    result = await tools.invoke(tool_code, params or {}, context)
    return {
        "tool_code": tool_code,
        "tool_name": tool.tool_name,
        "cost_millis": cost_millis(started),
        "result": result,
    }


async def _agent_names() -> dict[str, str]:
    rows = await AgentDefinition.all()
    return {row.agent_code: row.agent_name for row in rows}


def call_log_dict(log: ToolCallLog, names: dict[str, str] | None = None,
                  titles: dict[str, str] | None = None) -> dict:
    """手写转字典：把角色编码和工具编码翻成名字，时间格式化。"""
    return {
        "id": log.id,
        "run_id": log.run_id,
        "agent_code": log.agent_code,
        "agent_name": (names or {}).get(log.agent_code or "") or log.agent_code,
        "tool_code": log.tool_code,
        "tool_name": (titles or {}).get(log.tool_code) or log.tool_code,
        "row_count": log.row_count,
        "success": log.success,
        "error_message": log.error_message,
        "cost_millis": log.cost_millis,
        "request_params": log.request_params,
        "response_result": log.response_result,
        "create_time": format_datetime(log.create_time),
    }


async def call_log_page(run_id: int | None = None, agent_code: str = "",
                        tool_code: str = "", success: str = "",
                        page_num: int = 1, page_size: int = 10) -> PageInfo:
    """工具调用日志分页查询。

    默认按时间倒序：看日志的人基本都是想知道「刚才那次调用发生了什么」。
    """
    query = ToolCallLog.all()
    if run_id:
        query = query.filter(run_id=int(run_id))
    if agent_code:
        query = query.filter(agent_code=agent_code)
    if tool_code:
        query = query.filter(tool_code=tool_code)
    if success:
        query = query.filter(success=_check_yes_no(success, "调用结果"))
    if page_size > MAX_PAGE_SIZE:
        page_size = MAX_PAGE_SIZE
    total = await query.count()
    rows = await query.order_by("-id").offset(
        (page_num - 1) * page_size).limit(page_size)
    names = await _agent_names()
    titles = {tool.tool_code: tool.tool_name for tool in await FunctionTool.all()}
    return PageInfo(total=total, list=[
        call_log_dict(row, names, titles) for row in rows])


async def call_log_detail(log_id: int | None) -> dict:
    """一条调用日志的完整入参与返回，页面上放在弹窗里看。"""
    log = await ToolCallLog.get_or_none(id=log_id)
    if log is None:
        raise CustomException("这条调用日志已经不在了，请刷新列表后重试")
    names = await _agent_names()
    titles = {tool.tool_code: tool.tool_name for tool in await FunctionTool.all()}
    return call_log_dict(log, names, titles)


async def remove_log(log_id: int | None) -> None:
    """删一条调用日志。日志只是记录，删掉不影响任何业务数据。"""
    log = await ToolCallLog.get_or_none(id=log_id)
    if log is None:
        raise CustomException("这条调用日志已经不在了，请刷新列表后重试")
    await ToolCallLog.filter(id=log.id).delete()


async def remove_logs(log_ids: list | None) -> int:
    """批量删调用日志，返回删掉几条。"""
    ids = [int(item) for item in (log_ids or []) if str(item).strip()]
    if not ids:
        raise CustomException("请先勾选要删除的调用日志")
    deleted = await ToolCallLog.filter(id__in=ids).count()
    await ToolCallLog.filter(id__in=ids).delete()
    return deleted


async def log_options() -> dict:
    """日志筛选用的下拉：角色、工具、调用结果。"""
    names = await _agent_names()
    tools_rows = await FunctionTool.all().order_by("sort", "id")
    return {
        "agents": [{"agent_code": code, "agent_name": name} for code, name in names.items()],
        "tools": [{"tool_code": row.tool_code, "tool_name": row.tool_name} for row in tools_rows],
        "results": list(YES_NO_OPTIONS),
    }
