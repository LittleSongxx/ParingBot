"""工具注册表背后的八个实现与统一调用入口。

工具清单不是写死在代码里的：哪个工具给哪个角色用、描述怎么写、参数长什么样、
开不开，全部存在 function_tool 表里，管理员在工具中心就能改。代码这边只出一份实现，
用 tool_code 去分发表里找对应的函数，所以表里的编码必须和分发表里的函数名一字不差——
对不上的话，模型点名要调用这个工具时会取不到，整轮执行直接失败。

运行期信息（哪次运行、哪个角色、哪个任务、哪个租客）由执行器塞进 ToolContext，
不写进工具的参数里：这些是编排的事，模型不需要也不该去猜。

每次调用都在入口处统一做三件事：写一条 tool_call_log、数出返回条数、把异常翻译成人话。
成功失败都记——只记成功的话，出错的那几次调用在页面上看不见，复盘时只能靠猜。
"""

import json
import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Callable

from tortoise.transactions import in_transaction

from common.exception_handler import CustomException
from common.redact import redact_text
from common.text import split_values
from common.times import cost_millis, format_datetime, now, precise_now
from models import (AgentStep, FunctionTool, InterestTag, MatchCandidate, MemberMoment,
                    MemberPortrait, MemberProfile, RoommatePreference, ToolCallLog)
from service import config_service, member_service, preference_service

# 入参与返回存进日志时的长度上限。一次调用可能返回几十行，全量存进去日志表会被撑爆，
# 页面上也读不动；截断之后至少还看得到这次调用大致拿了什么、回了什么
LOG_TEXT_LIMIT = 20000
# 失败原因写库前的截断长度，和 tool_call_log.error_message 的列长一致
ERROR_LIMIT = 500
# 读取类工具不改业务数据，可以在工具中心试跑；写入类只能在匹配运行里由角色调用
READ_ONLY_TOOLS = (
    "read_member_detail",
    "read_member_moments",
    "list_interest_tags",
    "read_roommate_preference",
    "search_members",
    "read_candidate_preference",
)
# 审核官能给出的两种结论
AUDIT_PASS = "通过"
AUDIT_REJECT = "否决"
AUDIT_STATUSES = (AUDIT_PASS, AUDIT_REJECT)
# 三种否决原因。前两种直接换人，第三种要补画像后重新筛选
REJECT_CODES = ("MISMATCH_HARD", "PREFERENCE_CONFLICT", "PORTRAIT_INSUFFICIENT")
# 判「画像不够、判断不了」时必须点名缺哪个维度，这里按维度名核对理由里有没有提到
PORTRAIT_DIMENSIONS = ("年龄", "预算", "整洁", "门店", "作息", "租期", "宠物", "吸烟", "生活方式", "性格", "兴趣")
# 读动态时默认取几条
DEFAULT_MOMENT_LIMIT = 20
# 一次往候选池写多少条的兜底上限，实际以系统参数里的配置为准
POOL_LIMIT_KEY = "POOL_CANDIDATE_LIMIT"
POOL_LIMIT_DEFAULT = 30

# 放宽规则：代码定边界，模型在边界内自己挑这轮动哪一个维度。
# step 是单次能放宽的最大幅度，total 是同一个维度累计能放宽的最大幅度。
# 维度名和合住偏好里的叫法对齐，alias 是更顺口的说法。
RELAX_RULES = (
    {"name": "年龄", "alias": (), "step": 2, "total": 6, "unit": "岁"},
    {"name": "预算", "alias": ("房租",), "step": 200, "total": 600, "unit": "元"},
    {"name": "门店", "alias": ("片区",), "step": 1, "total": 2, "unit": "级"},
    {"name": "整洁度", "alias": (), "step": 1, "total": 2, "unit": "档"},
    {"name": "租期", "alias": (), "step": 1, "total": 2, "unit": "档"},
    {"name": "作息", "alias": (), "step": 1, "total": 1, "unit": "级"},
)
# 放宽次数上限的参数编码，和系统参数里那一项一致
RELAX_LIMIT_KEY = "SCREENER_MAX_RELAX"
RELAX_LIMIT_DEFAULT = 3
# 可放宽的维度清单与写法示例，模型写歪了按这两句回正。
# 示例按规则表拼出来，规则改了示例跟着改，不会对不上
RELAX_DIMENSION_HINT = "、".join(item["name"] for item in RELAX_RULES)
# 区间类维度，放宽时要写清动的是上限还是下限
RANGE_DIMENSIONS = ("年龄", "预算")


def _rule_example(rule: dict) -> str:
    """一个维度的放宽说明示例：年龄预算要写上限还是下限，其余维度写档位。"""
    if rule["name"] in RANGE_DIMENSIONS:
        return f"「{rule['name']}上限+{rule['step']}」"
    return f"「{rule['name']}+{rule['step']}{rule['unit']}」"


RELAX_FORMAT_HINT = "、".join(_rule_example(rule) for rule in RELAX_RULES)


@dataclass
class ToolContext:
    """一次工具调用所处的运行环境。

    由执行器构造，工具实现只读不改。试跑时只有 member_id 有值，
    所以试跑能跑读取类工具，写入类会因为拿不到任务编号而明确拒绝。
    """

    # 所属运行，为空表示这不是一次匹配运行里的调用（页面上的试跑）
    run_id: int | None = None
    # 发起调用的角色编码
    agent_code: str | None = None
    # 所属匹配任务
    task_id: int | None = None
    # 本次任务要服务的租客，也就是申请方
    member_id: int | None = None
    # 当前调度轮次，审核结论要记在第几轮审的
    round_no: int = 0
    # 注册表里写的单次返回行数上限
    max_return_rows: int | None = None


