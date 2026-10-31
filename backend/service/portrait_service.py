"""租客画像业务逻辑。

画像是一次「读材料 → 提炼标签 → 落库」的执行：材料是租客自己写的自我介绍、
室友期望和动态原文，产出是三类标签、一段概括，以及每个标签依据的那段原文。

三件事在这里定死，不由模型自由发挥：

1. 标签必须有依据。模型给的每个标签都要能在原文里找到那段话，找不到的丢掉，
   丢掉了哪几个一起写进结论。标签没有依据，后面的匹配理由就没有根。
2. 一个标签都不剩，这次提取算失败：不落库、也不报成功，宁可让租客重试，
   也不能往画像表里写一条空画像。
3. 版本只增不删。每提取一次产生一个新版本，旧版本留着，
   补画像前后审核通过率的变化就靠这份历史。

落库之前还要反查一次：写进去的那条必须能按租客编号和版本号原样读回来，
页面上的数字全部以库里的为准。
"""

import json
import re
from dataclasses import dataclass, field
from uuid import uuid4

from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from ai import agents, model_factory
from ai import tools as tool_box
from common.exception_handler import CustomException
from common.text import split_values
from common.times import cost_millis, format_datetime, now, precise_now
from models import (AgentDefinition, AgentRun, AiModelConfig, FunctionTool, MemberMoment,
                    MemberPortrait, MemberProfile, PromptTemplate, User)
from service import agent_service, member_service

# 跑这次执行的角色，以及它产出写进哪张表
AGENT_CODE = agents.AGENT_PORTRAIT
RUN_TYPE = "画像提取"
# 画像师必须先把租客档案读到手，没读就交结论会被执行器打回去
REQUIRED_TOOLS = ("read_member_detail",)

# 三类标签的字段名和给页面看的中文名
TAG_FIELDS = (
    ("personality_tags", "性格"),
    ("lifestyle_tags", "生活方式"),
    ("cohabit_need_tags", "合住需求"),
)
# 一个版本里每类标签最多留几个，多出来的丢掉
TAG_LIMIT = 6
# 单个标签的最长字数。标签是一两个词的短句，超长的说明模型写成了整句话
TAG_MAX_LENGTH = 30
# 单条依据的最长字数，防止模型把整段动态贴进依据里
EVIDENCE_MAX_LENGTH = 200
# 提示词里带几条动态
MOMENT_LIMIT = 20
# 收尾原因写库前的长度上限，error_message 那一列只放 500 字
SUMMARY_LIMIT = 2000
ERROR_LIMIT = 500

# 运行状态，取值和 agent_run.run_status 一致
RUN_RUNNING = "运行中"
RUN_DONE = "已完成"
RUN_FAILED = "运行失败"


@dataclass
class PortraitResult:
    """一次画像提取的结果。

    gate 有值表示执行被闸拦下来了，portrait 必定是空的；
    conclusion 是可以直接写进运行记录、也可以回给页面的一句话结论。
    """

    portrait: MemberPortrait | None
    conclusion: str
    gate: str | None = None
    tool_calls: int = 0
    dropped: list[str] = field(default_factory=list)


def _plain(text: str | None) -> str:
    """去掉所有空白，用来比对依据片段在不在原文里。

    模型抄原文时常常多一个换行或者少一个空格，
    按字符一一比对会把正常的依据判成找不到，所以两边都先去空白再比。
    """
    return re.sub(r"\s+", "", text or "")


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _check(key: str, label: str, ok: bool, message: str,
           action_path: str | None = None, action_label: str | None = None) -> dict:
    """一项前置条件。不满足时 message 里要写清去哪做什么。"""
    return {
        "key": key,
        "label": label,
        "ok": ok,
        "message": message,
        "action_path": action_path,
        "action_label": action_label,
    }


def _parse_evidence(text: str | None) -> dict:
    if not text:
        return {}
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def evidence_rows(portrait: MemberPortrait) -> list[dict]:
    """把每个标签和它依据的那段原文摊平成表格行。"""
    evidence = _parse_evidence(portrait.evidence)
    rows: list[dict] = []
    for name, label in TAG_FIELDS:
        for tag in split_values(getattr(portrait, name)):
            rows.append({
                "dimension": label,
                "tag": tag,
                "source": evidence.get(tag),
            })
    return rows


