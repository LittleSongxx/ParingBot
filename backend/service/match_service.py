"""智能匹配业务逻辑。

租客点一次【重新智能匹配】走的路：

    核对前置条件（档案、偏好、动态、模型配置、各个角色与工具）
      → 全过了才动数据：开一条匹配任务和一条运行记录
      → 把活交给主管调度，主管每一轮决定派谁
      → 跑完代码重算一遍收尾：可以交付的候选为 0 就判失败

三条规则写在这里：

1. 前置条件全过之前，一条旧数据都不许删。一个「API Key 没填」就把上一次的匹配成果
   白删掉，是返工过的错法：校验放在清数据的后面，用户就要为一次没跑起来的运行付代价。
2. 轮数、放宽次数、补画像次数这些闸门全部读系统参数，管理员改完立刻生效。
3. 页面上的数字全部现查数据库。主管说有几个人通过不作数，
   要从 match_candidate 里数出来才算。

主管调度本身写在 ai/graph.py：本文件负责它前面和后面的两段，
以及把一次运行的过程和结果摊平成页面要的结构。
"""

import asyncio
import json
from uuid import uuid4

from tortoise.transactions import in_transaction

from ai import agents, graph, model_factory
from ai import tools as tool_box
from common.exception_handler import CustomException
from common.times import cost_millis, now, precise_now
from models import (AgentDefinition, AgentRun, AgentStep, AiModelConfig, FunctionTool,
                    MatchCandidate, MatchTask, MemberMoment, MemberProfile,
                    PromptTemplate, RoommatePreference, User)
from service import (agent_service, auditor_service, config_service, member_service,
                     preference_service, screener_service)
from settings import MATCH_TIMEOUT_SECONDS

# 运行类型，一次匹配编排对应一条运行记录
RUN_TYPE = "匹配编排"
# 任务编号与运行编号的前缀
NO_PREFIX = "MATCH"
# 匹配任务的状态流转
TASK_PENDING = "待执行"
TASK_RUNNING = "执行中"
TASK_DONE = "已完成"
TASK_FAILED = "执行失败"
# 运行记录的状态流转
RUN_RUNNING = "运行中"
RUN_DONE = "已完成"
RUN_FAILED = "运行失败"
# 收尾时写库前的长度上限
SUMMARY_LIMIT = 2000
ERROR_LIMIT = 500
# 中断的原因，也是页面上给租客的下一步指示
INTERRUPT_REASON = "服务重启，这次运行已经中断，请重新发起匹配"


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