def _json_text(value: Any) -> str:
    """把入参或返回转成存日志的文本：先脱敏、再截断。

    工具返回里可能带租客原文（自我介绍、动态、手机号等），写进 tool_call_log 之前
    统一把手机号/邮箱/身份证号打码；排查问题时仍看得出这里原来有个值。
    """
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    text = redact_text(text) or ""
    if len(text) <= LOG_TEXT_LIMIT:
        return text
    return text[:LOG_TEXT_LIMIT] + "……（内容过长已截断）"


def _row_count(result: Any) -> int | None:
    """从返回里数出条数，写进日志的 row_count 列。

    返回结构里带 returned 的以它为准，其次是 total、written 这类计数，
    最后才退回列表长度。都是普通字典和列表，不需要为这一列改返回结构。
    """
    if isinstance(result, dict):
        for key in ("returned", "written", "total", "count"):
            value = result.get(key)
            if isinstance(value, int):
                return value
    if isinstance(result, list):
        return len(result)
    return None


def _truncate(message: str) -> str:
    """错误原因写库前先脱敏再截断，列长 500。"""
    text = redact_text(str(message or "").strip()) or ""
    text = text or "工具执行失败"
    return text if len(text) <= ERROR_LIMIT else text[:ERROR_LIMIT]


def _limit_of(raw, default: int, ceiling: int | None) -> int:
    """算这一次取多少条：工具给的默认值和注册表里的上限，取小的那个。"""
    try:
        value = int(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        value = default
    if value < 1:
        value = default
    if ceiling and ceiling > 0:
        value = min(value, ceiling)
    return value


def _check_int(raw, low: int, high: int, label: str) -> int:
    """把入参里的整数校验到区间内，越界时提示写清该填什么。"""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise CustomException(f"{label}要填整数")
    if value < low or value > high:
        raise CustomException(f"{label}请填 {low} 到 {high} 之间的整数")
    return value


def _effective_round(context: ToolContext, found_round) -> int:
    """这一轮是第几轮筛出来的：真实运行以调度轮次为准，模型传的只在没有上下文时兜底。

    模型自己填 found_round 时，一次执行里可以连填 1、2、3 把放宽轮次一次吃光，
    统计口径也会和调度轮次脱钩；运行上下文里带了轮次就不再采信模型的值。
    """
    if context.round_no:
        return int(context.round_no)
    return _check_int(found_round, 1, 999, "第几轮筛出来的")


def _member_target(context: ToolContext, member_id: int | None) -> int:
    """确定这次要读哪个租客：参数里带了就用参数，没带就用运行上下文里的申请方。"""
    target = member_id or context.member_id
    if not target:
        raise CustomException("这次调用没有指明是哪个租客，请把租客编号一起传进来")
    return int(target)


def _safe_date(year: int, month: int, day: int) -> date:
    """构造日期，2 月 29 日这种在平年里不存在的日期退回 28 日。"""
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, month, 28)


def _birth_bounds(age_min: int | None, age_max: int | None) -> tuple[date | None, date | None]:
    """把年龄区间换算成出生日期区间。

    档案表里存的是出生日期，年龄是现算的，按年龄筛选要先折成日期范围。
    上限那一侧要减一岁：年龄等于上限的人也满足条件，不能被他正好卡掉。
    """
    today = now().date()
    low = _safe_date(today.year - age_max - 1, today.month, today.day) if age_max else None
    high = _safe_date(today.year - age_min, today.month, today.day) if age_min else None
    return low, high


async def _write_log(context: ToolContext, tool_code: str, params: dict, result: Any,
                     success: bool, error_message: str | None, started) -> None:
    """写一条工具调用日志。

    页面上的试跑没有运行编号，不写日志：日志是给匹配运行复盘用的，
    混进试跑记录之后，按运行筛出来的链路会多出几条对不上的调用。
    """
    if not context.run_id:
        return
    await ToolCallLog.create(
        run_id=context.run_id,
        agent_code=context.agent_code,
        tool_code=tool_code,
        request_params=_json_text(params),
        response_result=_json_text(result) if result is not None else None,
        row_count=_row_count(result),
        success="是" if success else "否",
        error_message=_truncate(error_message) if error_message else None,
        cost_millis=cost_millis(started),
        create_time=now(),
    )


def _parse_schema(tool: FunctionTool) -> dict:
    """把注册表里的参数 Schema 文本解析成对象。

    写坏了的 Schema 要到模型传参时才会炸，那时候错误信息已经离现场很远，
    所以这里直接拦下来，并说清是哪条工具、该写成什么样。
    """
    text = (tool.input_schema or "").strip()
    if not text:
        return {"type": "object", "properties": {}}
    try:
        schema = json.loads(text)
    except (TypeError, ValueError):
        raise CustomException(
            f"工具「{tool.tool_name}」的参数 Schema 不是合法的 JSON，"
            f"请到工具中心把它改成对象形式的 JSON")
    if not isinstance(schema, dict):
        raise CustomException(
            f"工具「{tool.tool_name}」的参数 Schema 要是一个 JSON 对象，"
            f"请到工具中心改成以花括号开头的那种写法")
    return schema