def portrait_dict(portrait: MemberPortrait | None, with_evidence: bool = True) -> dict | None:
    """手写转字典：三类标签拆成数组，时间格式化成页面能直接显示的字符串。

    列表里只需要看版本和概括，依据明细只在弹窗里看，所以 with_evidence
    由调用方决定要不要把依据行一起带出来。
    """
    if portrait is None:
        return None
    data = {
        "id": portrait.id,
        "member_id": portrait.member_id,
        "version": portrait.version,
        "personality_tags": split_values(portrait.personality_tags),
        "lifestyle_tags": split_values(portrait.lifestyle_tags),
        "cohabit_need_tags": split_values(portrait.cohabit_need_tags),
        "summary": portrait.summary,
        "focus_hint": portrait.focus_hint,
        "run_id": portrait.run_id,
        "tag_count": sum(len(split_values(getattr(portrait, name))) for name, _ in TAG_FIELDS),
        "create_time": format_datetime(portrait.create_time),
    }
    if with_evidence:
        data["evidence"] = evidence_rows(portrait)
    return data


def clean_portrait(data: dict, sources: str) -> tuple[dict, dict, list[str], dict]:
    """逐条核验模型给的标签，返回（三类标签、标签依据、被丢掉的标签、每类留下的个数）。

    这是「模型负责提炼、代码负责核对」这一步的落点：

    - 标签名必须能在原文里找到所说的那段依据，找不到的丢掉，一个一个记下来；
    - 标签太长、或者一类超过上限的，同样丢掉并记下来；
    - 三类标签都不剩时由调用方判这次提取失败，不落空画像。
    """
    raw_evidence = data.get("evidence")
    evidence = raw_evidence if isinstance(raw_evidence, dict) else {}
    text = _plain(sources)
    # 概括不需要像标签一样做“原文逐字命中”校验，但仍要从模型结果带到落库值里。
    # 之前这里只重建了三类标签，导致模型明明返回了 summary，保存时却永远取到空值。
    summary = str(data.get("summary") or "").strip()
    values: dict = {"summary": summary or None}
    kept: dict[str, str] = {}
    dropped: list[str] = []
    counts: dict = {}
    for name, _label in TAG_FIELDS:
        tags: list[str] = []
        for item in _as_list(data.get(name)):
            tag = str(item or "").strip()
            # 同一个词在一类里说两遍只算一个
            if not tag or tag in tags:
                continue
            if len(tag) > TAG_MAX_LENGTH:
                dropped.append(f"{tag[:TAG_MAX_LENGTH]}（标签太长）")
                continue
            if len(tags) >= TAG_LIMIT:
                dropped.append(f"{tag}（超过每类 {TAG_LIMIT} 个）")
                continue
            source = str(evidence.get(tag) or "").strip()[:EVIDENCE_MAX_LENGTH]
            if not source or _plain(source) not in text:
                dropped.append(f"{tag}（原文里找不到依据）")
                continue
            tags.append(tag)
            kept[tag] = source
        values[name] = ",".join(tags) or None
        counts[name] = len(tags)
    return values, kept, dropped, counts


def _profile_text(profile: dict) -> str:
    """把租客档案摊平成发给模型看的一段文字。"""
    lines = [
        f"昵称：{profile.get('nickname')}",
        f"性别：{profile.get('gender')}",
        f"年龄：{profile.get('age')}",
        f"月租预算：{profile.get('rent_budget')} 元",
        f"整洁度：{profile.get('tidiness')}",
        f"职业：{profile.get('occupation')}",
        f"计划租期：{profile.get('lease_term')}",
        f"意向门店：{profile.get('store')}（{profile.get('area')}片区）",
        f"作息：{profile.get('schedule_type')}",
        f"是否养宠：{profile.get('has_pet')}",
        f"是否吸烟：{profile.get('smoking')}",
        f"已选的兴趣标签：{'、'.join(profile.get('interest_tags') or []) or '（还没有选）'}",
        f"自我介绍：{profile.get('self_intro') or '（没有填）'}",
        f"室友期望：{profile.get('roommate_expectation') or '（没有填）'}",
    ]
    return "\n".join(lines)


def _moments_text(moments: dict) -> str:
    """把动态原文按时间倒序摊平，带上编号方便模型指明依据来自哪一条。"""
    rows = moments.get("moments") or []
    if not rows:
        return "（这位租客还没有发布过公开动态）"
    return "\n".join(
        f"动态{index}（{row.get('publish_time') or '时间不详'}）：{row.get('content')}"
        for index, row in enumerate(rows, 1))


def _tags_text(tags: dict) -> str:
    """兴趣标签词表按类目摊平，模型只能从这里挑词。"""
    grouped: dict[str, list[str]] = {}
    for row in tags.get("tags") or []:
        grouped.setdefault(row.get("category") or "其它", []).append(row.get("tag_name") or "")
    if not grouped:
        return "（词表里还没有启用的标签，这一次不要写兴趣类标签）"
    return "\n".join(f"{name}：{'、'.join(items)}" for name, items in grouped.items())