async def readiness(member: MemberProfile | None) -> dict:
    """发起匹配之前要过的检查。

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

    intro = (member.self_intro or "").strip()
    if not intro:
        return blocked(_check(
            "intro", "自我介绍", False,
            "自我介绍还是空的，画像师要读它才能提炼标签，请先到【租客档案】补上",
            "/front/memberProfile", "去补充自我介绍"))
    checks.append(_check("intro", "自我介绍", True, f"{len(intro)} 个字"))

    preference = await RoommatePreference.get_or_none(member_id=member.id)
    if preference is None:
        return blocked(_check(
            "preference", "合住偏好", False,
            "还没有填合住偏好，筛选官要按它找人，请先到【合住偏好】填好",
            "/front/myPreference", "去填写合住偏好"))
    checks.append(_check(
        "preference", "合住偏好", True,
        f"必须 {len(preference_service.must_dimensions(preference))} 项、"
        f"可放宽 {len(screener_service.relaxable_dimensions(preference))} 项"))

    moments = await MemberMoment.filter(member_id=member.id).count()
    if not moments:
        return blocked(_check(
            "moment", "租客动态", False,
            "还没有发过动态，画像师是从动态原文里提炼标签的，请先到【我的动态】发一条",
            "/front/myMoment", "去发布动态"))
    checks.append(_check("moment", "租客动态", True, f"{moments} 条"))

    roles = await AgentDefinition.filter(enabled="是").order_by("sort", "id")
    codes = [role.agent_code for role in roles]
    if agents.AGENT_SUPERVISOR not in codes:
        return blocked(_check(
            "supervisor", "合租管家", False,
            "合租管家已经被停用，没有它就没有人决定下一步派谁，匹配无法进行。"
            "请联系管理员到【子 Agent 定义】把它启用"))
    if agents.AGENT_SCREENER not in codes:
        return blocked(_check(
            "screener", "筛选官", False,
            "筛选官已经被停用，没有它就没有候选可选，匹配无法进行。"
            "请联系管理员到【子 Agent 定义】把它启用"))

    for role in roles:
        prompt = await PromptTemplate.get_or_none(code=role.prompt_code)
        state = agent_service.prompt_state(prompt)
        if state != "正常":
            return blocked(_check(
                f"prompt_{role.agent_code}", f"{role.agent_name}提示词", False,
                f"{role.agent_name}绑定的提示词当前是「{state}」，"
                f"执行到它那一步会取不到提示词，"
                f"请联系管理员到【Prompt模板】改成启用且内容非空"))
        if role.agent_code == agents.AGENT_SUPERVISOR:
            checks.append(_check(f"prompt_{role.agent_code}", role.agent_name, True, "提示词正常"))
            continue
        tool_count = await FunctionTool.filter(
            tool_group=role.tool_group, enabled="是").count()
        if not tool_count:
            return blocked(_check(
                f"tool_{role.agent_code}", f"{role.agent_name}工具", False,
                f"{role.agent_name}的工具分组「{role.tool_group or '未设置'}」下没有启用中的工具，"
                f"它接不到任何工具就干不了活，请联系管理员到【工具中心】启用"))
        checks.append(_check(f"tool_{role.agent_code}", role.agent_name, True,
                             f"提示词正常，可用工具 {tool_count} 个"))

    config = await AiModelConfig.filter(
        model_purpose=model_factory.PURPOSE_SCHEDULE, enabled="是").order_by("-id").first()
    if config is None:
        return blocked(_check(
            "model", "调度模型", False,
            "平台还没有启用「调度」用途的对话模型，主管理不了事，"
            "请联系管理员到【AI模型配置】启用一条"))
    if not config.api_key:
        return blocked(_check("model", "调度模型", False,
                              f"「{config.name}」还没有填写 API Key，"
                              f"请联系管理员到【AI模型配置】补上"))
    if not config.model_name:
        return blocked(_check("model", "调度模型", False,
                              f"「{config.name}」还没有填写模型名称，"
                              f"请联系管理员到【AI模型配置】补上"))
    checks.append(_check("model", "调度模型", True, f"已启用「{config.name}」"))

    chat_ready = await AiModelConfig.filter(enabled="是").exclude(
        api_key=None).exclude(api_key="").count()
    if not chat_ready:
        return blocked(_check(
            "chat", "对话模型", False,
            "平台没有一条填好 API Key 的启用中对话模型，子 Agent 的请求发不出去，"
            "请联系管理员到【AI模型配置】补上"))
    checks.append(_check("chat", "对话模型", True, f"{chat_ready} 条可用"))
    return {"checks": checks, "blocker": None, "can_run": True}


async def _open_task(member: MemberProfile, deliver: int) -> MatchTask:
    """开一条匹配任务。一次发起对应一条任务，编号带上发起时间。"""
    return await MatchTask.create(
        member_id=member.id,
        task_no=f"{NO_PREFIX}-{now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}",
        deliver_count=deliver,
        status=TASK_PENDING)


async def _open_run(member: MemberProfile, user_id: int, task: MatchTask) -> AgentRun:
    """开一条运行记录。入参快照留着，运行失败之后能复现当时的输入。"""
    snapshot = json.dumps({
        "task_id": task.id,
        "task_no": task.task_no,
        "member_id": member.id,
        "nickname": member.nickname,
        "deliver_count": task.deliver_count,
    }, ensure_ascii=False)
    return await AgentRun.create(
        run_no=f"{NO_PREFIX}-{now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}",
        task_id=task.id,
        user_id=user_id,
        run_type=RUN_TYPE,
        run_status=RUN_RUNNING,
        current_round=0,
        input_snapshot=snapshot,
        start_time=now())


async def _count_rounds(run_id: int) -> int:
    """这次运行实际调度了几轮，从步骤表里数出来。

    轮数不放在内存变量里：运行中断之后重看这条记录，数出来的还是真实的轮次，
    不会因为进程重启就从 0 重新开始。
    """
    return await AgentStep.filter(run_id=run_id, agent_code=agents.AGENT_SUPERVISOR,
                                  step_type=agents.STEP_SCHEDULE).count()


async def _close(run: AgentRun, task: MatchTask, started, ok: bool, summary: str,
                 rounds: int, delivered: int = 0) -> None:
    """收尾：运行记录和匹配任务在同一条事务里一次写全。

    两张表的状态必须一起变：只写了一张就中途崩掉，会出现「运行已失败、
    任务还挂在执行中」的半截状态，页面上的状态机就对不上了。
    """
    async with in_transaction():
        await AgentRun.filter(id=run.id).update(
            run_status=RUN_DONE if ok else RUN_FAILED,
            current_round=rounds,
            total_round=rounds,
            output_summary=summary[:SUMMARY_LIMIT],
            error_message=None if ok else summary[:ERROR_LIMIT],
            end_time=now(),
            cost_millis=cost_millis(started))
        await MatchTask.filter(id=task.id).update(
            status=TASK_DONE if ok else TASK_FAILED,
            total_round=rounds,
            delivered_count=delivered,
            error_message=None if ok else summary[:ERROR_LIMIT])


async def deliverable(task_id: int) -> tuple[list, str | None]:
    """这次匹配最终能交付哪些候选，以及要顺带说明的一句话。

    审核官启用时只算通过审核的那些；审核官被停用时，候选池里的人没有经过审核这一环，
    按全部可交付处理，并把这件事写进结论——页面上不能让人以为审核做过了。

    调度时间线与候选漏斗那一页也要用这一条口径，所以它是公开的：
    同一个「通过」在两处按两种算法数，页面上的数字迟早对不上。
    """
    auditor = await AgentDefinition.get_or_none(agent_code=agents.AGENT_AUDITOR)
    rows = await MatchCandidate.filter(task_id=task_id).order_by("id")
    if auditor is None or auditor.enabled != "是":
        return list(rows), "审核官已停用，本次候选没有经过反向审核，按候选池里的全部交付"
    return [row for row in rows if row.audit_status == tool_box.AUDIT_PASS], None


def _summary(final: dict, counts: dict, rounds: int, task: MatchTask,
             delivered: int, note: str | None) -> str:
    """把这次运行的结果拼成一句能直接显示、也能直接写库的话。"""
    parts = [f"调度 {rounds} 轮，候选池累计 {counts['total']} 人，"
             f"通过审核 {counts['passed']} 人，否决 {counts['rejected']} 人，"
             f"交付 {delivered} 人（要求 {task.deliver_count} 人）"]
    reason = (final.get("finish_reason") or "").strip()
    if reason:
        parts.append(f"收尾原因：{reason}")
    if note:
        parts.append(note)
    last = (final.get("last_summary") or "").strip()
    if last:
        parts.append(f"最后一次交接：{last}")
    return "；".join(parts)


async def execute_task(task_id: int, run_id: int) -> None:
    """后台执行已经创建好的任务；结果和失败原因全部写库，供页面轮询读取。

    收尾不采信主管和审核官说了什么：可以交付的候选从候选池里现数，
    一个都没有就判失败——页面显示「匹配成功」而库里是空的，是返工过的错法。
    整次运行有总时限（settings.MATCH_TIMEOUT_SECONDS），超过就中断并按失败收尾，
    不让页面一直挂着一个转不完的圈。
    """
    started = precise_now()
    task = await MatchTask.get_or_none(id=task_id)
    run = await AgentRun.get_or_none(id=run_id)
    if task is None or run is None:
        return
    try:
        final = await asyncio.wait_for(
            graph.run_graph(task.id, run.id), timeout=MATCH_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        # 整次运行超过系统参数里的时限：中断并按失败收尾，给租客一句能照做的下一步
        message = (f"本次匹配运行超时（超过 {MATCH_TIMEOUT_SECONDS} 秒）已中断，"
                   f"请稍后重新发起")
        await _close(run, task, started, False, message, await _count_rounds(run.id))
        return
    except CustomException as exc:
        await _close(run, task, started, False, exc.message, await _count_rounds(run.id))
        return
    except Exception:  # noqa: BLE001
        # 兜住没预料到的异常。写进运行记录的是一句能照做的话：
        # 底层异常原文是英文，直接放进结论列用户看不懂，也指不出下一步
        reason = ("调度过程中出现未预期的错误。请稍后重试；"
                  "如果一直失败，请把这次操作告诉管理员")
        await _close(run, task, started, False, reason, await _count_rounds(run.id))
        return

    rows = await MatchCandidate.filter(task_id=task.id)
    counts = graph.pool_counts(rows)
    rounds = await _count_rounds(run.id)
    passed_rows, note = await deliverable(task.id)
    delivered = min(len(passed_rows), task.deliver_count)
    summary = _summary(final, counts, rounds, task, delivered, note)
    if not passed_rows:
        message = (f"本次没有可以交付的候选。{summary}。"
                   f"可以到【合住偏好】把标为必须的条件放宽一些再试一次，"
                   f"或者让管理员确认租客库里有没有符合条件的人")
        await _close(run, task, started, False, message, rounds)
        return
    await _close(run, task, started, True, summary, rounds, delivered)


async def rerun(current_user: User) -> dict:
    """创建后台匹配任务并立即返回，实际调度由接口注册到后台执行。"""
    member = await member_service.get_my_member(current_user, "重新匹配")
    state = await readiness(member)
    if not state["can_run"]:
        raise CustomException(state["blocker"]["message"])
    deliver = await screener_service.deliver_count()
    # 从「查有没有在跑」到「建任务、建运行、把任务改成执行中」放在同一条事务里：
    # 同一账号连点两次时只有一笔能落下来，不会出现两个后台任务并行跑
    async with in_transaction():
        user = await User.filter(id=current_user.id).select_for_update().first()
        if user is None:
            raise CustomException("当前账号已经不存在，请重新登录后再试")
        running = await AgentRun.filter(
            user_id=user.id, run_type=RUN_TYPE, run_status=RUN_RUNNING
        ).order_by("-id").first()
        if running is not None:
            running_task = await MatchTask.get_or_none(id=running.task_id)
            return {
                "task_id": running.task_id,
                "task_no": running_task.task_no if running_task else None,
                "run_id": running.id,
                "run_no": running.run_no,
                "already_running": True,
                "message": "智能匹配正在后台执行，请稍后查看实时进度",
            }
        # 每次用当前档案、偏好和动态开一条新的 MATCH-* 任务。
        # 三个子 Agent 页面按最新任务展示；旧任务仍留库用于运行记录追溯。
        task = await _open_task(member, deliver)
        run = await _open_run(member, user.id, task)
        await MatchTask.filter(id=task.id).update(
            run_id=run.id, status=TASK_RUNNING, delivered_count=0,
            total_round=0, error_message=None)
        return {
            "task_id": task.id,
            "task_no": task.task_no,
            "run_id": run.id,
            "run_no": run.run_no,
            "already_running": False,
            "message": "智能匹配已转入后台执行，可以离开页面，回来后会继续显示进度",
        }


async def round_rows(run_id: int | None) -> list[dict]:
    """调度过程：每一轮派了谁、主管的判断依据、这一轮的结论。

    按轮次把步骤记录归拢起来：同一个调度轮里，主管的调度步骤在最前，
    接着是那个角色自己写的工具调用和结论步骤。页面上的时间线就是这一份的分层展开。
    """
    if not run_id:
        return []
    steps = await AgentStep.filter(run_id=run_id).order_by("round_no", "step_index")
    names = {role.agent_code: role.agent_name for role in await AgentDefinition.all()}
    rows: dict = {}
    order: list = []
    for step in steps:
        round_no = step.round_no or 0
        if round_no not in rows:
            rows[round_no] = {"round": round_no, "agent_code": None, "agent_name": None,
                              "instruction": None, "reason": None, "conclusion": None,
                              "tool_calls": 0, "failed": False}
            order.append(round_no)
        row = rows[round_no]
        if step.step_type == agents.STEP_SCHEDULE:
            decision = agents.step_json(step.response_result)
            row["agent_code"] = str(decision.get("next_agent") or "") or row["agent_code"]
            row["agent_name"] = names.get(row["agent_code"], row["agent_code"])
            row["instruction"] = decision.get("instruction") or None
            row["reason"] = decision.get("reason") or None
        elif step.step_type == agents.STEP_TOOL:
            row["tool_calls"] += 1
        elif step.step_type == agents.STEP_CONCLUSION:
            row["conclusion"] = agents.step_text(step.response_result) or None
            if step.step_status == agents.STEP_FAILED:
                row["failed"] = True
    return [rows[round_no] for round_no in order]


async def limits() -> dict:
    """页面上要显示的三个上限，全部现查系统参数。"""
    return {
        "round_limit": await config_service.get_int(graph.MAX_ROUND_KEY, graph.MAX_ROUND_DEFAULT),
        "relax_limit": await tool_box.relax_limit(),
        "portrait_limit": await config_service.get_int(
            graph.PORTRAIT_VERSION_KEY, graph.PORTRAIT_VERSION_DEFAULT),
    }


async def my_page(current_user: User) -> dict:
    """租客端【智能匹配】：条件核对、最近一次运行、调度过程、候选统计。"""
    member_service.check_member_role(current_user)
    member = await MemberProfile.get_or_none(user_id=current_user.id)
    state = await readiness(member)
    empty = {"has_profile": member is not None, "readiness": state, "task": None,
             "run": None, "rounds": [], "note": None, "delivered": 0,
             "counts": {"total": 0, "passed": 0, "rejected": 0, "pending": 0},
             "distribution": auditor_service.distribution([]),
             "limits": await limits()}
    if member is None:
        return empty
    # 智能匹配页只展示“匹配编排”产生的任务，按运行类型锁定数据范围。
    run = await AgentRun.filter(
        user_id=current_user.id, run_type=RUN_TYPE).order_by("-id").first()
    if run is None or run.task_id is None:
        return empty
    task = await MatchTask.get_or_none(id=run.task_id, member_id=member.id)
    if task is None:
        return empty
    rows = await MatchCandidate.filter(task_id=task.id).order_by("id")
    counts = graph.pool_counts(rows)
    passed_rows, note = await deliverable(task.id)
    return {
        "has_profile": True,
        "readiness": state,
        "task": screener_service.task_dict(task),
        "run": auditor_service.run_dict(run),
        "rounds": await round_rows(run.id if run else None),
        "note": note,
        "delivered": min(len(passed_rows), task.deliver_count),
        "counts": {"total": counts["total"], "passed": counts["passed"],
                   "rejected": counts["rejected"], "pending": counts["pending"]},
        "distribution": auditor_service.distribution(
            [{"reject_code": row.reject_code} for row in rows]),
        "limits": await limits(),
    }


async def recover_unfinished() -> int:
    """服务启动时把上一次没跑完的运行收尾。

    进程被关掉、机器断电这一类情况下，运行记录会一直停在「运行中」，
    页面上就永远挂着一个转不完的圈，发起人不知道到底跑完了没有。
    启动时统一改成失败并写清原因，看到的人下一步该做什么是明确的。
    """
    runs = await AgentRun.filter(run_status=RUN_RUNNING)
    if not runs:
        return 0
    task_ids = [run.task_id for run in runs if run.task_id]
    if task_ids:
        await MatchTask.filter(id__in=task_ids, status=TASK_RUNNING).update(
            status=TASK_FAILED, error_message=INTERRUPT_REASON)
    await AgentRun.filter(id__in=[run.id for run in runs]).update(
        run_status=RUN_FAILED, end_time=now(),
        output_summary=INTERRUPT_REASON, error_message=INTERRUPT_REASON)
    return len(runs)