async def build_tool_specs(tool_group: str) -> list[dict]:
    """按分组取启用中的工具，拼成发给模型看的工具清单。

    描述和参数都来自注册表：改了表里的描述，模型下一次调用看到的就是新的。
    停用的工具在这里被过滤掉，模型根本看不到它，这就是「真开关」——
    不是页面上灰一个按钮，而是模型手上的工具清单里真的没有了。
    """
    tools = await FunctionTool.filter(tool_group=tool_group, enabled="是").order_by("sort", "id")
    specs: list[dict] = []
    for tool in tools:
        if tool.tool_code not in IMPLEMENTATIONS:
            raise CustomException(
                f"工具「{tool.tool_name}」（{tool.tool_code}）在注册表里是启用状态，"
                f"但代码里没有对应的实现，模型点名调用时会取不到。"
                f"请到工具中心把它停用，或者把编码改成已实现的那个")
        specs.append({
            "type": "function",
            "function": {
                "name": tool.tool_code,
                "description": tool.description or tool.tool_name,
                "parameters": _parse_schema(tool),
            },
        })
    return specs


def is_read_only(tool_code: str) -> bool:
    """这个工具会不会改业务数据。"""
    return tool_code in READ_ONLY_TOOLS


async def invoke(tool_code: str, params: dict | None = None,
                 context: ToolContext | None = None) -> Any:
    """统一调用入口：查注册表、找实现、执行、记日志。

    所有工具调用都从这里进，一处管住三件事：停用的工具调不到、
    每次调用都留痕、失败原因一定被翻译成人话再往上抛。
    注册表里这条工具的单次返回行数上限也在这一层塞进上下文，
    读取类工具按各自的上限截断返回，模型换个工具调用时上限跟着换。
    """
    context = context or ToolContext()
    tool = await FunctionTool.get_or_none(tool_code=tool_code)
    if tool is None:
        raise CustomException(f"没有登记过工具 {tool_code}，请到工具中心确认这条工具还在不在")
    if tool.enabled != "是":
        raise CustomException(
            f"工具「{tool.tool_name}」已经被停用，模型用不了它；"
            f"要恢复请到工具中心把它启用")
    # 注册表里这条工具的单次返回行数上限作为本次调用的上下文；
    # 注册表没填时保留调用方传进来的值，不同工具的上限不会互相串
    context = replace(context, max_return_rows=tool.max_return_rows or context.max_return_rows)
    implementation = IMPLEMENTATIONS.get(tool_code)
    if implementation is None:
        raise CustomException(
            f"工具「{tool.tool_name}」还没有对应实现，请到工具中心核对它的编码")
    arguments = dict(params or {})
    started = precise_now()
    try:
        result = await implementation(context, **arguments)
    except CustomException as exc:
        await _write_log(context, tool_code, arguments, None, False, exc.message, started)
        raise
    except TypeError:
        # 传进来的参数名和工具实现接不住，属于工具与模型之间的约定对不上。
        # 日志里记的是能照做的一句话，不留 Python 的英文报错原文
        reason = (f"调用工具「{tool.tool_name}」时参数对不上，"
                  f"请到工具中心核对这个工具的编码与参数说明")
        await _write_log(context, tool_code, arguments, None, False, reason, started)
        raise CustomException(
            f"调用工具「{tool.tool_name}」时参数对不上，请检查参数名和取值后重试")
    except Exception:
        await _write_log(context, tool_code, arguments, None, False,
                         f"执行出错：{tool.tool_name}", started)
        raise CustomException(
            f"工具「{tool.tool_name}」执行出错，请稍后重试；"
            f"如果一直失败，请把这次操作告诉管理员")
    await _write_log(context, tool_code, arguments, result, True, None, started)
    return result


async def read_member_detail(context: ToolContext, member_id: int | None = None) -> dict:
    """读租客档案与兴趣标签。

    这是提取画像的起点：没有这份档案，画像师连租客的作息和预算都不知道。
    """
    target = _member_target(context, member_id)
    member = await MemberProfile.get_or_none(id=target)
    if member is None:
        raise CustomException("这位租客还没有填档案，请先让租客补全档案再来提取画像")
    return {
        "member_id": member.id,
        "nickname": member.nickname,
        "gender": member.gender,
        # 年龄不落库，按出生日期现算，档案放久了也不会出现库里和实际差一岁
        "age": member_service.calc_age(member.birth_date),
        "rent_budget": member.rent_budget,
        "tidiness": member.tidiness,
        "occupation": member.occupation,
        "lease_term": member.lease_term,
        "store": member_service.store_name(member.store_id),
        "area": member_service.area_name(member.store_id),
        "schedule_type": member.schedule_type,
        "has_pet": member.has_pet,
        "smoking": member.smoking,
        "self_intro": member.self_intro,
        "roommate_expectation": member.roommate_expectation,
        "interest_tags": split_values(member.interest_tags),
        "audit_status": member.audit_status,
        "returned": 1,
    }


async def read_member_moments(context: ToolContext, member_id: int | None = None,
                            limit: int | None = None) -> dict:
    """读租客发布的动态原文，按发布时间倒序。

    动态是画像最重要的依据来源：性格和生活习惯这些没法从档案字段里读出来的东西，
    基本都藏在他自己写的动态里。原文一起返回，标签才有地方注明依据。
    """
    target = _member_target(context, member_id)
    size = _limit_of(limit, DEFAULT_MOMENT_LIMIT, context.max_return_rows)
    rows = await MemberMoment.filter(
        member_id=target, visible="公开").order_by("-publish_time", "-id").limit(size)
    return {
        "member_id": target,
        "returned": len(rows),
        "moments": [
            {
                "moment_id": row.id,
                "content": row.content,
                "publish_time": format_datetime(row.publish_time),
            }
            for row in rows
        ],
    }


