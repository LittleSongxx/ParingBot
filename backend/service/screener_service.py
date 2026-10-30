"""候选筛选业务逻辑。

筛选官做的是「按申请方的合住偏好去租客库里找人，人不够就放宽加分项再找」：
第 1 轮把标「必须」的维度当硬门槛筛一轮，候选数不够交付要求时，
一轮放宽一个标「加分」的维度再筛，直到够数或者放宽次数用尽。
每一轮筛出来的候选都写进候选池，带上是第几轮筛出来的和这一轮的放宽说明，
页面上因此看得到「第 2 轮放宽了预算上限+200，新增候选 15 人」这样的完整过程。

这里定死三件事：

1. 能放宽哪几个维度、单次能放宽多少、累计能放宽多少、整次运行能放宽几轮，
   都不由模型说了算。校验在写候选池的那个工具里，模型越界会被拒绝并把原因收到手里。
2. 每一轮的候选数从候选池里数，不采信模型结论里报的数。模型报的和库里存的对不上时，
   以库里为准，并把这件事写进这一轮的结论。
3. 候选池里一个人只占一行。重复筛到的只算一次，后面审核出的结论也是回填这一行。

一次筛选留下两类记录：agent_run / agent_step 记过程，match_task / match_candidate 记结果。
租客端页面读的是后两者的现查结果，页面上的数字全部来自数据库。
"""

import json
from dataclasses import dataclass, field
from uuid import uuid4

from ai import agents, model_factory
from ai import tools as tool_box
from common.exception_handler import CustomException
from common.text import split_values
from common.times import cost_millis, format_datetime, now, precise_now
from models import (AgentDefinition, AgentRun, AgentStep, AiModelConfig, FunctionTool,
                    MatchCandidate, MatchTask, MemberProfile, PromptTemplate,
                    RoommatePreference, User)
from service import agent_service, config_service, member_service, preference_service

# 跑这一轮的角色，以及它产出写进哪张表
AGENT_CODE = agents.AGENT_SCREENER
RUN_TYPE = "候选筛选"
# 每一轮都必须先把偏好读到手里、再把结果写进候选池，两件都不许省。
# 少写候选池那一次，这一轮的放宽说明就没地方留，页面上只看到候选突然多了一批
REQUIRED_TOOLS = ("read_roommate_preference", "save_candidates")
# 写候选池的工具编码，用它从步骤记录里取回每一轮的放宽说明
SAVE_TOOL = "save_candidates"
# 默认交付人数与候选不足时的兜底
DELIVER_KEY = "MATCH_DELIVER_COUNT"
DELIVER_DEFAULT = 8
# 结论与失败原因写库前的长度上限，error_message 那一列只放 500 字
SUMMARY_LIMIT = 2000
ERROR_LIMIT = 500

# 任务状态，取值和 match_task.status 一致
TASK_RUNNING = "执行中"
TASK_DONE = "已完成"
TASK_FAILED = "执行失败"
# 运行状态，取值和 agent_run.run_status 一致
RUN_RUNNING = "运行中"
RUN_DONE = "已完成"
RUN_FAILED = "运行失败"
# 候选刚进池子时的审核状态，审核官回来才改它
AUDIT_WAIT = "待审核"


@dataclass
class ScreenRound:
    """一轮筛选的结果。

    note 是这一轮真正写进候选池的放宽说明，取自工具调用记录，不是模型结论里报的那一份；
    mismatch 有值表示模型报的和库里存的对不上，这一轮的结论里会写明。
    gate 有值表示这一轮被闸拦下来了，这一轮没有产出。
    """

    round_no: int
    written: int = 0
    note: str | None = None
    conclusion: str = ""
    gate: str | None = None
    tool_calls: int = 0
    mismatch: str | None = None


@dataclass
class ScreenResult:
    """一次筛选跑完的结果。total 是候选池里现有多少条，现查出来的。"""

    rounds: list[ScreenRound] = field(default_factory=list)
    total: int = 0
    conclusion: str = ""
    gate: str | None = None


def target_gender(member: MemberProfile) -> str:
    """候选找哪个性别：合租按同性匹配，申请方是男就只在男租客里找。"""
    return member.gender