def _instruction(hint: str | None) -> str:
    text = "现在给这位租客提取画像。请先调用工具把他的档案和动态原文读到手里，再按输出格式给出结论。"
    if hint:
        text += f"本次要重点补充的是「{hint}」维度，这一维度必须给出标签，每个标签都要有原文依据。"
    return text


def _summarize(data: dict) -> str:
    parts = [f"{label} {len(_as_list(data.get(name)))} 个" for name, label in TAG_FIELDS]
    return "模型给出：" + "、".join(parts) + "标签"


async def _prompt_values(member: MemberProfile, hint: str | None) -> tuple[dict, str]:
    """组装提示词变量，同时把发给模型的材料原样留一份用来核对依据。

    档案和动态都通过工具实现来读：取哪些字段、动态取几条、按什么排序，
    和画像师自己在循环里调工具读到的完全一致。
    """
    context = tool_box.ToolContext(member_id=member.id)
    profile = await tool_box.read_member_detail(context)
    moments = await tool_box.read_member_moments(context, limit=MOMENT_LIMIT)
    tags = await tool_box.list_interest_tags(context)
    profile_text = _profile_text(profile)
    moments_text = _moments_text(moments)
    values = {
        "member_profile": profile_text,
        "moments": moments_text,
        "interest_tags": _tags_text(tags),
        "focus_hint": hint or "（这次没有指定，按档案和动态自己判断重点）",
    }
    return values, profile_text + "\n" + moments_text


async def _save(member: MemberProfile, values: dict, evidence: dict,
                hint: str | None, run_id: int) -> MemberPortrait:
    """写入一个新版本，再按租客编号和版本号反查一次确认真的落库了。

    「读最新版本 → 写新版本 → 反查」三步放在同一条事务里：两个请求同时补画像时，
    后一个不会读到前一个提交前的旧版本、算出同一个版本号。版本号有唯一键兜底，
    真撞上就重新读版本重试一次；第二次还撞就明确报错，不把半条画像留在库里。
    """
    for _attempt in range(2):
        try:
            async with in_transaction():
                latest = await MemberPortrait.filter(
                    member_id=member.id).order_by("-version").first()
                version = latest.version + 1 if latest else 1
                await MemberPortrait.create(
                    member_id=member.id,
                    version=version,
                    personality_tags=values.get("personality_tags"),
                    lifestyle_tags=values.get("lifestyle_tags"),
                    cohabit_need_tags=values.get("cohabit_need_tags"),
                    summary=(values.get("summary") or "").strip() or None,
                    evidence=json.dumps(evidence, ensure_ascii=False),
                    focus_hint=hint,
                    run_id=run_id,
                )
                saved = await MemberPortrait.get_or_none(
                    member_id=member.id, version=version)
                if saved is None:
                    raise CustomException("画像写进库里之后没有查回来，请重试")
                return saved
        except IntegrityError:
            # 版本唯一键冲突：另一个请求先写了同一版，重新读版本号再试一次
            continue
    raise CustomException("画像版本号冲突，已经重试一次仍然写不进去，请稍后重试")


def _conclusion(portrait: MemberPortrait, outcome: agents.AgentOutcome,
                dropped: list[str]) -> str:
    counts = "、".join(
        f"{label} {len(split_values(getattr(portrait, name)))} 个" for name, label in TAG_FIELDS)
    text = f"画像 v{portrait.version} 已生成：{counts}，共调用工具 {outcome.tool_calls} 次"
    if dropped:
        text += "；没有写进画像的标签：" + "、".join(dropped)
    return text


async def build_portrait(member_id: int, run_id: int, *, round_no: int = 1,
                         focus_hint: str | None = None) -> PortraitResult:
    """跑一次画像提取并把结果落库。

    运行记录由调度层创建，画像产物通过 run_id 关联本次智能匹配。
    """
    member = await MemberProfile.get_or_none(id=member_id)
    if member is None:
        raise CustomException("没有找到这位租客的档案，请先让他把档案填好")
    hint = (focus_hint or "").strip()[:255] or None
    values, sources = await _prompt_values(member, hint)
    context = tool_box.ToolContext(run_id=run_id, agent_code=AGENT_CODE,
                                   member_id=member.id, round_no=round_no)
    outcome = await agents.run_agent(
        AGENT_CODE, context,
        prompt_values=values,
        instruction=_instruction(hint),
        required_tools=REQUIRED_TOOLS,
        summarize=_summarize)
    if outcome.gate:
        # 被闸拦下来：当前角色立即中断，把触发了哪道闸原样带回去
        return PortraitResult(portrait=None, conclusion=outcome.conclusion,
                              gate=outcome.gate, tool_calls=outcome.tool_calls)
    cleaned, evidence, dropped, counts = clean_portrait(outcome.data or {}, sources)
    if not any(counts.values()):
        return PortraitResult(
            portrait=None,
            conclusion="这次没有提取出任何能在原文里找到依据的标签，画像没有落库",
            tool_calls=outcome.tool_calls, dropped=dropped)
    portrait = await _save(member, cleaned, evidence, hint, run_id)
    return PortraitResult(portrait=portrait, conclusion=_conclusion(portrait, outcome, dropped),
                          tool_calls=outcome.tool_calls, dropped=dropped)