async def list_interest_tags(context: ToolContext, category: str | None = None) -> dict:
    """读兴趣标签词表。

    词表是把兴趣标签统一起来的依据：同样喜欢跑步，有人写「跑步」有人写「晨跑」，
    各写各的就没法算重合度。所以打标签只能用词表里的词。
    """
    query = InterestTag.filter(enabled="是")
    if category:
        query = query.filter(category=str(category).strip())
    rows = await query.order_by("sort", "id")
    return {
        "total": len(rows),
        "returned": len(rows),
        "tags": [{"tag_name": row.tag_name, "category": row.category} for row in rows],
    }


async def read_roommate_preference(context: ToolContext) -> dict:
    """读申请方的合住偏好，每个维度带上「必须」或「加分」的标注。

    读谁不由模型说了算：申请方就是这次运行的发起人，编号运行上下文里已经有了。
    这个工具早先收一个可选的租客编号，昵称取得像数字时（比如「2222」），
    模型会把昵称当编号传进来，那边读不到偏好，整轮筛选就一个人都筛不出来。

    标注是这个工具的重点：标为「必须」的维度是硬门槛，候选不满足就不能要；
    标为「加分」的在候选不够时可以放宽。不带标注，筛选官就分不清哪些能让。
    """
    target = context.member_id
    if not target:
        raise CustomException("这次运行没有带上是哪位租客，请从租客端重新发起一次")
    preference = await RoommatePreference.get_or_none(member_id=target)
    if preference is None:
        raise CustomException("这位租客还没有填合住偏好，请先让租客把偏好填好再筛候选")
    return {
        "member_id": target,
        "age": {"range": [preference.age_min, preference.age_max],
                "required": preference.age_required},
        "budget": {"range": [preference.budget_min, preference.budget_max],
                   "required": preference.budget_required},
        "tidiness": {"min": preference.tidiness_min, "required": preference.tidiness_required},
        "store": {"scope": preference.store_scope, "required": preference.store_required},
        "schedule": {"accept": split_values(preference.schedule_accept),
                     "required": preference.schedule_required},
        "lease": {"min": preference.lease_min, "required": preference.lease_required},
        "pet": {"accept": preference.pet_accept, "required": preference.pet_required},
        "returned": 1,
    }


def _candidate_dict(member: MemberProfile, wanted_tags: list[str]) -> dict:
    """候选租客在工具返回里的样子：够筛选官判断就行，不给整行。"""
    tags = split_values(member.interest_tags)
    return {
        "member_id": member.id,
        "nickname": member.nickname,
        "gender": member.gender,
        "age": member_service.calc_age(member.birth_date),
        "rent_budget": member.rent_budget,
        "tidiness": member.tidiness,
        "occupation": member.occupation,
        "lease_term": member.lease_term,
        "store": member_service.store_name(member.store_id),
        "schedule_type": member.schedule_type,
        "has_pet": member.has_pet,
        "interest_tags": tags,
        # 和筛选条件里点名的兴趣对上的那几个词，模型不用自己再做一遍比对
        "matched_tags": [tag for tag in tags if tag in wanted_tags],
    }


