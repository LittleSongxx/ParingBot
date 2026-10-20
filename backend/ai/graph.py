"""合租管家调度图。

一次匹配就是主管和三个专职角色轮流交接：主管看一遍当前进展，决定下一步把活派给谁；
被派的角色干完一件事回到主管；主管再看一遍新的进展，直到它说收尾、或者调度轮次用尽。

    起点 → 主管 ─┬→ 画像师 ─┐
                 ├→ 筛选官 ─┼→ 回到主管
                 └→ 审核官 ─┘
                    └→ 终点

三个角色之间没有连线，所有交接都经过主管：谁该接下一步，只有主管说了算。
角色之间也不靠提示词传话——候选池、画像、审核结论各自落在表里，
主管每一轮从库里现查进展，下一个角色再从库里取自己要的那一份，
所以上一个角色的输出原文不需要塞进下一个角色的提示词。

状态刻意做得很薄：只放任务号、运行号、轮次，和这一轮派谁、给它的交代。
画像全文、候选清单这些留在库里不进状态，上下文就不会随轮数线性膨胀。

主管的输出是结构化 JSON，`next_agent` 只能是启用中的角色编码或者 FINISH。
取到别的值再给一次机会，第二次还是不行就整次运行判失败——代码替它挑一个角色，
等于把模型的决策悄悄换成代码的决策。
"""

from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from ai import agents, model_factory, prompt_loader
from ai import tools as tool_box
from common.exception_handler import CustomException
from common.times import precise_now
from models import (AgentDefinition, AgentStep, FunctionTool, MatchCandidate,
                    MatchTask, MemberPortrait, MemberProfile)
from service import (auditor_service, config_service, member_service, portrait_service,
                     screener_service)

# 收尾这个取值不在角色表里，它是主管自己的动作，不是某个角色；
# 取值由 agents 统一给出，调度时间线那一层按同一个值判断哪条记录是收尾
AGENT_FINISH = agents.AGENT_FINISH
# 调度轮数上限读这个参数
MAX_ROUND_KEY = "SUPERVISOR_MAX_ROUND"
MAX_ROUND_DEFAULT = 12
# 单次任务内补画像次数上限读这个参数
PORTRAIT_VERSION_KEY = "PORTRAIT_MAX_VERSION"
PORTRAIT_VERSION_DEFAULT = 2
# 主管输出不合规时最多再给一次机会，第二次还不行就整次运行判失败
MAX_CORRECT = 1
# 已经发生过的事最多回看几轮，防止进展文本自己越滚越长
HISTORY_LIMIT = 12
# 每一条历史结论在进展文本里的长度上限
HISTORY_TEXT_LIMIT = 160
# 从否决理由里摘维度名时，每条最多看多少字
REASON_SAMPLE_LIMIT = 80
# 两种收尾原因，写进运行记录的最后结论里
FINISH_ROUND_LIMIT = "调度轮次用尽"
FINISH_BY_SUPERVISOR = "主管判断可以收尾"


class MatchState(TypedDict):
    """图在各节点之间传递的状态。

    刻意做得很薄：角色的产出全部写数据库，状态里只放路由信息和一句话摘要。
    把画像全文、候选清单原文塞进状态的话，上下文会随轮数线性膨胀，
    跑到第七八轮就撑不住了。
    """

    task_id: int
    run_id: int
    # 当前是第几轮调度
    round_no: int
    # PORTRAIT / SCREENER / AUDITOR / FINISH
    next_agent: str
    # 主管给这一轮被派角色的交代
    instruction: str
    # 上一个角色返回的一句话结论
    last_summary: str
    # 收尾原因，写进 agent_run.output_summary
    finish_reason: str


def pool_counts(pool: list) -> dict:
    """候选池的四个数：一共多少、通过多少、否决多少、还挂着多少，外加否决分类。"""
    passed = len([row for row in pool if row.audit_status == tool_box.AUDIT_PASS])
    rejected = [row for row in pool if row.audit_status == tool_box.AUDIT_REJECT]
    codes: dict = {}
    for row in rejected:
        code = row.reject_code or "未分类"
        codes[code] = codes.get(code, 0) + 1
    return {"total": len(pool), "passed": passed, "rejected": len(rejected),
            "pending": len(pool) - passed - len(rejected), "codes": codes}