async def readiness(member: MemberProfile | None) -> dict:
    """生成画像之前要过的六项检查。

    按顺序一项一项看，第一项不满足就停下来：后面的几项在材料都不齐的时候
    也判断不出结果，列一屏红字不如只指一处。每一项的提示都写清去哪做什么。
    """
    checks: list[dict] = []

    def blocked(item: dict) -> dict:
        checks.append(item)
        return {"checks": checks, "blocker": item, "can_generate": False}

    if member is None:
        return blocked(_check("profile", "租客档案", False,
                              "还没有填写租客档案，请先到【租客档案】把档案填好",
                              "/front/memberProfile", "去填写租客档案"))
    if not (member.self_intro or "").strip():
        return blocked(_check("profile", "租客档案", False,
                              "自我介绍还是空白的，请先到【租客档案】把它补上",
                              "/front/memberProfile", "去补充自我介绍"))
    checks.append(_check("profile", "租客档案", True, "自我介绍已填写"))

    moment_count = await MemberMoment.filter(member_id=member.id, visible="公开").count()
    if not moment_count:
        return blocked(_check("moment", "公开动态", False,
                              "还没有发布过公开动态，请先到【我的动态】发一条；"
                              "画像里的生活方式标签主要从动态原文里来",
                              "/front/myMoment", "去发布动态"))
    checks.append(_check("moment", "公开动态", True, f"已发布 {moment_count} 条公开动态"))

    agent = await AgentDefinition.get_or_none(agent_code=AGENT_CODE)
    if agent is None:
        return blocked(_check("agent", "画像师角色", False,
                              "平台没有找到画像师角色，请联系管理员到【子 Agent 定义】核对"))
    if agent.enabled != "是":
        return blocked(_check("agent", "画像师角色", False,
                              "画像师已被停用，请联系管理员到【子 Agent 定义】把它启用"))
    checks.append(_check("agent", "画像师角色", True, "画像师已启用"))

    prompt = await PromptTemplate.get_or_none(code=agent.prompt_code)
    state = agent_service.prompt_state(prompt)
    if state != "正常":
        return blocked(_check("prompt", "提示词模板", False,
                              f"画像师的提示词模板不可用（{state}），"
                              f"请联系管理员到【Prompt模板】处理"))
    checks.append(_check("prompt", "提示词模板", True, "提示词模板正常"))

    tool_count = await FunctionTool.filter(tool_group=agent.tool_group, enabled="是").count()
    if not tool_count:
        return blocked(_check("tool", "画像工具", False,
                              f"画像师的工具分组「{agent.tool_group}」下没有启用中的工具，"
                              f"请联系管理员到【工具中心】启用"))
    checks.append(_check("tool", "画像工具", True, f"可用工具 {tool_count} 个"))

    config = await AiModelConfig.filter(
        model_purpose=model_factory.PURPOSE_PORTRAIT, enabled="是").order_by("-id").first()
    if config is None:
        return blocked(_check("model", "画像模型", False,
                              "平台还没有启用「画像」用途的对话模型，"
                              "请联系管理员到【AI模型配置】启用一条"))
    if not config.api_key:
        return blocked(_check("model", "画像模型", False,
                              f"「{config.name}」还没有填写 API Key，"
                              f"请联系管理员到【AI模型配置】补上"))
    if not config.model_name:
        return blocked(_check("model", "画像模型", False,
                              f"「{config.name}」还没有填写模型名称，"
                              f"请联系管理员到【AI模型配置】补上"))
    checks.append(_check("model", "画像模型", True, f"已启用「{config.name}」"))
    return {"checks": checks, "blocker": None, "can_generate": True}