async def search_members(context: ToolContext, gender: str | None = None,
                         age_min: int | None = None, age_max: int | None = None,
                         budget_min: int | None = None, budget_max: int | None = None,
                         tidiness_min: str | None = None, store_scope: str | None = None,
                         store_id: int | None = None, schedule_accept: str | None = None,
                         lease_min: str | None = None,
                         interest_tags: list[str] | None = None) -> dict:
    """按条件检索候选租客。

    只返回档案已通过审核、并且不是申请方本人的租客：没通过审核的档案不能推荐给别人，
    本人出现在自己的候选里更是直接错。没传的条件表示不限制。

    total 是符合全部条件的总人数，returned 是这次实际返回几条，hasMore 说明还有没有。
    返回条数按注册表里写的上限截断，避免一次把上下文塞满。
    """
    query = MemberProfile.filter(audit_status="已通过", enabled="是")
    if context.member_id:
        query = query.exclude(id=context.member_id)
        # 合租只找同性：性别以申请方档案为准，不靠模型自己传。
        # 模型传了别的性别就拒绝，原因回到它手上；没传就按申请方的性别补上
        applicant = await MemberProfile.get_or_none(id=context.member_id)
        if applicant is not None and applicant.gender:
            if gender and gender != applicant.gender:
                raise CustomException(
                    f"合租只找同性，申请方是{applicant.gender}，"
                    f"gender 请传「{applicant.gender}」或者不传")
            gender = applicant.gender
    if gender:
        if gender not in member_service.GENDERS:
            raise CustomException(f"性别请从这几项里选：{'、'.join(member_service.GENDERS)}")
        query = query.filter(gender=gender)
    if budget_min is not None:
        query = query.filter(rent_budget__gte=_check_int(
            budget_min, member_service.MIN_BUDGET, member_service.MAX_BUDGET, "预算下限"))
    if budget_max is not None:
        query = query.filter(rent_budget__lte=_check_int(
            budget_max, member_service.MIN_BUDGET, member_service.MAX_BUDGET, "预算上限"))
    if age_min is not None and age_max is not None and int(age_min) > int(age_max):
        raise CustomException("年龄的下限不能大于上限")
    low, high = _birth_bounds(
        _check_int(age_min, member_service.MIN_AGE, member_service.MAX_AGE, "年龄下限")
        if age_min is not None else None,
        _check_int(age_max, member_service.MIN_AGE, member_service.MAX_AGE, "年龄上限")
        if age_max is not None else None)
    if low:
        query = query.filter(birth_date__gt=low)
    if high:
        query = query.filter(birth_date__lte=high)
    if tidiness_min:
        if tidiness_min not in member_service.TIDINESS_LEVELS:
            raise CustomException(
                f"最低整洁度请从这几项里选：{'、'.join(member_service.TIDINESS_LEVELS)}")
        allowed = member_service.TIDINESS_LEVELS[member_service.TIDINESS_LEVELS.index(tidiness_min):]
        query = query.filter(tidiness__in=list(allowed))
    if lease_min:
        if lease_min not in member_service.LEASE_TERMS:
            raise CustomException(
                f"最短租期请从这几项里选：{'、'.join(member_service.LEASE_TERMS)}")
        allowed = member_service.LEASE_TERMS[member_service.LEASE_TERMS.index(lease_min):]
        query = query.filter(lease_term__in=list(allowed))
    if schedule_accept:
        accept = split_values(schedule_accept)
        unknown = [item for item in accept if item not in member_service.SCHEDULE_TYPES]
        if unknown:
            raise CustomException(
                f"作息取值里没有：{'、'.join(unknown)}，"
                f"请从这几项里选：{'、'.join(member_service.SCHEDULE_TYPES)}")
        query = query.filter(schedule_type__in=accept)
    if store_scope in ("同门店", "同片区"):
        if not store_id:
            raise CustomException(
                f"门店范围选了「{store_scope}」，请把要看的是哪家门店一起传进来")
        if store_scope == "同门店":
            query = query.filter(store_id=int(store_id))
        else:
            area = member_service.area_name(int(store_id))
            same = [code for code, name in member_service.STORE_LIST
                    if member_service.area_name(code) == area]
            query = query.filter(store_id__in=same)
    elif store_scope and store_scope != "不限":
        raise CustomException("门店范围只能填「同门店」「同片区」或「不限」")
    wanted_tags = split_values(interest_tags)
    for tag in wanted_tags:
        # 兴趣按「命中任意一个」算：全都要满足会把候选直接筛空
        query = query.filter(interest_tags__contains=tag)
    total = await query.count()
    ceiling = context.max_return_rows or POOL_LIMIT_DEFAULT
    rows = await query.order_by("-id").limit(ceiling)
    return {
        "total": total,
        "returned": len(rows),
        "hasMore": total > len(rows),
        "candidates": [_candidate_dict(member, wanted_tags) for member in rows],
    }


async def _pool_limit() -> int:
    """单轮往候选池写多少条上限，从系统参数读，读坏了退回兜底值。"""
    raw = await config_service.get_value(POOL_LIMIT_KEY, str(POOL_LIMIT_DEFAULT))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return POOL_LIMIT_DEFAULT
    return value if value > 0 else POOL_LIMIT_DEFAULT


def _compact(text: str) -> str:
    """去掉空白、把全角数字和符号换成半角，比对和取数都按这一份来。"""
    table = str.maketrans("０１２３４５６７８９＋－", "0123456789+-")
    return re.sub(r"\s+", "", str(text or "").translate(table))