def _missing_dimensions(pool: list) -> list:
    """审核官判「画像不够」时点名的维度，去重后按出现顺序列出来。

    这些维度就是补画像该补的方向，主管照着它给画像师写交代。
    """
    names: list = []
    for row in pool:
        if row.reject_code != "PORTRAIT_INSUFFICIENT":
            continue
        reason = (row.reject_reason or "")[:REASON_SAMPLE_LIMIT]
        for name in tool_box.PORTRAIT_DIMENSIONS:
            if name in reason and name not in names:
                names.append(name)
    return names


async def _relax_history(task_id: int) -> list:
    """这个任务上已经放宽过哪几轮、每一轮放宽了什么，按轮次排好。

    放宽说明挂在筛出这位候选的那一轮上，同一个候选只算一次，
    所以按行去重就是按轮去重。
    """
    rows = await MatchCandidate.filter(
        task_id=task_id, relax_note__not_isnull=True).order_by("found_round")
    history: list = []
    for row in rows:
        note = (row.relax_note or "").strip()
        if note and all(item[0] != row.found_round for item in history):
            history.append((row.found_round, note))
    return history


async def _task_line(task: MatchTask, member: MemberProfile | None) -> str:
    """任务那一行：给谁匹配、要几个人。"""
    if member is None:
        return f"任务 {task.task_no}：发起匹配的租客档案已经查不到了"
    age = member_service.calc_age(member.birth_date)
    parts = [
        member.gender or "性别未填",
        f"{age} 岁" if age else "年龄未填",
        member_service.store_name(member.store_id) or "门店未填",
        member.schedule_type or "作息未填",
    ]
    return (f"为租客 #{member.id}（{'，'.join(parts)}）匹配，"
            f"要求交付 {task.deliver_count} 人")


async def _portrait_line(member: MemberProfile, run_id: int) -> str:
    """画像那一行：本次补了几版、最新一版在补什么维度。"""
    own = await MemberPortrait.filter(
        member_id=member.id, run_id=run_id).order_by("-version")
    if own:
        latest = own[0]
        text = f"本次已经补了 {len(own)} 版，最新一版是 v{latest.version}"
        if latest.focus_hint:
            text += f"（这一版重点补：{latest.focus_hint}）"
        return text
    earlier = await MemberPortrait.filter(
        member_id=member.id).order_by("-version").first()
    if earlier is None:
        return "还没有生成过画像，审核官会因为拿不到依据而否决候选"
    return f"本次还没有补过画像，现在用的是之前生成的 v{earlier.version}"


async def _role_lines() -> list:
    """主管能派的角色：只列启用中的，每个角色后面带上它手上真正可调的工具。

    工具名从注册表现查。停用某个角色，这里就没有它，主管也派不了它；
    停用一个工具，它就不出现在这一行里，模型看得见的是当前真实的手牌。
    """
    lines: list = []
    for role in await AgentDefinition.filter(enabled="是").order_by("sort", "id"):
        if role.agent_code == agents.AGENT_SUPERVISOR or not role.tool_group:
            continue
        tools = await FunctionTool.filter(
            tool_group=role.tool_group, enabled="是").order_by("sort", "id")
        names = "、".join(tool.tool_name for tool in tools) or "没有可用的工具"
        lines.append(f"{role.agent_code} {role.agent_name} —— 可调工具：{names}")
    lines.append(f"{AGENT_FINISH} 收尾 —— 结束本次匹配，把已经通过审核的候选交给租客")
    return lines


async def _history_lines(run_id: int) -> list:
    """已经发生过的事：每一个角色报过的一句话结论，按轮次排。

    取的是角色结论那一条步骤，不是主管的调度步骤——主管要看的是
    「上一轮那件事最后做成了什么样」，再据此决定下一步。
    """
    steps = await AgentStep.filter(
        run_id=run_id, step_type=agents.STEP_CONCLUSION).order_by("round_no", "step_index")
    if not steps:
        return ["还没有派过角色，这是第一轮调度"]
    names = {role.agent_code: role.agent_name for role in await AgentDefinition.all()}
    lines: list = []
    for step in steps[-HISTORY_LIMIT:]:
        text = agents.step_text(step.response_result)
        if len(text) > HISTORY_TEXT_LIMIT:
            text = text[:HISTORY_TEXT_LIMIT] + "……"
        lines.append(f"第 {step.round_no} 轮 {names.get(step.agent_code, step.agent_code)}：{text}")
    return lines