async def _open_run(member: MemberProfile, user_id: int, moment_count: int) -> AgentRun:
    """开一条运行记录。入参快照留着，运行失败之后能复现当时的输入。"""
    snapshot = json.dumps({
        "member_id": member.id,
        "nickname": member.nickname,
        "public_moment_count": moment_count,
        "focus_hint": None,
    }, ensure_ascii=False)
    return await AgentRun.create(
        run_no=f"PORTRAIT-{now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}",
        user_id=user_id,
        run_type=RUN_TYPE,
        run_status=RUN_RUNNING,
        current_round=1,
        input_snapshot=snapshot,
        start_time=now())


async def _close_run(run: AgentRun, started, failed: bool, summary: str) -> None:
    """收尾运行记录：状态、最终结论、失败原因、耗时一次写全。"""
    await AgentRun.filter(id=run.id).update(
        run_status=RUN_FAILED if failed else RUN_DONE,
        total_round=1,
        output_summary=summary[:SUMMARY_LIMIT],
        error_message=summary[:ERROR_LIMIT] if failed else None,
        end_time=now(),
        cost_millis=cost_millis(started))


async def generate_for_candidate(member_id: int) -> MemberPortrait | None:
    """给候选补一版画像（评测/后台补数据用，不改变候选的公开身份）。

    候选画像只在有公开动态时才生成；没有动态不硬造，直接返回 None。
    每次生成仍走画像师和原有版本校验，失败只影响这一个候选，不抛到调用方。
    """
    member = await MemberProfile.get_or_none(id=member_id)
    if member is None:
        return None
    existing = await MemberPortrait.filter(member_id=member.id).order_by("-version").first()
    if existing is not None:
        return existing
    moments = await MemberMoment.filter(member_id=member.id, visible="公开").count()
    if not moments:
        return None
    user = await User.get_or_none(id=member.user_id)
    if user is None:
        return None
    started = precise_now()
    run = await _open_run(member, user.id, moments)
    try:
        result = await build_portrait(member.id, run.id)
    except CustomException as exc:
        await _close_run(run, started, True, exc.message)
        return None
    except Exception:  # noqa: BLE001
        await _close_run(run, started, True, "候选画像生成出现未预期错误")
        return None
    if result.gate or result.portrait is None:
        await _close_run(run, started, True, result.conclusion[:ERROR_LIMIT])
        return None
    await _close_run(run, started, False, result.conclusion)
    return result.portrait


async def generate(current_user: User) -> dict:
    """租客点一次【生成画像】走的路：核对条件、开运行、提取、收尾。"""
    member = await member_service.get_my_member(current_user, "生成画像")
    state = await readiness(member)
    if not state["can_generate"]:
        # 条件不满足就在这里停下，一步都不往模型走，也不留半条运行记录
        raise CustomException(state["blocker"]["message"])
    moment_count = await MemberMoment.filter(member_id=member.id, visible="公开").count()
    started = precise_now()
    run = await _open_run(member, current_user.id, moment_count)
    try:
        result = await build_portrait(member.id, run.id)
    except CustomException as exc:
        await _close_run(run, started, True, exc.message)
        raise
    if result.gate:
        message = (f"画像提取被中断：{result.conclusion}。请稍后重试；"
                   f"如果每次都这样，请让管理员到【子 Agent 定义】检查画像师的单次工具调用上限")
        await _close_run(run, started, True, message)
        raise CustomException(message)
    if result.portrait is None:
        message = f"{result.conclusion}。请补充自我介绍和动态内容后重试"
        await _close_run(run, started, True, message)
        raise CustomException(message)
    await _close_run(run, started, False, result.conclusion)
    return {"portrait": portrait_dict(result.portrait), "conclusion": result.conclusion}


async def my_page(current_user: User) -> dict:
    """租客端「我的画像」：条件核对、当前版本、历史版本一次取回。"""
    member_service.check_member_role(current_user)
    member = await MemberProfile.get_or_none(user_id=current_user.id)
    state = await readiness(member)
    if member is None:
        return {"has_profile": False, "readiness": state, "portrait": None, "history": []}
    versions = await MemberPortrait.filter(member_id=member.id).order_by("-version")
    return {
        "has_profile": True,
        "readiness": state,
        "portrait": portrait_dict(versions[0]) if versions else None,
        "history": [portrait_dict(item, with_evidence=False) for item in versions],
    }


async def detail(current_user: User, portrait_id: int) -> dict:
    """查看某一个历史版本的画像，带每个标签的原文依据。"""
    member = await member_service.get_my_member(current_user, "查看画像")
    portrait = await MemberPortrait.get_or_none(id=portrait_id, member_id=member.id)
    if portrait is None:
        raise CustomException("没有找到这个版本的画像，请刷新页面后重试")
    return portrait_dict(portrait)
