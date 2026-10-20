"""子 Agent 通用执行器。

几个角色跑的是同一套执行器：角色的差别只有三样——用哪份提示词、能调哪几个工具、
单次最多调几次工具，这三样全部从 agent_definition 和 function_tool 里读，
代码里没有按角色写的分支。

一次执行就是一个 ReAct 循环：把角色的提示词、这一轮的任务交代和它手上那几件工具
一起发给模型；模型决定调哪个工具，代码执行完把结果回给它，直到它不再调工具、
给出结构化结论为止。

循环里有两道闸，上限都从系统参数里读，管理员改完立刻生效：

    单角色工具调用次数     一个角色一次执行最多调几次工具
    同一个工具连续调用次数  模型陷在同一个工具里反复调的时候把它拦住

任何一道闸被触发，都是中断当前角色、把「触发了哪道闸」作为结论返回，
既不静默继续，也不抛异常把整次运行带崩——接下来是换角色还是收尾，是调度层的决定。

每一步都落库：一次工具调用写一条 agent_step，角色收尾再写一条结论 step。
执行器只做这些通用的事，业务产出（画像、候选池）由调用方拿到结论之后自己写。

写步骤记录和写模型调用记录这两件事收在本文件里做成公共函数：主管派单也落 agent_step
（step_type 为「调度」），它用的是同一个写入口，两张表的口径才不会一处一个样。
"""

import json
import re
from dataclasses import dataclass
from typing import Callable

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from ai import model_factory, prompt_loader
from ai import tools as tool_box
from common.exception_handler import CustomException
from common.times import cost_millis, now, precise_now
from models import AgentDefinition, AgentStep
from service import config_service

# 执行器认识的几个角色编码，和 agent_definition.agent_code 一致
AGENT_SUPERVISOR = "SUPERVISOR"
AGENT_PORTRAIT = "PORTRAIT"
AGENT_SCREENER = "SCREENER"
AGENT_AUDITOR = "AUDITOR"
# 主管说收尾时用的取值。它不是角色，不在角色表里，但主管每一轮的调度结论、
# 以及照结论渲染的调度时间线都要认它，所以和角色编码放在一起当唯一来源
AGENT_FINISH = "FINISH"
# 三个子角色跑同一套执行器；主管做的是调度，写在调度层里
SUB_AGENT_CODES = (AGENT_PORTRAIT, AGENT_SCREENER, AGENT_AUDITOR)
# 每个角色用哪条用途的模型配置。换模型改的是表里的数据，不是这里的代码
ROLE_PURPOSE = {
    AGENT_PORTRAIT: model_factory.PURPOSE_PORTRAIT,
    AGENT_SCREENER: model_factory.PURPOSE_SCREEN,
    AGENT_AUDITOR: model_factory.PURPOSE_AUDIT,
}

# 步骤类型与步骤状态，取值和 agent_step 两列的口径一致
STEP_TOOL = "工具调用"
STEP_CONCLUSION = "角色结论"
# 主管派单写的那一条。子角色不写这种，它只写工具调用和角色结论
STEP_SCHEDULE = "调度"
STEP_DONE = "已完成"
STEP_FAILED = "运行失败"

# 两道闸的参数编码与兜底默认值。参数被停用或值填坏了就退回默认值
MAX_TOOL_CALL_KEY = "AGENT_MAX_TOOL_CALL"
MAX_TOOL_CALL_DEFAULT = 30
MAX_SAME_TOOL_KEY = "AGENT_MAX_SAME_TOOL"
MAX_SAME_TOOL_DEFAULT = 10
# 触发了哪道闸，作为结论返回给调用方
GATE_TOOL_CALL = "单角色工具调用次数达到上限"
GATE_SAME_TOOL = "同一个工具连续调用次数达到上限"

# 模型没先调必调工具、或没给出合法 JSON 时，最多再纠正一次
MAX_CORRECT = 1
# 工具调用之外还留给纠正和收尾的模型来回轮数
EXTRA_ROUNDS = 3
# 入参与结论写库前的长度上限，和工具调用日志同一口径
TEXT_LIMIT = 20000
# 失败原因写库前的截断长度，和 agent_step.error_message 的列长一致
ERROR_LIMIT = 500


