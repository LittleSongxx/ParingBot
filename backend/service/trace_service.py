"""Agent 调度时间线与候选漏斗的业务逻辑。

页面上两个视图的数据都来自过程表，这一层只读，不改动任何业务数据：

    调度时间线    agent_step 的 agent_code + step_type 两列，按轮次分组摊开
    候选漏斗      match_candidate 的 audit_status 逐级往下数

三条口径：

1. 每个数字都现查数据库。运行记录里那句结论文字只当说明用，不当数据源——
   它是运行当时写下的，事后候选池被改过，那句话上的数字就对不上了。
2. 漏斗的每一级都是实打实数出来的，页面上只呈现数字，不贴统计口径和表名。
3. 只有挂着匹配任务的运行才有漏斗；没有任务时页面显示原因，不绘制全 0 漏斗。
"""

from ai import agents
from ai import tools as tool_box
from common.exception_handler import CustomException
from common.result import PageInfo
from common.times import format_datetime
from models import (AgentDefinition, AgentRun, AgentStep, FunctionTool, MatchCandidate,
                    MatchTask, MemberProfile)
from service import match_service

# 一页最多返回多少条，防止前端一次把整张表拉走
MAX_PAGE_SIZE = 50
# 漏斗四级的编码，前端按这个顺序渲染
STAGE_TOTAL = "total"
STAGE_REJECT = "rejected"
STAGE_PASS = "passed"
STAGE_DELIVER = "delivered"


async def _agent_names() -> dict[str, str]:
    """角色编码到角色名的对照，步骤表里存的是编码。"""
    return {row.agent_code: row.agent_name for row in await AgentDefinition.all()}


async def _tool_names() -> dict[str, str]:
    """工具编码到工具名的对照，步骤表里存的是编码。"""
    return {row.tool_code: row.tool_name for row in await FunctionTool.all()}


def _ratio(value: int, base: int) -> float:
    """这一级占筛出总数的百分比，保留一位小数。没有筛出人时返回 0。"""
    return round(value * 100 / base, 1) if base else 0.0


def _stage(key: str, label: str, value: int, base: int, desc: str) -> dict:
    """漏斗的一级：人数、占筛出总数的比例、一句人话说明。"""
    return {"key": key, "label": label, "value": value,
            "ratio": _ratio(value, base), "desc": desc}


async def funnel(task_id: int | None) -> dict:
    """一次匹配的候选漏斗：筛出 → 否决 → 通过 → 交付。

    「通过」这一级按审核官是否启用来定：审核官启用时只数审过且通过的；
    它被停用时候选池里的人没有经过审核这一环，按候选池全部可交付算，
    并把这件事写成说明——不写的话，页面上看着和「审核通过」是一回事。
    """
    stopped = {"available": False, "stages": [], "notes": [], "deliver_count": 0}
    if not task_id:
        return {**stopped,
                "reason": "这次运行没有关联匹配任务，因此没有候选漏斗"}
    task = await MatchTask.get_or_none(id=task_id)
    if task is None:
        return {**stopped,
                "reason": "这次运行挂着的匹配任务已经不在了，请刷新列表后重新挑一条运行"}

    rows = await MatchCandidate.filter(task_id=task.id)
    total = len(rows)
    approved = sum(1 for row in rows if row.audit_status == tool_box.AUDIT_PASS)
    rejected = sum(1 for row in rows if row.audit_status == tool_box.AUDIT_REJECT)
    # 待审核的人既不算通过也不算否决，说清楚他们的去向，两个数字才加得起来
    pending = total - approved - rejected
    # 漏斗的「通过/交付」和运行总结、租客页读同一份交付名单：
    # 审核官启用时还要过当前硬规则复核，历史误判的「通过」不计入
    passed_rows, note = await match_service.deliverable(task.id)
    passed = len(passed_rows)
    delivered = min(passed, task.deliver_count)
    auditor = await AgentDefinition.get_or_none(agent_code=agents.AGENT_AUDITOR)
    audited = auditor is not None and auditor.enabled == "是"

    stages = [
        _stage(STAGE_TOTAL, "筛出", total, total,
               "筛选官写进候选池的人数，含后面被否决的和还没审的"),
        _stage(STAGE_REJECT, "否决", rejected, total,
               "审核官站在候选人那一方重新看一遍，判为不合适的"),
        _stage(STAGE_PASS, "通过", passed, total,
               "通过审核、且按当前规则复核得上的" if audited
               else "审核官已停用，候选池里未否决的人按可交付算（待审核也计入）"),
        _stage(STAGE_DELIVER, "交付", delivered, total,
               f"最终交到发起人手上的，最多不超过要求的 {task.deliver_count} 人"),
    ]
    notes = [note] if note else []
    # 审核官启用时，待审核的人既不算通过也不算否决，要说清他们的去向，
    # 两个数字才加得起来；停用时这些人已经算进「通过」了，再说一句就自相矛盾
    if pending and audited:
        notes.append(f"还有 {pending} 人停在待审核：这次运行没有审到他们，"
                     f"所以他们既不算通过也不算否决")
    return {"available": True, "task_id": task.id, "task_no": task.task_no,
            "deliver_count": task.deliver_count, "total": total, "rejected": rejected,
            "approved": approved, "pending": pending, "audited": audited,
            "stages": stages, "notes": notes, "reason": None}