async def build_progress(task: MatchTask, run_id: int, round_no: int) -> str:
    """拼出主管这一轮看到的进展。

    全部现查数据库，不从上一轮的状态里往上堆：角色说它做了什么、
    库里到底有没有落下来，两者对不上时以库里为准。
    """
    member = await MemberProfile.get_or_none(id=task.member_id)
    pool = await MatchCandidate.filter(task_id=task.id)
    counts = pool_counts(pool)
    max_round = await config_service.get_int(MAX_ROUND_KEY, MAX_ROUND_DEFAULT)
    relax_limit = await tool_box.relax_limit()
    relax_used = len(await _relax_history(task.id))

    lines = ["【任务】", await _task_line(task, member), "", "【当前候选统计】",
             f"累计候选 {counts['total']} 人 / 已通过 {counts['passed']} 人 / "
             f"已否决 {counts['rejected']} 人 / 待审核 {counts['pending']} 人",
             f"距离交付要求还差 {max(task.deliver_count - counts['passed'], 0)} 人"]
    if counts["codes"]:
        detail = "、".join(
            f"{code} {count} 人（{auditor_service.reject_label(code) or '未分类'}）"
            for code, count in counts["codes"].items())
        lines.append(f"否决分类：{detail}")

    lines += ["", "【本次画像】",
              await _portrait_line(member, run_id) if member else "没有租客档案"]
    missing = _missing_dimensions(pool)
    lines.append("【审核官点名的缺失维度】" + ("、".join(missing) if missing else "还没有点名过"))

    lines += ["", "【你可以派的角色】"]
    lines += await _role_lines()

    lines += ["", "【已经发生的事】"]
    lines += await _history_lines(run_id)

    lines += ["", f"【已用调度轮次】{round_no} / 上限 {max_round}",
              f"【筛选官已放宽次数】{relax_used} / 上限 {relax_limit}"]
    return "\n".join(lines)


def _decision_problem(data, allowed: list) -> str | None:
    """主管这一轮的决定哪里不能用。没问题时返回空。"""
    if not isinstance(data, dict):
        return "输出不是一个 JSON 对象"
    code = str(data.get("next_agent") or "").strip()
    if not code:
        return "输出里没有 next_agent"
    if code not in allowed:
        return f"next_agent 是「{code}」，只能是 {'、'.join(allowed)} 之一"
    if code != AGENT_FINISH and not str(data.get("instruction") or "").strip():
        return "派角色的时候必须给出 instruction，说清这一轮要它做什么"
    return None


async def ask_supervisor(progress: str, context: tool_box.ToolContext) -> dict:
    """把当前进展交给主管，要它给出下一步派谁。

    主管不调工具，它只做一件事：读一遍进展，输出一个 JSON 决定。
    输出不合规再问一次，第二次还不合规就把这次运行判失败。
    """
    agent = await AgentDefinition.get_or_none(agent_code=agents.AGENT_SUPERVISOR)
    if agent is None:
        raise CustomException("平台没有找到合租管家角色，请联系管理员到【子 Agent 定义】核对")
    if agent.enabled != "是":
        raise CustomException("合租管家已经被停用，整次匹配跑不起来，请到【子 Agent 定义】把它启用")
    roles = await AgentDefinition.filter(enabled="是").order_by("sort", "id")
    allowed = [role.agent_code for role in roles
               if role.agent_code != agents.AGENT_SUPERVISOR] + [AGENT_FINISH]

    system_prompt = await prompt_loader.render(agent.prompt_code, progress=progress)
    config = await model_factory.load_for_purpose(model_factory.PURPOSE_SCHEDULE)
    model = model_factory.build_chat_model(config)
    messages = [SystemMessage(content=system_prompt)]

    for attempt in range(MAX_CORRECT + 1):
        try:
            response = await model.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001
            # 接口报错翻译成人话再往上抛，页面上的提示要能指到该改哪里
            raise CustomException(model_factory.translate_exception(exc))
        model_factory.check_truncated(response)
        data = agents.first_json_object(agents.message_text(response))
        problem = _decision_problem(data, allowed)
        if problem is None:
            return {
                "next_agent": str(data.get("next_agent")).strip(),
                "instruction": str(data.get("instruction") or "").strip(),
                "reason": str(data.get("reason") or "").strip(),
            }
        if attempt < MAX_CORRECT:
            messages.append(response)
            messages.append(HumanMessage(content=(
                f"上一次的输出不能用：{problem}。"
                f"请重新输出一个 JSON 对象，不要输出解释文字，不要加代码块标记。")))
            continue
        raise CustomException(
            f"合租管家连续两次没有给出可用的调度决定（{problem}），本次运行已经中断，请稍后重试；"
            f"如果每次都这样，请到【Prompt模板】检查主管的提示词里有没有写清输出格式")
    # 循环里每一轮都 return 或 raise，走到这里只可能是 MAX_CORRECT 配错了
    raise CustomException("调度决定的重试次数配置不正确，请检查代码里的重试上限")