def _span(low, high, unit: str) -> str:
    """一段区间读成人话：下限、上限有一头没填时只写另一头。"""
    if low is None and high is None:
        return "不限"
    if high is None:
        return f"{low}{unit}及以上"
    if low is None:
        return f"{high}{unit}及以下"
    return f"{low}-{high}{unit}"


def preference_text(preference: dict) -> str:
    """把合住偏好摊平成给模型看的一段文字。

    每个维度后面都带上必须或加分：标必须的是硬门槛，标加分的候选不够时才能动。
    不带这个标注，筛选官分不清哪些能让步。
    """
    def flag(item: dict) -> str:
        return item.get("required") or preference_service.BONUS

    age = preference.get("age") or {}
    budget = preference.get("budget") or {}
    tidiness = preference.get("tidiness") or {}
    store = preference.get("store") or {}
    schedule = preference.get("schedule") or {}
    lease = preference.get("lease") or {}
    pet = preference.get("pet") or {}
    return "\n".join([
        f"年龄：{_span(*((age.get('range') or [None, None])[:2]), '岁')}（{flag(age)}）",
        f"预算：{_span(*((budget.get('range') or [None, None])[:2]), '元')}（{flag(budget)}）",
        f"整洁度：{tidiness.get('min') or '不限'}及以上（{flag(tidiness)}）",
        f"门店：{store.get('scope') or '不限'}（{flag(store)}）",
        f"作息：可接受 {'、'.join(schedule.get('accept') or []) or '不限'}（{flag(schedule)}）",
        f"租期：{lease.get('min') or '不限'}及以上（{flag(lease)}）",
        f"对室友养宠的接受度：{pet.get('accept') or preference_service.NO_OPINION}（{flag(pet)}）",
    ])


def relaxable_dimensions(member_preference: RoommatePreference) -> list[dict]:
    """这位租客能被放宽的维度，带上单次幅度和累计上限。

    只有标「加分」而且确实有约束的维度才在里面；放宽规则表里没有的维度
    （比如宠物态度）即使标了加分也不放宽，所以这里按规则表过滤一遍——
    能放宽什么，代码说了算。
    """
    rules = {rule["name"]: rule for rule in tool_box.RELAX_RULES}
    items: list[dict] = []
    for item in preference_service.relaxable_dimensions(member_preference):
        rule = rules.get(item["name"])
        if rule is None:
            continue
        items.append({"name": item["name"], "step": rule["step"],
                      "total": rule["total"], "unit": rule["unit"]})
    return items


def relax_text(items: list[dict], history: list, remaining: int) -> str:
    """放宽历史和这一轮还能动哪个维度。

    已经放宽过的连轮次一起列出来，模型据此知道哪个维度快到累计上限了。
    """
    if history:
        used = "；".join(f"第 {round_no} 轮放宽了「{note}」" for round_no, note in history)
    else:
        used = "（还没有放宽过任何条件）"
    lines = [f"已经放宽的：{used}", f"这次运行还能再放宽 {remaining} 轮"]
    if items:
        detail = "、".join(
            f"{item['name']}（一次最多 {item['step']}{item['unit']}，"
            f"累计最多 {item['total']}{item['unit']}）" for item in items)
        lines.append("可以放宽的维度：" + detail)
    else:
        lines.append("这位租客没有可以放宽的维度：标为加分的维度要么没填，要么填的是不限。")
    return "\n".join(lines)


def instruction(member: MemberProfile, round_no: int, pool: int, deliver: int) -> str:
    """这一轮交给筛选官的交代。

    第 1 轮说清是硬筛，之后每一轮说清最多动一个加分维度，再带上还差几个人。
    """
    age = member_service.calc_age(member.birth_date)
    parts = [
        f"给租客「{member.nickname}」（{member.gender}，{age} 岁，"
        f"意向门店 {member_service.store_name(member.store_id)}，门店编号 {member.store_id}）"
        f"筛第 {round_no} 轮候选。",
        f"合租只找同性，检索时 gender 传「{target_gender(member)}」；"
        f"门店范围不是不限时，store_id 传申请方的门店编号 {member.store_id}。",
    ]
    if round_no == 1:
        parts.append("这一轮是硬筛：按合住偏好里的条件检索，不要放宽任何维度。")
    else:
        parts.append("上一轮的候选不够交付人数，这一轮最多放宽一个标为加分的维度再检索一次。")
    parts.append(f"候选池现在有 {pool} 人，本次要求交付 {deliver} 人。")
    parts.append("放宽说明写成「维度+幅度」，例如 "
                 f"{tool_box.RELAX_FORMAT_HINT}；这一轮没放宽就填空字符串。"
                 "标为必须的维度任何情况下都不许放宽。")
    parts.append("先把偏好读到手里，再把这一轮的候选写进候选池，最后按输出格式给出结论。")
    return "\n".join(parts)