def step_dict(step: AgentStep, names: dict[str, str], tools: dict[str, str]) -> dict:
    """时间线上的一个节点：谁、在做什么、做的结果、花了多久。"""
    return {
        "id": step.id,
        "round_no": step.round_no,
        "step_index": step.step_index,
        "agent_code": step.agent_code,
        "agent_name": names.get(step.agent_code or "") or step.agent_code,
        "step_type": step.step_type,
        "step_name": step.step_name,
        "tool_code": step.tool_code,
        "tool_name": tools.get(step.tool_code or "") or step.tool_code,
        "step_status": step.step_status,
        "error_message": step.error_message,
        "request_params": step.request_params,
        "response_result": step.response_result,
        "cost_millis": step.cost_millis,
        "start_time": format_datetime(step.start_time or step.create_time),
    }


async def timeline(run_id: int) -> list[dict]:
    """一次运行的时间线：按轮次分组，每轮里按步骤顺序摊开。

    每轮的第一条是主管的调度步骤，从它的返回里解出这一轮派给了谁、
    交代了什么、为什么这么派；后面几条是那个角色自己写的工具调用和结论。
    三个角色之间没有连线，所以每一轮走到谁那儿，都是主管上一条记录说了算的。
    """
    steps = await AgentStep.filter(run_id=run_id).order_by("round_no", "step_index", "id")
    if not steps:
        return []
    names = await _agent_names()
    tools = await _tool_names()
    rounds: dict[int, dict] = {}
    order: list[int] = []
    for step in steps:
        no = int(step.round_no or 0)
        if no not in rounds:
            rounds[no] = {"round": no, "agent_code": "", "agent_name": "",
                          "instruction": None, "reason": None, "finished": False,
                          "scheduled": False,
                          "tool_calls": 0, "failed": 0, "cost_millis": 0, "steps": []}
            order.append(no)
        one = rounds[no]
        one["steps"].append(step_dict(step, names, tools))
        one["cost_millis"] += step.cost_millis or 0
        if step.step_status == agents.STEP_FAILED:
            one["failed"] += 1
        if step.step_type == agents.STEP_SCHEDULE:
            decision = agents.step_json(step.response_result)
            one["scheduled"] = True
            one["agent_code"] = str(decision.get("next_agent") or "") or one["agent_code"]
            one["agent_name"] = names.get(one["agent_code"], one["agent_code"])
            one["instruction"] = decision.get("instruction") or None
            one["reason"] = decision.get("reason") or None
            one["finished"] = one["agent_code"] == agents.AGENT_FINISH
        elif step.step_type == agents.STEP_TOOL:
            one["tool_calls"] += 1
    lines = [rounds[no] for no in order]
    for one in lines:
        # 没有主管派单信息时，按这一轮第一步的角色署名
        if not one["agent_code"] and one["steps"]:
            one["agent_code"] = one["steps"][0]["agent_code"]
            one["agent_name"] = one["steps"][0]["agent_name"]
    return lines