def _context(state: MatchState, agent_code: str, member_id: int, round_no: int):
    """构造一次角色执行所处的运行环境，步骤记录挂在同一个运行上。"""
    return tool_box.ToolContext(run_id=state["run_id"], agent_code=agent_code,
                                task_id=state["task_id"], member_id=member_id,
                                round_no=round_no)


async def _role_blocked(context, round_no: int, agent_name: str, conclusion: str) -> dict:
    """角色在被派出去之前就被上限挡住了：写一条结论步骤，把原因带回主管。

    这里的写法和执行器里被闸拦下时一致——结论步骤落成失败状态，
    页面上这一条会标红，看的人一眼能分出「没干成」和「干完了」。
    """
    await agents.write_step(
        context, round_no, 1, agents.STEP_CONCLUSION,
        step_name=f"{agent_name}结论", request_params={"blocked": True},
        response_result=conclusion, step_status=agents.STEP_FAILED,
        error_message=conclusion, started=precise_now())
    return {"last_summary": conclusion}


async def supervisor_node(state: MatchState) -> dict:
    """主管节点：先把轮次加一，再决定下一步派谁或者收尾。

    轮次到顶就收尾，不再问模型——这是最后一道闸，问也只会拿到一个还想继续干的决定。
    """
    round_no = int(state.get("round_no") or 0) + 1
    max_round = await config_service.get_int(MAX_ROUND_KEY, MAX_ROUND_DEFAULT)
    if round_no > max_round:
        return {"round_no": round_no, "next_agent": AGENT_FINISH, "instruction": "",
                "finish_reason": FINISH_ROUND_LIMIT}

    task = await MatchTask.get_or_none(id=state["task_id"])
    if task is None:
        raise CustomException("这次运行挂着的匹配任务已经不存在了，请重新发起匹配")
    progress = await build_progress(task, state["run_id"], round_no)
    context = _context(state, agents.AGENT_SUPERVISOR, task.member_id, round_no)
    decision = await ask_supervisor(progress, context)
    await agents.write_step(
        context, round_no, 1, agents.STEP_SCHEDULE,
        step_name=f"第 {round_no} 轮调度", request_params=progress,
        response_result=decision, started=precise_now())
    finished = decision["next_agent"] == AGENT_FINISH
    return {"round_no": round_no, "next_agent": decision["next_agent"],
            "instruction": decision["instruction"],
            "finish_reason": FINISH_BY_SUPERVISOR if finished else ""}


async def portrait_node(state: MatchState) -> dict:
    """画像师节点：按主管的交代补一版画像，产出落在 member_portrait 上。

    补画像次数在派单前就拦一道：一次匹配最多补几版是系统参数说了算的，
    超了就不问了，直接把原因带回主管，让它换个角色或者收尾。
    """
    task = await MatchTask.get_or_none(id=state["task_id"])
    member = await MemberProfile.get_or_none(id=task.member_id) if task else None
    if member is None:
        raise CustomException("这次匹配的租客档案已经查不到了，请重新发起匹配")
    round_no = state["round_no"]
    context = _context(state, agents.AGENT_PORTRAIT, member.id, round_no)
    limit = await config_service.get_int(PORTRAIT_VERSION_KEY, PORTRAIT_VERSION_DEFAULT)
    made = await MemberPortrait.filter(run_id=state["run_id"]).count()
    if made >= limit:
        return await _role_blocked(
            context, round_no, "画像师",
            f"补画像次数已经用满（一次匹配最多补 {limit} 版），本次不能再派画像师了")
    result = await portrait_service.build_portrait(
        member.id, state["run_id"], round_no=round_no,
        focus_hint=(state.get("instruction") or "").strip() or None)
    return {"last_summary": result.conclusion}