def _summarize(data: dict) -> str:
    """把模型的结论收敛成一句话写进步骤记录。"""
    rows = data.get("candidates")
    count = len(rows) if isinstance(rows, list) else 0
    note = str(data.get("relax_note") or "").strip()
    return f"模型给出候选 {count} 个" + (f"，放宽说明「{note}」" if note else "，没有放宽条件")


def _step_params(step: AgentStep) -> dict:
    """读步骤记录里这一次工具调用的入参。"""
    try:
        value = json.loads(step.request_params or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


async def _round_note(run_id: int | None, round_no: int) -> str | None:
    """这一轮真正写进候选池的放宽说明。

    以工具调用记录为准，不采信模型结论里另外报的那一份：写进库的那份是经过校验的，
    也是页面上要显示的那份，两边不一致时不能拿模型说的当数。
    """
    if not run_id:
        return None
    note = None
    steps = await AgentStep.filter(
        run_id=run_id, tool_code=SAVE_TOOL).order_by("step_index", "id")
    for step in steps:
        params = _step_params(step)
        # 以步骤记录上的调度轮次为准：save_candidates 落库的 found_round 已经是
        # context.round_no，步骤入参里的 found_round 仍是模型自报值，不能拿来对轮。
        effective = step.round_no or params.get("found_round")
        if effective != round_no:
            continue
        current = str(params.get("relax_note") or "").strip()
        if current:
            note = current
    return note


async def _prompt_values(member: MemberProfile, member_preference: RoommatePreference, *,
                         round_no: int, pool: int, deliver: int, history: list,
                         remaining: int, custom: str | None = None) -> dict:
    """组装这一轮的提示词变量。

    偏好走工具实现来读，和筛选官自己在循环里调工具读到的是同一份内容。
    """
    context = tool_box.ToolContext(member_id=member.id)
    preference = await tool_box.read_roommate_preference(context)
    # 合租只找同性，申请方性别放在偏好最前面：合租管家的交代里不一定写性别
    gender_line = (f"申请方性别：{member.gender}（合租只找同性，检索时 gender 传「{member.gender}」）"
                   if member.gender else "申请方性别：未填")
    return {
        "preference": gender_line + "\n" + preference_text(preference),
        "relax_history": relax_text(relaxable_dimensions(member_preference), history, remaining),
        "instruction": custom or instruction(member, round_no, pool, deliver),
    }


async def screen_round(member: MemberProfile, task_id: int, run_id: int, *, round_no: int,
                       history: list, deliver_count: int,
                       custom_instruction: str | None = None) -> ScreenRound:
    """跑一轮筛选：交给筛选官，产出写进候选池，再反查这一轮落了几条。

    一轮只做一轮的事，放宽几轮由调用方决定，这样调度层接进来时
    可以把「这一轮派谁、交代什么」放在自己手里。
    """
    member_preference = await RoommatePreference.get_or_none(member_id=member.id)
    if member_preference is None:
        raise CustomException(
            "还没有填合住偏好，请先到【合住偏好】把七个维度填好，平台才知道按什么条件找人")
    pool = await MatchCandidate.filter(task_id=task_id).count()
    limit = await tool_box.relax_limit()
    values = await _prompt_values(
        member, member_preference, round_no=round_no, pool=pool, deliver=deliver_count,
        history=history, remaining=max(limit - len(history), 0), custom=custom_instruction)
    context = tool_box.ToolContext(run_id=run_id, agent_code=AGENT_CODE, task_id=task_id,
                                   member_id=member.id, round_no=round_no)
    outcome = await agents.run_agent(
        AGENT_CODE, context,
        prompt_values=values,
        instruction=values["instruction"],
        required_tools=REQUIRED_TOOLS,
        summarize=_summarize)
    if outcome.gate:
        # 被闸拦下来：这一轮没有产出，把触发了哪道闸原样带回去
        return ScreenRound(round_no=round_no, gate=outcome.gate,
                           conclusion=outcome.conclusion, tool_calls=outcome.tool_calls)
    data = outcome.data or {}
    written = await MatchCandidate.filter(task_id=task_id, found_round=round_no).count()
    note = await _round_note(run_id, round_no)
    claimed = str(data.get("relax_note") or "").strip()
    mismatch = None
    if claimed and not note:
        mismatch = f"模型说放宽了「{claimed}」，但这一轮的放宽没有写进候选池"
    conclusion = f"第 {round_no} 轮新增候选 {written} 人" + (
        f"，放宽了「{note}」" if note else "，没有放宽条件")
    if mismatch:
        conclusion += f"；{mismatch}"
    return ScreenRound(round_no=round_no, written=written, note=note,
                       conclusion=conclusion, tool_calls=outcome.tool_calls,
                       mismatch=mismatch)


def _conclusion(rounds: list[ScreenRound], total: int, deliver_count: int) -> str:
    """把每一轮的结果拼成一句能直接显示的话。"""
    text = f"一共筛了 {len(rounds)} 轮，候选池累计 {total} 人"
    relaxed = [f"第 {item.round_no} 轮放宽了「{item.note}」" for item in rounds if item.note]
    if relaxed:
        text += "；" + "、".join(relaxed)
    # 模型报的放宽和库里对不上的地方一并写出来：这一类不写，只有翻步骤记录才看得出来
    mismatch = [f"第 {item.round_no} 轮：{item.mismatch}" for item in rounds if item.mismatch]
    if mismatch:
        text += "；" + "、".join(mismatch)
    if total >= deliver_count:
        return text + f"，已经达到交付要求的 {deliver_count} 人"
    if total:
        return (text + f"，还差 {deliver_count - total} 人；"
                f"要凑够可以到【合住偏好】把标为加分的条件再放宽一些，然后重新筛一次")
    return text + "，一位候选都没有筛出来"


async def build_candidates(member_id: int, task_id: int, run_id: int, *,
                           deliver_count: int,
                           custom_instruction: str | None = None) -> ScreenResult:
    """把一次筛选跑完：硬筛一轮，不够就一轮一轮放宽，直到够数或者放宽轮次用尽。

    每一轮单独交给筛选官一次，已经放宽过的说明带进下一轮的提示词。
    停下来的条件有三个：候选够交付人数了、放宽轮次用尽了、上一轮没有放宽——
    最后一种情况下再来一轮也还是同一批人，白跑一次。
    """
    member = await MemberProfile.get_or_none(id=member_id)
    if member is None:
        raise CustomException("没有找到这位租客的档案，请先让他把档案填好")
    member_preference = await RoommatePreference.get_or_none(member_id=member_id)
    if member_preference is None:
        raise CustomException(
            "还没有填合住偏好，请先到【合住偏好】把七个维度填好，平台才知道按什么条件找人")
    limit = await tool_box.relax_limit()
    # 一个能放宽的维度都没有时只跑硬筛那一轮：放宽轮没有条件可动，跑了也是白跑
    max_round = 1 + limit if relaxable_dimensions(member_preference) else 1
    history: list = []
    rounds: list[ScreenRound] = []
    round_no = 1
    while round_no <= max_round:
        pool = await MatchCandidate.filter(task_id=task_id).count()
        if round_no > 1 and pool >= deliver_count:
            break
        one = await screen_round(
            member, task_id, run_id, round_no=round_no, history=history,
            deliver_count=deliver_count,
            custom_instruction=custom_instruction if round_no == 1 else None)
        rounds.append(one)
        pool = await MatchCandidate.filter(task_id=task_id).count()
        if one.gate:
            return ScreenResult(rounds=rounds, total=pool, conclusion=one.conclusion,
                                gate=one.gate)
        if one.note:
            history.append((round_no, one.note))
        if pool >= deliver_count:
            break
        if not one.note and round_no > 1:
            # 已经放宽了一轮还是这几个人：再来一轮的条件和这一轮一样，白跑一次
            break
        round_no += 1
    total = await MatchCandidate.filter(task_id=task_id).count()
    return ScreenResult(rounds=rounds, total=total,
                        conclusion=_conclusion(rounds, total, deliver_count))


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


async def deliver_count() -> int:
    """一次匹配默认要交付几个人，从系统参数读，读坏了退回兜底值。"""
    raw = await config_service.get_value(DELIVER_KEY, str(DELIVER_DEFAULT))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DELIVER_DEFAULT
    return value if value > 0 else DELIVER_DEFAULT


async def readiness(member: MemberProfile | None) -> dict:
    """发起筛选之前要过的六项检查。

    按顺序一项一项看，第一项不满足就停下来：后面的几项在材料都不齐的时候
    也判断不出结果，列一屏红字不如只指一处。每一项的提示都写清去哪做什么。
    """
    checks: list[dict] = []

    def blocked(item: dict) -> dict:
        checks.append(item)
        return {"checks": checks, "blocker": item, "can_run": False}

    if member is None:
        return blocked(_check("profile", "租客档案", False,
                              "还没有填写租客档案，请先到【租客档案】把档案填好",
                              "/front/memberProfile", "去填写租客档案"))
    checks.append(_check("profile", "租客档案", True, f"昵称「{member.nickname}」"))

    member_preference = await RoommatePreference.get_or_none(member_id=member.id)
    if member_preference is None:
        return blocked(_check("preference", "合住偏好", False,
                              "还没有填合住偏好，筛选要按它来找人，请先到【合住偏好】填好",
                              "/front/myPreference", "去填写合住偏好"))
    checks.append(_check(
        "preference", "合住偏好", True,
        f"必须 {len(preference_service.must_dimensions(member_preference))} 项、"
        f"可放宽 {len(relaxable_dimensions(member_preference))} 项"))

    agent = await AgentDefinition.get_or_none(agent_code=AGENT_CODE)
    if agent is None:
        return blocked(_check("agent", "筛选官角色", False,
                              "平台没有找到筛选官角色，请联系管理员到【子 Agent 定义】核对"))
    if agent.enabled != "是":
        return blocked(_check("agent", "筛选官角色", False,
                              "筛选官已被停用，请联系管理员到【子 Agent 定义】把它启用"))
    checks.append(_check("agent", "筛选官角色", True, "筛选官已启用"))

    prompt = await PromptTemplate.get_or_none(code=agent.prompt_code)
    state = agent_service.prompt_state(prompt)
    if state != "正常":
        return blocked(_check("prompt", "提示词模板", False,
                              f"筛选官的提示词模板不可用（{state}），"
                              f"请联系管理员到【Prompt模板】处理"))
    checks.append(_check("prompt", "提示词模板", True, "提示词模板正常"))

    tool_count = await FunctionTool.filter(tool_group=agent.tool_group, enabled="是").count()
    if not tool_count:
        return blocked(_check("tool", "筛选工具", False,
                              f"筛选官的工具分组「{agent.tool_group}」下没有启用中的工具，"
                              f"请联系管理员到【工具中心】启用"))
    checks.append(_check("tool", "筛选工具", True, f"可用工具 {tool_count} 个"))

    config = await AiModelConfig.filter(
        model_purpose=model_factory.PURPOSE_SCREEN, enabled="是").order_by("-id").first()
    if config is None:
        return blocked(_check("model", "筛选模型", False,
                              "平台还没有启用「筛选」用途的对话模型，"
                              "请联系管理员到【AI模型配置】启用一条"))
    if not config.api_key:
        return blocked(_check("model", "筛选模型", False,
                              f"「{config.name}」还没有填写 API Key，"
                              f"请联系管理员到【AI模型配置】补上"))
    if not config.model_name:
        return blocked(_check("model", "筛选模型", False,
                              f"「{config.name}」还没有填写模型名称，"
                              f"请联系管理员到【AI模型配置】补上"))
    checks.append(_check("model", "筛选模型", True, f"已启用「{config.name}」"))
    return {"checks": checks, "blocker": None, "can_run": True}


async def _open_task(member: MemberProfile, count: int) -> MatchTask:
    """开一条匹配任务。单独筛选只跑到候选池，交付人数先记上，审核交给审核官。"""
    return await MatchTask.create(
        member_id=member.id,
        task_no=f"SCREEN-{now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}",
        deliver_count=count,
        status=TASK_RUNNING)


async def _open_run(member: MemberProfile, user_id: int, task: MatchTask,
                    count: int) -> AgentRun:
    """开一条运行记录。入参快照留着，运行失败之后能复现当时的输入。"""
    snapshot = json.dumps({
        "task_id": task.id,
        "task_no": task.task_no,
        "member_id": member.id,
        "nickname": member.nickname,
        "deliver_count": count,
    }, ensure_ascii=False)
    return await AgentRun.create(
        run_no=f"SCREEN-{now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}",
        task_id=task.id,
        user_id=user_id,
        run_type=RUN_TYPE,
        run_status=RUN_RUNNING,
        current_round=1,
        input_snapshot=snapshot,
        start_time=now())


async def _close_run(run: AgentRun, started, failed: bool, summary: str, rounds: int) -> None:
    """收尾运行记录：状态、最终结论、失败原因、耗时一次写全。"""
    await AgentRun.filter(id=run.id).update(
        run_status=RUN_FAILED if failed else RUN_DONE,
        total_round=rounds,
        output_summary=summary[:SUMMARY_LIMIT],
        error_message=summary[:ERROR_LIMIT] if failed else None,
        end_time=now(),
        cost_millis=cost_millis(started))


async def _close_task(task: MatchTask, status: str, rounds: int, error: str | None) -> None:
    """收尾任务：状态、用了几轮、失败原因。交付人数要等结果那一步才算得出来。"""
    await MatchTask.filter(id=task.id).update(
        status=status,
        total_round=rounds,
        error_message=(error or "")[:ERROR_LIMIT] or None)


async def generate(current_user: User) -> dict:
    """租客点一次【筛选候选】走的路：核对条件、开任务与运行、一轮轮流筛、收尾。"""
    member = await member_service.get_my_member(current_user, "筛选候选")
    state = await readiness(member)
    if not state["can_run"]:
        # 条件不满足就在这里停下，一步都不往模型走，也不留半条任务记录
        raise CustomException(state["blocker"]["message"])
    count = await deliver_count()
    started = precise_now()
    task = await _open_task(member, count)
    run = await _open_run(member, current_user.id, task, count)
    await MatchTask.filter(id=task.id).update(run_id=run.id)
    try:
        result = await build_candidates(member.id, task.id, run.id, deliver_count=count)
    except CustomException as exc:
        await _close_run(run, started, True, exc.message, 0)
        await _close_task(task, TASK_FAILED, 0, exc.message)
        raise
    if result.gate:
        message = (f"筛选被中断：{result.conclusion}。请稍后重试；"
                   f"如果每次都这样，请让管理员到【子 Agent 定义】检查筛选官的单次工具调用上限")
        await _close_run(run, started, True, message, len(result.rounds))
        await _close_task(task, TASK_FAILED, len(result.rounds), message)
        raise CustomException(message)
    if result.total == 0:
        message = (f"{result.conclusion}。可以到【合住偏好】把标为必须的条件放宽一些再筛一次；"
                   f"如果条件已经很宽，请让管理员确认租客库里有没有符合条件的人")
        await _close_run(run, started, True, message, len(result.rounds))
        await _close_task(task, TASK_FAILED, len(result.rounds), message)
        raise CustomException(message)
    await _close_run(run, started, False, result.conclusion, len(result.rounds))
    await _close_task(task, TASK_DONE, len(result.rounds), None)
    return {"task_id": task.id, "task_no": task.task_no, "rounds": len(result.rounds),
            "total": result.total, "conclusion": result.conclusion}


def task_dict(task: MatchTask) -> dict:
    """任务在页面上的样子。"""
    return {
        "id": task.id,
        "task_no": task.task_no,
        "status": task.status,
        "deliver_count": task.deliver_count,
        "total_round": task.total_round,
        "error_message": task.error_message,
        "create_time": format_datetime(task.create_time),
    }


def candidate_dict(row: MatchCandidate, member: MemberProfile | None) -> dict:
    """候选池里的一个人：挑页面要显示的字段，不给整行。

    候选人的档案查不到时照样返回这一行，另外带一句说明——
    页面上宁可显示一行「档案已经查不到」，也不要少一条让人对不上数。
    """
    data = {
        "id": row.id,
        "member_id": row.candidate_member_id,
        "found_round": row.found_round,
        "screen_score": row.screen_score,
        "relax_note": row.relax_note,
        "audit_status": row.audit_status,
        "create_time": format_datetime(row.create_time),
    }
    if member is None:
        data.update({"nickname": None, "missing": "这位租客的档案已经查不到了"})
        return data
    data.update({
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
        "interest_tags": split_values(member.interest_tags),
    })
    return data


async def _candidate_rows(task_id: int) -> list[dict]:
    """候选池列表：先按筛出来的轮次排，同一轮里初筛得分高的在前。"""
    rows = await MatchCandidate.filter(task_id=task_id).order_by(
        "found_round", "-screen_score", "id")
    if not rows:
        return []
    members = {item.id: item for item in await MemberProfile.filter(
        id__in=[row.candidate_member_id for row in rows])}
    return [candidate_dict(row, members.get(row.candidate_member_id)) for row in rows]


async def round_rows(task: MatchTask) -> list[dict]:
    """这一次筛选每一轮的放宽说明和新增人数。

    轮次从工具调用记录里取：一轮放宽了但一个候选也没筛到时，候选池里没有那一轮的行，
    可那一轮照样发生过，只从候选池里数会把这一轮漏掉。
    人数从候选池里数，两边对不上时以候选池为准。
    """
    if not task.run_id:
        return []
    notes: dict = {}
    steps = await AgentStep.filter(
        run_id=task.run_id, tool_code=SAVE_TOOL).order_by("step_index", "id")
    for step in steps:
        params = _step_params(step)
        # 轮次同样以步骤上的 round_no 为准，模型自报的 found_round 只在老数据里兜底
        found = step.round_no or params.get("found_round")
        if found is None:
            continue
        notes[found] = str(params.get("relax_note") or "").strip() or None
    counts: dict = {}
    for found in await MatchCandidate.filter(task_id=task.id).values_list(
            "found_round", flat=True):
        counts[found] = counts.get(found, 0) + 1
    result: list[dict] = []
    running = 0
    for round_no in sorted(set(notes) | set(counts)):
        running += counts.get(round_no, 0)
        result.append({
            "round": round_no,
            "relax_note": notes.get(round_no),
            "added": counts.get(round_no, 0),
            "total": running,
        })
    return result


async def my_page(current_user: User) -> dict:
    """租客端【候选结果】：最近一次任务的筛选轮次与候选列表。"""
    member_service.check_member_role(current_user)
    member = await MemberProfile.get_or_none(user_id=current_user.id)
    state = await readiness(member)
    if member is None:
        return {"has_profile": False, "readiness": state, "task": None,
                "rounds": [], "candidates": []}
    task = await MatchTask.filter(member_id=member.id).order_by("-id").first()
    if task is None:
        return {"has_profile": True, "readiness": state, "task": None,
                "rounds": [], "candidates": []}
    return {
        "has_profile": True,
        "readiness": state,
        "task": task_dict(task),
        "rounds": await round_rows(task),
        "candidates": await _candidate_rows(task.id),
    }


async def candidate_detail(current_user: User, candidate_id: int) -> dict:
    """看候选池里某个人的详情，走弹窗看，不跳新页面。

    只能看自己这次筛选筛出来的候选：拿别人的候选编号过来是取不到的。
    """
    member = await member_service.get_my_member(current_user, "查看候选详情")
    row = await MatchCandidate.get_or_none(id=candidate_id)
    if row is None:
        raise CustomException("没有找到这位候选，请刷新页面后重试")
    task = await MatchTask.get_or_none(id=row.task_id)
    if task is None or task.member_id != member.id:
        raise CustomException("这位候选不在你的候选池里，请从自己的候选池里打开")
    profile = await MemberProfile.get_or_none(id=row.candidate_member_id)
    data = candidate_dict(row, profile)
    if profile is not None:
        data["self_intro"] = profile.self_intro
        data["roommate_expectation"] = profile.roommate_expectation
    return data