@dataclass
class AgentOutcome:
    """一次角色执行的结果。

    gate 有值表示这次执行是被闸拦下来的：结论就是「触发了哪道闸」，
    data 可能是空的，业务产出也不该再往下写。
    """

    agent_code: str
    conclusion: str
    data: dict | None = None
    gate: str | None = None
    tool_calls: int = 0
    rounds: int = 0


def _json_text(value, limit: int = TEXT_LIMIT) -> str | None:
    """把入参或返回转成存库的文本，过长就截断。"""
    if value is None:
        return None
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "……（内容过长已截断）"


def _error_text(message) -> str:
    text = str(message or "").strip() or "角色执行失败"
    return text if len(text) <= ERROR_LIMIT else text[:ERROR_LIMIT]


def message_text(message) -> str:
    """取出模型这一轮回的正文。"""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content or "")


def first_json_object(text: str) -> dict | None:
    """从模型输出里取出第一个 JSON 对象。

    模型有时会在 JSON 外面带一段解释，或者套一层代码块标记。
    这里先剥掉代码块，再取第一个左花括号到最后一个右花括号之间的内容；
    解析不出来就返回空，由调用方决定是纠正重试还是直接报错。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    fenced = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fenced:
        raw = fenced.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start:end + 1])
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def step_json(value: str | None) -> dict:
    """把步骤表里按 JSON 存的入参读回对象，读不出来当作空。

    写入端统一用 JSON 文本存，这里读回来的保证是字典，
    调用方不用每处都再判一次类型。
    """
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def step_text(value: str | None) -> str:
    """把步骤表里按 JSON 存的文本还原成人看的文字。

    字符串存进去会带一层引号和转义，读回来要脱掉；
    存的不是字符串就原样返回，不拿一条历史数据把读取处拦下来。
    """
    text = (value or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return text
    return parsed if isinstance(parsed, str) else text


async def _limit(key: str, default: int) -> int:
    raw = await config_service.get_value(key, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


async def role_limits(agent: AgentDefinition) -> tuple[int, int]:
    """算这个角色这次执行的两道上限。

    工具调用总数优先用角色自己配的值，角色留空才用系统参数里的统一上限；
    同一个工具连续调用次数是全局口径，只在系统参数里配。
    """
    max_tool_call = agent.max_tool_call or await _limit(MAX_TOOL_CALL_KEY, MAX_TOOL_CALL_DEFAULT)
    max_same_tool = await _limit(MAX_SAME_TOOL_KEY, MAX_SAME_TOOL_DEFAULT)
    return max_tool_call, max_same_tool


async def write_step(context: tool_box.ToolContext, round_no: int, step_index: int,
                     step_type: str, *, step_name: str, tool_code: str | None = None,
                     request_params=None, response_result=None,
                     step_status: str = STEP_DONE, error_message: str | None = None,
                     started=None) -> None:
    """写一条步骤记录。页面上的调度时间线就是按这张表渲染的。

    主管派单和子角色干活用的是同一个写入口，截断长度、时间口径、
    耗时的起点怎么打都按这里的一份规矩来。
    """
    if not context.run_id:
        return
    await AgentStep.create(
        run_id=context.run_id,
        round_no=round_no,
        step_index=step_index,
        agent_code=context.agent_code,
        step_type=step_type,
        step_name=step_name,
        tool_code=tool_code,
        request_params=_json_text(request_params),
        response_result=_json_text(response_result),
        step_status=step_status,
        error_message=_error_text(error_message) if error_message else None,
        # 时间列是秒精度，存 now() 的原值；microsecond 的起点只用来算耗时
        start_time=now(),
        end_time=now(),
        cost_millis=cost_millis(started) if started else None,
    )


def _default_summary(data: dict) -> str:
    """调用方没给概述函数时，用字段名和条数拼一句结论。"""
    parts = []
    for key, value in data.items():
        if isinstance(value, list):
            parts.append(f"{key} {len(value)} 项")
        elif isinstance(value, str) and value.strip():
            parts.append(f"{key} {len(value)} 字")
    return "模型返回了结构化结论：" + ("、".join(parts) if parts else "字段为空")


async def _finish(agent: AgentDefinition, context: tool_box.ToolContext, round_no: int,
                  step_index: int, *, conclusion: str, gate: str | None,
                  tool_calls: int, rounds: int) -> AgentOutcome:
    """被闸拦下来时收尾：把「触发了哪道闸」写成一条结论步骤并返回。"""
    await write_step(
        context, round_no, step_index, STEP_CONCLUSION,
        step_name=f"{agent.agent_name}结论",
        request_params={"tool_calls": tool_calls, "rounds": rounds, "gate": gate},
        response_result=conclusion,
        step_status=STEP_FAILED if gate else STEP_DONE,
        error_message=conclusion if gate else None,
        started=precise_now())
    return AgentOutcome(agent_code=agent.agent_code, conclusion=conclusion,
                        gate=gate, tool_calls=tool_calls, rounds=rounds)


async def run_agent(agent_code: str, context: tool_box.ToolContext, *,
                    prompt_values: dict | None = None,
                    instruction: str = "",
                    required_tools: tuple[str, ...] = (),
                    summarize: Callable[[dict], str] | None = None) -> AgentOutcome:
    """把一个角色交给模型跑一轮。

    进来之前先把角色、提示词、工具、模型四项都取到：这四项里任何一项不满足，
    都是执行到一半才会炸的，那时候错误信息已经离现场很远，所以在这里一次查清，
    并说清该去哪补哪一项。

    required_tools 是这一轮必须先调到的工具：模型没调就想交结论时，
    执行器把它打回去重来一次，两次都不调就直接报错，不采信这份结论。
    """
    agent = await AgentDefinition.get_or_none(agent_code=agent_code)
    if agent is None:
        raise CustomException(f"没有找到角色 {agent_code}，请到【子 Agent 定义】确认这个角色还在不在")
    if agent.enabled != "是":
        raise CustomException(f"「{agent.agent_name}」已经被停用，请到【子 Agent 定义】把它启用后再试")
    code = (agent.prompt_code or "").strip()
    if not code:
        raise CustomException(f"「{agent.agent_name}」还没有绑定提示词模板，请到【子 Agent 定义】给它选一个")
    group = (agent.tool_group or "").strip()
    if not group:
        raise CustomException(f"「{agent.agent_name}」还没有绑定工具分组，请到【子 Agent 定义】给它选一个分组")
    if not context.run_id:
        raise CustomException("这次执行没有运行编号，步骤记录没法落库，请从发起运行的那一步进来")

    system_prompt = await prompt_loader.render(code, **(prompt_values or {}))
    specs = await tool_box.build_tool_specs(group)
    if not specs:
        raise CustomException(
            f"「{agent.agent_name}」的工具分组「{group}」下没有启用中的工具，"
            f"请到【工具中心】把这个分组下的工具启用")
    purpose = ROLE_PURPOSE.get(agent_code, model_factory.PURPOSE_SCHEDULE)
    config = await model_factory.load_for_purpose(purpose)
    bound = model_factory.build_chat_model(config).bind_tools(specs)

    messages = [SystemMessage(content=system_prompt)]
    if instruction:
        messages.append(HumanMessage(content=instruction))
    max_tool_call, max_same_tool = await role_limits(agent)
    round_no = context.round_no or 1
    step_index = 0
    tool_calls_used = 0
    last_tool = ""
    same_streak = 0
    called_tools: list[str] = []
    corrections = 0
    max_rounds = max_tool_call + EXTRA_ROUNDS

    for model_round in range(1, max_rounds + 1):
        try:
            response = await bound.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001
            # 接口报错翻译成人话再往上抛，页面上的提示要能指到该改哪里
            raise CustomException(model_factory.translate_exception(exc))
        model_factory.check_truncated(response)
        messages.append(response)

        calls = list(getattr(response, "tool_calls", None) or [])
        if calls:
            for call in calls:
                name = str(call.get("name") or "")
                args = call.get("args") or {}
                call_id = call.get("id")
                if tool_calls_used + 1 > max_tool_call:
                    return await _finish(
                        agent, context, round_no, step_index + 1,
                        conclusion=f"工具调用次数已经用满 {max_tool_call} 次，"
                                   f"本次执行被「{GATE_TOOL_CALL}」中断",
                        gate=GATE_TOOL_CALL, tool_calls=tool_calls_used, rounds=model_round)
                streak = same_streak + 1 if name == last_tool else 1
                if streak > max_same_tool:
                    return await _finish(
                        agent, context, round_no, step_index + 1,
                        conclusion=f"工具 {name} 被连续调用了 {streak} 次，"
                                   f"本次执行被「{GATE_SAME_TOOL}」中断",
                        gate=GATE_SAME_TOOL, tool_calls=tool_calls_used, rounds=model_round)
                tool_calls_used += 1
                last_tool, same_streak = name, streak
                if name not in called_tools:
                    called_tools.append(name)
                step_index += 1
                call_started = precise_now()
                try:
                    result = await tool_box.invoke(name, args, context)
                except CustomException as exc:
                    # 工具失败不中断这一轮：把原因回给模型，让它改参数或者换个工具
                    await write_step(
                        context, round_no, step_index, STEP_TOOL,
                        step_name=f"调用工具 {name}", tool_code=name,
                        request_params=args, step_status=STEP_FAILED,
                        error_message=exc.message, started=call_started)
                    messages.append(ToolMessage(
                        content=f"这次调用没有成功：{exc.message}", tool_call_id=call_id))
                    continue
                await write_step(
                    context, round_no, step_index, STEP_TOOL,
                    step_name=f"调用工具 {name}", tool_code=name,
                    request_params=args, response_result=result,
                    started=call_started)
                messages.append(ToolMessage(content=_json_text(result) or "",
                                            tool_call_id=call_id))
            continue

        data = first_json_object(message_text(response))
        missing = [name for name in required_tools if name not in called_tools]
        if missing and corrections < MAX_CORRECT:
            corrections += 1
            messages.append(HumanMessage(content=(
                f"你还没有调用 {'、'.join(missing)}。请先调用它把需要的数据读到手，再重新给出结论。")))
            continue
        if data is None and corrections < MAX_CORRECT:
            corrections += 1
            messages.append(HumanMessage(content=(
                "上一次的输出不是合法的 JSON 对象。请只输出一个 JSON 对象，"
                "不要解释文字，也不要代码块标记。")))
            continue
        if missing:
            raise CustomException(
                f"「{agent.agent_name}」没有调用 {'、'.join(missing)} 就给出了结论，"
                f"这次结果不可信，请重试")
        if data is None:
            raise CustomException(
                f"「{agent.agent_name}」没有按要求返回 JSON 结构化结论，请重试；"
                f"如果每次都这样，请到【Prompt模板】检查它的提示词里有没有写清输出格式")
        conclusion = (summarize or _default_summary)(data)
        await write_step(
            context, round_no, step_index + 1, STEP_CONCLUSION,
            step_name=f"{agent.agent_name}结论",
            request_params={"tool_calls": tool_calls_used, "rounds": model_round},
            response_result=conclusion, started=precise_now())
        return AgentOutcome(agent_code=agent.agent_code, conclusion=conclusion,
                            data=data, tool_calls=tool_calls_used, rounds=model_round)

    return await _finish(
        agent, context, round_no, step_index + 1,
        conclusion=f"模型来回 {max_rounds} 轮仍然没有给出结论，"
                   f"本次执行被「{GATE_TOOL_CALL}」中断",
        gate=GATE_TOOL_CALL, tool_calls=tool_calls_used, rounds=max_rounds)