async def screener_node(state: MatchState) -> dict:
    """筛选官节点：跑一轮筛选，候选写进 match_candidate。

    一轮只做一轮的事：放宽几轮、什么时候换角色，是主管每一轮重新决定的，
    不在这里一口气筛到够为止。
    """
    task = await MatchTask.get_or_none(id=state["task_id"])
    member = await MemberProfile.get_or_none(id=task.member_id) if task else None
    if member is None:
        raise CustomException("这次匹配的租客档案已经查不到了，请重新发起匹配")
    round_no = state["round_no"]
    result = await screener_service.screen_round(
        member, task.id, state["run_id"], round_no=round_no,
        history=await _relax_history(task.id), deliver_count=task.deliver_count,
        custom_instruction=(state.get("instruction") or "").strip() or None)
    return {"last_summary": result.conclusion}


async def auditor_node(state: MatchState) -> dict:
    """审核官节点：把候选池里还没有结论的人审完，结论回填在候选那一行上。

    一轮派单把待审的人全部审掉，这是审核官的整块活：
    分几批由它的工具调用上限算出来，不需要主管一批一批地派。
    """
    task = await MatchTask.get_or_none(id=state["task_id"])
    member = await MemberProfile.get_or_none(id=task.member_id) if task else None
    if member is None:
        raise CustomException("这次匹配的租客档案已经查不到了，请重新发起匹配")
    result = await auditor_service.build_audit(
        member.id, task.id, state["run_id"], round_no=state["round_no"],
        custom_instruction=(state.get("instruction") or "").strip() or None)
    return {"last_summary": result.conclusion}


def next_node(state: MatchState) -> str:
    """主管之后往哪走：它派谁就去谁那儿，说收尾就去终点。"""
    return state.get("next_agent") or AGENT_FINISH


def build_graph():
    """把四个节点和它们之间的边拼成一张图。

    起点的边指向主管，主管后面按 next_agent 分岔，三个角色后面一律回到主管。
    三个角色之间没有边，所以它们不可能绕过主管互相移交。
    """
    graph = StateGraph(MatchState)
    graph.add_node(agents.AGENT_SUPERVISOR, supervisor_node)
    graph.add_node(agents.AGENT_PORTRAIT, portrait_node)
    graph.add_node(agents.AGENT_SCREENER, screener_node)
    graph.add_node(agents.AGENT_AUDITOR, auditor_node)
    graph.add_edge(START, agents.AGENT_SUPERVISOR)
    graph.add_conditional_edges(agents.AGENT_SUPERVISOR, next_node, {
        agents.AGENT_PORTRAIT: agents.AGENT_PORTRAIT,
        agents.AGENT_SCREENER: agents.AGENT_SCREENER,
        agents.AGENT_AUDITOR: agents.AGENT_AUDITOR,
        AGENT_FINISH: END,
    })
    for agent_code in agents.SUB_AGENT_CODES:
        graph.add_edge(agent_code, agents.AGENT_SUPERVISOR)
    return graph.compile()


async def run_graph(task_id: int, run_id: int) -> MatchState:
    """把一次匹配交给这张图跑完，返回最后那个状态。"""
    max_round = await config_service.get_int(MAX_ROUND_KEY, MAX_ROUND_DEFAULT)
    state: MatchState = {"task_id": task_id, "run_id": run_id, "round_no": 0,
                         "next_agent": "", "instruction": "", "last_summary": "",
                         "finish_reason": ""}
    # 每一轮最多走两个节点（主管加一个角色），再留几步收尾。
    # 这个上限不放宽的话，轮次上限还没到，图自己的步数上限就先把它拦下来了
    return await build_graph().ainvoke(state, {"recursion_limit": max_round * 2 + 5})