def _step_stat(rounds: list[dict]) -> dict:
    """时间线的小计，放在弹窗顶部。"""
    steps = [step for one in rounds for step in one["steps"]]

    def count(step_type: str) -> int:
        return sum(1 for step in steps if step["step_type"] == step_type)

    return {
        "rounds": len(rounds),
        "steps": len(steps),
        "schedule": count(agents.STEP_SCHEDULE),
        "tool_calls": count(agents.STEP_TOOL),
        "conclusions": count(agents.STEP_CONCLUSION),
        "failed": sum(1 for step in steps if step["step_status"] == agents.STEP_FAILED),
        "cost_millis": sum(step["cost_millis"] or 0 for step in steps),
    }


def _run_line(run: AgentRun, task: MatchTask | None, member: MemberProfile | None) -> dict:
    """运行列表里的一行。挂着的任务和租客查不到时这一栏留空，不少返回一条。"""
    return {
        "id": run.id,
        "run_no": run.run_no,
        "run_type": run.run_type,
        "run_status": run.run_status,
        "current_round": run.current_round,
        "total_round": run.total_round,
        "cost_millis": run.cost_millis,
        "task_id": run.task_id,
        "task_no": task.task_no if task else None,
        "nickname": member.nickname if member else None,
        "error_message": run.error_message,
        "start_time": format_datetime(run.start_time or run.create_time),
        "end_time": format_datetime(run.end_time),
    }


async def run_options() -> dict:
    """筛选用的下拉：运行类型和运行状态。取值从库里现查，页面上不写死。"""
    rows = await AgentRun.all().values_list("run_type", "run_status")
    return {
        "run_types": sorted({row[0] for row in rows if row[0]}),
        "run_statuses": sorted({row[1] for row in rows if row[1]}),
    }


async def run_page(run_no: str = "", run_type: str = "", run_status: str = "",
                   page_num: int = 1, page_size: int = 10) -> PageInfo:
    """运行记录分页查询。

    默认按时间倒序：看这一页的人基本都是想知道「刚才那次跑成什么样」。
    """
    query = AgentRun.all()
    text = str(run_no or "").strip()
    if text:
        query = query.filter(run_no__contains=text)
    if str(run_type or "").strip():
        query = query.filter(run_type=str(run_type).strip())
    if str(run_status or "").strip():
        query = query.filter(run_status=str(run_status).strip())
    if page_size > MAX_PAGE_SIZE:
        page_size = MAX_PAGE_SIZE
    page_num = max(1, page_num)
    total = await query.count()
    rows = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    tasks = {task.id: task for task in await MatchTask.filter(
        id__in=[run.task_id for run in rows if run.task_id])}
    members = {member.id: member for member in await MemberProfile.filter(
        id__in=[task.member_id for task in tasks.values()])}
    lines = []
    for run in rows:
        task = tasks.get(run.task_id) if run.task_id else None
        lines.append(_run_line(run, task, members.get(task.member_id) if task else None))
    return PageInfo(total=total, list=lines)


async def run_detail(run_id: int | None) -> dict:
    """一次运行的过程：运行总览、候选漏斗、调度时间线。

    三块数据分别现查：总览来自运行记录，漏斗来自候选池，时间线来自步骤记录。
    运行记录里那句结论文字只跟着总览一起显示，不参与数数。
    """
    run = await AgentRun.get_or_none(id=run_id)
    if run is None:
        raise CustomException("这条运行记录已经不在了，请刷新列表后重新挑一条")
    task = await MatchTask.get_or_none(id=run.task_id) if run.task_id else None
    member = await MemberProfile.get_or_none(id=task.member_id) if task else None
    rounds = await timeline(run.id)
    return {
        "run": {**_run_line(run, task, member),
                "input_snapshot": run.input_snapshot,
                "output_summary": run.output_summary},
        "funnel": await funnel(task.id if task else None),
        "timeline": rounds,
        "stat": _step_stat(rounds),
    }