def _load_json(text: str | None) -> dict:
    """把存进库的 JSON 文本读回对象，读不出来就当作空。"""
    try:
        value = json.loads(text or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def parse_relax(note: str) -> dict:
    """解析一条放宽说明，返回放宽的维度、幅度和这个维度的上限。

    说明必须写成「维度+幅度」，例如「年龄上限+2」「整洁度+1档」。写不成这样的直接拒绝：
    说不清放宽了多少，累计上限就无从算起，页面上也只能显示一句让人猜的话。
    放宽方向和维度名同样要能对上，含混的说明一律不接受。
    """
    text = _compact(note)
    if not text:
        raise CustomException(
            f"放宽说明是空的，这一轮没放宽就留空，要放宽就写成 {RELAX_FORMAT_HINT} 这样")
    matched = [rule for rule in RELAX_RULES
               if any(name in text for name in (rule["name"],) + tuple(rule["alias"]))]
    if not matched:
        raise CustomException(
            f"放宽说明里要写清放宽的是哪个维度，可放宽的维度是 {RELAX_DIMENSION_HINT}，"
            f"写成 {RELAX_FORMAT_HINT} 这样")
    if len(matched) > 1:
        names = "、".join(rule["name"] for rule in matched)
        raise CustomException(f"一轮最多放宽一个维度，这次的说明里提到了 {names}，请只留一个")
    rule = matched[0]
    if rule["name"] in RANGE_DIMENSIONS:
        if "上限" not in text and "下限" not in text:
            raise CustomException(
                f"放宽{rule['name']}要写清是上限还是下限，"
                f"例如 {_rule_example(rule)}")
        if "上限" in text and ("-" in text or "减" in text):
            raise CustomException(
                f"{rule['name']}的上限只能往上放宽，要放宽下限请写成「{rule['name']}下限-{rule['step']}」")
        if "下限" in text and ("+" in text or "加" in text):
            raise CustomException(
                f"{rule['name']}的下限只能往下放宽，要放宽上限请写成「{rule['name']}上限+{rule['step']}」")
    numbers = re.findall(r"\d+", text)
    if not numbers:
        raise CustomException(f"放宽说明里要有幅度数字，写成 {RELAX_FORMAT_HINT} 这样")
    amount = int(numbers[0])
    if amount <= 0 or amount > rule["step"]:
        raise CustomException(
            f"{rule['name']}一次最多放宽 {rule['step']}{rule['unit']}，"
            f"这次的说明是「{note}」，请把幅度改到 {rule['step']}{rule['unit']} 以内")
    return {"name": rule["name"], "amount": amount, "rule": rule}


async def relax_limit() -> int:
    """一次运行最多放宽几轮，从系统参数读，读坏了退回兜底值。

    候选池这边按它算放宽轮次，筛选那一层按它算要跑几轮，两边用同一个上限。
    """
    raw = await config_service.get_value(RELAX_LIMIT_KEY, str(RELAX_LIMIT_DEFAULT))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return RELAX_LIMIT_DEFAULT
    return value if value > 0 else RELAX_LIMIT_DEFAULT


async def _relax_used(context: ToolContext) -> dict:
    """这次任务里每一轮各放宽了什么。

    两个来源合起来看，缺一个就会算漏：

    1. 候选池里带着放宽说明的行——写进去立刻看得见，同一轮里调两次本工具也算得住；
    2. 工具调用记录——放宽了但一个候选也没筛到的那一轮，只有这里留得下痕迹。

    同一轮只算一次，以候选池里那一份为准。已经写进库的说明都是当时校验通过的，
    万一解析不出来就跳过，不拿一条历史数据把这一次的正常调用拦下来。
    """
    parsed_rounds: dict = {}
    if context.task_id:
        rows = await MatchCandidate.filter(
            task_id=context.task_id, relax_note__not_isnull=True).order_by("found_round")
        for row in rows:
            note = (row.relax_note or "").strip()
            if not note or row.found_round in parsed_rounds:
                continue
            try:
                parsed_rounds[row.found_round] = parse_relax(note)
            except CustomException:
                continue
    if context.run_id:
        steps = await AgentStep.filter(
            run_id=context.run_id,
            tool_code="save_candidates").order_by("step_index", "id")
        for step in steps:
            params = _load_json(step.request_params)
            # 轮次以步骤记录上的轮次为准：真实运行里它就是调度轮次，
            # 模型在入参里自己填的 found_round 已经不再作为判断依据
            found = step.round_no or params.get("found_round")
            note = str(params.get("relax_note") or "").strip()
            if not note or found in parsed_rounds:
                continue
            try:
                parsed_rounds[found] = parse_relax(note)
            except CustomException:
                continue
    return parsed_rounds


async def _check_relax(context: ToolContext, note: str, round_no: int) -> None:
    """校验这一轮的放宽说明：能不能放宽、放宽多少、一共放宽了几轮。

    round_no 是这次调用归属的调度轮次，由 save_candidates 算好后传进来，
    放宽轮次的去重与累计都按它记，不按模型自己填的 found_round。

    边界全部写死在这里，选择权留给模型：由它决定这一轮动哪一个维度，
    越界的一律拒绝，并把原因原样回到它手上让它改。
    """
    if not context.member_id:
        raise CustomException("这次调用没有带上租客上下文，核对不了放宽条件，请从匹配运行里调用")
    preference = await RoommatePreference.get_or_none(member_id=context.member_id)
    if preference is None:
        raise CustomException(
            "申请方还没有填合住偏好，请先让他到【合住偏好】把七个维度填好再来筛候选")
    parsed = parse_relax(note)
    rule = parsed["rule"]
    dimension = next((item for item in preference_service.DIMENSIONS
                      if item[1] == rule["name"]), None)
    if dimension is None:
        raise CustomException(f"{rule['name']}不在合住偏好的维度里，请换一个可放宽的维度")
    marked = getattr(preference, dimension[2])
    if marked == preference_service.MUST:
        raise CustomException(
            f"{rule['name']}在这位租客的偏好里标的是「{marked}」，只有标「加分」的维度才可能放宽，"
            f"标「必须」的维度任何情况下都不许动")
    if not preference_service.has_constraint(preference, dimension[0]):
        raise CustomException(
            f"{rule['name']}现在填的是不限或最宽的取值，放宽它等于没放宽，请换一个真的有约束的维度")
    relaxed = await _relax_used(context)
    before = relaxed.get(round_no)
    if before and before["name"] != rule["name"]:
        raise CustomException(
            f"第 {round_no} 轮已经放宽过「{before['name']}」了，一轮最多放宽一个维度")
    used = sum(item["amount"] for item in relaxed.values() if item["name"] == rule["name"])
    if used + parsed["amount"] > rule["total"]:
        raise CustomException(
            f"{rule['name']}累计最多放宽 {rule['total']}{rule['unit']}，现在算上这一轮已经放到 "
            f"{used + parsed['amount']}{rule['unit']} 了，请换一个维度，或者让租客到【合住偏好】把条件放宽")
    limit = await relax_limit()
    if round_no not in relaxed and len(relaxed) + 1 > limit:
        raise CustomException(
            f"一次运行最多放宽 {limit} 轮，现在放宽轮次已经用满；"
            f"候选还是不够的话，请让租客到【合住偏好】调整条件")


async def save_candidates(context: ToolContext, candidates: list | None,
                          found_round: int, relax_note: str | None = "") -> dict:
    """把本轮筛出的候选写进候选池。

    同一个候选在一套任务里只占一行：重复筛到的不再写入，只把跳过数报回去。
    本轮一条都没筛到时也要调用一次（传空列表），把放宽说明带回来——
    否则主管只看得到「这一轮什么都没发生」，不知道是没放宽还是放宽了也没用。
    第几轮筛出来的以运行上下文里的调度轮次为准，模型入参里的 found_round
    只在没有上下文的调用里兜底，真实运行不再采信。

    放宽说明要写成「维度+幅度」，校验通过才写库：维度只能是标「加分」的那些，
    幅度和累计都在放宽规则之内，一轮只放宽一个维度，整次运行的放宽轮次也不超上限。
    校验不通过就把原因抛回去，模型收到之后改一版再来。
    """
    if not context.task_id:
        raise CustomException(
            "写候选池要在一次匹配任务里进行，现在没有任务上下文。"
            "这个工具由筛选官在匹配运行里调用，不能在页面上试跑")
    rows = list(candidates or [])
    limit = await _pool_limit()
    if len(rows) > limit:
        raise CustomException(
            f"一次最多写入 {limit} 条候选，这次要写 {len(rows)} 条，请分成两次写入")
    note = str(relax_note or "").strip()
    if len(note) > 255:
        raise CustomException("放宽说明最长 255 个字，请只说清放宽了哪个维度、放宽了多少")
    # 真实运行里第几轮筛出来的由调度轮次决定，模型的 found_round 不作数
    round_no = _effective_round(context, found_round)
    if note:
        await _check_relax(context, note, round_no)
    # 申请方档案，写入时按它核对候选的性别
    applicant = await MemberProfile.get_or_none(id=context.member_id) if context.member_id else None
    written = 0
    skipped = 0
    seen: set[int] = set()
    # 整批写入放在一个事务里：第 N 条校验失败时，前 N-1 条不能留在候选池里，
    # 否则模型改一版参数重试，池子里就混进了上一次被拒的半批候选
    async with in_transaction():
        for item in rows:
            if not isinstance(item, dict):
                raise CustomException("候选列表里每一条都要是对象，至少带上候选租客编号")
            raw_id = item.get("candidate_member_id")
            try:
                candidate_id = int(raw_id)
            except (TypeError, ValueError):
                raise CustomException("候选列表里有一条没填候选租客编号")
            if candidate_id in seen:
                skipped += 1
                continue
            seen.add(candidate_id)
            if candidate_id == context.member_id:
                raise CustomException("候选里出现了申请方本人，请把它去掉再写")
            member = await MemberProfile.get_or_none(id=candidate_id)
            if member is None:
                raise CustomException(f"租客 {candidate_id} 没有档案，写不进候选池")
            if member.audit_status != "已通过":
                raise CustomException(
                    f"租客「{member.nickname}」的档案还没有通过审核，不能进候选池")
            if applicant is not None and applicant.gender and member.gender != applicant.gender:
                raise CustomException(
                    f"租客「{member.nickname}」和申请方性别不同，合租只找同性，不能进候选池")
            exists = await MatchCandidate.get_or_none(
                task_id=context.task_id, candidate_member_id=candidate_id)
            if exists:
                skipped += 1
                continue
            score = item.get("screen_score")
            if score is not None:
                score = _check_int(score, 0, 100, "初筛得分")
            await MatchCandidate.create(
                task_id=context.task_id,
                candidate_member_id=candidate_id,
                found_round=round_no,
                screen_score=score,
                # 放宽说明挂在这一轮的每一条上，页面上按候选看就能看出它是哪一轮、放宽了什么进来的
                relax_note=note or None,
                audit_status="待审核",
            )
            written += 1
    return {"written": written, "skipped": skipped, "relax_note": note, "returned": written}


async def read_candidate_preference(context: ToolContext,
                                    candidate_member_id: int) -> dict:
    """读某个候选方的合住偏好与最新画像。

    审核官站的是候选方的立场：这位候选在意什么、他自己是什么样的人，
    两样都要拿到才判断得出「申请方适不适合和他合住」。
    画像还没生成时照样返回档案和偏好，另外带一句说明，审核官据此知道哪一维度判断不了。
    """
    try:
        candidate_id = int(candidate_member_id)
    except (TypeError, ValueError):
        raise CustomException("请把候选租客编号填成整数")
    member = await MemberProfile.get_or_none(id=candidate_id)
    if member is None:
        raise CustomException("没有找到这个候选租客的档案，请确认候选编号后重试")
    preference = await RoommatePreference.get_or_none(member_id=candidate_id)
    portrait = await MemberPortrait.filter(
        member_id=candidate_id).order_by("-version", "-id").first()
    return {
        "candidate_member_id": candidate_id,
        "nickname": member.nickname,
        "gender": member.gender,
        "age": member_service.calc_age(member.birth_date),
        "rent_budget": member.rent_budget,
        "tidiness": member.tidiness,
        "occupation": member.occupation,
        "lease_term": member.lease_term,
        "store": member_service.store_name(member.store_id),
        "area": member_service.area_name(member.store_id),
        "schedule_type": member.schedule_type,
        "has_pet": member.has_pet,
        "smoking": member.smoking,
        "self_intro": member.self_intro,
        "roommate_expectation": member.roommate_expectation,
        "interest_tags": split_values(member.interest_tags),
        "preference": None if preference is None else {
            "age": {"range": [preference.age_min, preference.age_max],
                    "required": preference.age_required},
            "budget": {"range": [preference.budget_min, preference.budget_max],
                       "required": preference.budget_required},
            "tidiness": {"min": preference.tidiness_min,
                         "required": preference.tidiness_required},
            "store": {"scope": preference.store_scope, "required": preference.store_required},
            "schedule": {"accept": split_values(preference.schedule_accept),
                         "required": preference.schedule_required},
            "lease": {"min": preference.lease_min, "required": preference.lease_required},
            "pet": {"accept": preference.pet_accept, "required": preference.pet_required},
        },
        "preference_missing": "这位候选还没有填合住偏好" if preference is None else None,
        "portrait": None if portrait is None else {
            "version": portrait.version,
            "personality_tags": split_values(portrait.personality_tags),
            "lifestyle_tags": split_values(portrait.lifestyle_tags),
            "cohabit_need_tags": split_values(portrait.cohabit_need_tags),
            "summary": portrait.summary,
        },
        "portrait_missing": "这位候选还没有生成画像" if portrait is None else None,
        "returned": 1,
    }


def _mentions_dimension(reason: str) -> bool:
    """否决理由里有没有点名缺哪个维度。"""
    return any(name in reason for name in PORTRAIT_DIMENSIONS)


async def save_audit_result(context: ToolContext, candidate_member_id: int,
                            audit_status: str, reject_code: str | None = None,
                            reject_reason: str | None = None) -> dict:
    """把一个候选的审核结论回填到候选池。

    结论只能回填一次：只有「待审核」的候选能被回填，已经有结论的行一律拒绝。
    这样模型跨批、重复调用或下一轮重审都不能悄悄覆盖别人的结论，批次计数和候选池
    才对得上；真要改判由代码复核在批内完成，或由管理员处理。

    合租只找同性：申请方与候选方性别都已知且不同的，判通过会被直接拒绝——
    性别不在合住偏好的七个维度里，模型从偏好文本上看不出这一条，只能由代码兜住。

    否决必须分类：分不清是「人不合适」还是「画像不够、判断不了」，主管就只剩
    「再筛一轮」一条路；分开之后它才能先派画像师补画像，再重新筛选和审核。
    所以判 PORTRAIT_INSUFFICIENT 时要求理由里点名缺哪个维度，这个维度会被主管
    原样拿去安排补画像。
    """
    if not context.task_id:
        raise CustomException(
            "回填审核结论要在一次匹配任务里进行，现在没有任务上下文。"
            "这个工具由审核官在匹配运行里调用，不能在页面上试跑")
    try:
        candidate_id = int(candidate_member_id)
    except (TypeError, ValueError):
        raise CustomException("请把候选租客编号填成整数")
    status = str(audit_status or "").strip()
    if status not in AUDIT_STATUSES:
        raise CustomException(
            f"审核结论请从这几项里选：{'、'.join(AUDIT_STATUSES)}")
    row = await MatchCandidate.get_or_none(
        task_id=context.task_id, candidate_member_id=candidate_id)
    if row is None:
        raise CustomException(
            "这位租客不在本次任务的候选池里，请先让筛选官把他筛出来，再来回填结论")
    if row.audit_status != "待审核":
        raise CustomException(
            f"这位候选已经有审核结论（{row.audit_status}），结论只能回填一次；"
            f"请不要重复回填或跨批改判，需要改判请让代码复核或管理员处理")
    if status == AUDIT_PASS and context.member_id:
        applicant = await MemberProfile.get_or_none(id=context.member_id)
        candidate = await MemberProfile.get_or_none(id=row.candidate_member_id)
        if (applicant is not None and candidate is not None
                and applicant.gender and candidate.gender
                and applicant.gender != candidate.gender):
            raise CustomException(
                f"合租只找同性：申请方是{applicant.gender}，候选方是{candidate.gender}，"
                f"不能判通过；这位候选只能判否决，请重新给结论")
    code = None
    reason = None
    if status == AUDIT_REJECT:
        code = str(reject_code or "").strip()
        if code not in REJECT_CODES:
            raise CustomException(
                f"否决原因请从这几项里选：{'、'.join(REJECT_CODES)}")
        reason = str(reject_reason or "").strip()
        if not reason:
            raise CustomException("否决要写明理由，主管和页面都靠它判断下一步该做什么")
        if len(reason) > 500:
            raise CustomException("否决理由最长 500 个字，请写清关键的那一条")
        if code == "PORTRAIT_INSUFFICIENT" and not _mentions_dimension(reason):
            raise CustomException(
                "判「画像不够、判断不了」时，理由里要点名缺的是哪个维度，"
                "比如「缺作息：几点睡、几点起都没有依据」——主管要照着它安排补画像")
    await MatchCandidate.filter(id=row.id).update(
        audit_status=status,
        reject_code=code,
        reject_reason=reason,
        audit_round=context.round_no or None,
    )
    return {
        "candidate_member_id": candidate_id,
        "audit_status": status,
        "reject_code": code,
        "returned": 1,
    }


# 编码到实现的对照表。注册表里的 tool_code 必须在这张表里找得到，
# 工具中心保存时会拿这张表核对，对不上的编码根本不让存
IMPLEMENTATIONS: dict[str, Callable] = {
    "read_member_detail": read_member_detail,
    "read_member_moments": read_member_moments,
    "list_interest_tags": list_interest_tags,
    "read_roommate_preference": read_roommate_preference,
    "search_members": search_members,
    "save_candidates": save_candidates,
    "read_candidate_preference": read_candidate_preference,
    "save_audit_result": save_audit_result,
}
