"""候选审核业务逻辑。

审核官站的是候选方那一侧的立场：拿候选方自己的合住偏好，反过来评估申请方适不适合和他合住。
同一个人从申请方这边看是「条件都满足」，从候选方那边看可能「必须项没满足」，
所以这一步不是把筛选的结果照抄一遍，而是换一个立场重评一次，评不过就否决。

否决必须分类，因为分类决定下一步能做什么：

    MISMATCH_HARD          申请方不满足候选方标为必须的条件       换一批候选
    PREFERENCE_CONFLICT    双方合住习惯直接冲突                   换一批候选
    PORTRAIT_INSUFFICIENT  申请方画像缺候选方在意的维度，判断不了   补充资料后重新匹配

第三种要先补充资料再重新匹配。所以判这一种时必须点名缺的是哪个维度，
工具层会拦住没有点名维度的理由。

一次审核把候选池里还没有结论的人分成几批，一批交给审核官执行一次。一位候选要两次
工具调用——先把候选方的偏好与画像读到手里，再把这一位的结论回填一次；一批能装多少人
按角色的单次工具调用上限算出来。

三件事由代码定死，不由模型说了算：

1. 一批审几位、按什么顺序分批，按工具调用上限和待审人数算，模型只能审这一批的名单。
2. 每一批审了几位、通过几位、否决几位，全部从数据库里现查，不采信模型结论里报的数；
   两边对不上时以库里的为准，并把这件事写进这一批的结论。
3. 模型判「通过」的候选，代码会双向复核必须项：申请方要满足候选方标为必须的
   条件，候选方也要满足申请方标为必须的条件；「合租只找同性」同样复核。复核不过的
   当场改判为否决，理由里写清是哪个方向、哪一项维度或性别不同——判断依据要验得上。

一次审核留下两类记录：agent_run / agent_step 记过程，match_candidate 上回填结论。
租客端页面读的是候选池的现查结果，页面上的数字全部来自数据库。
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
                    MatchCandidate, MatchTask, MemberPortrait, MemberProfile,
                    PromptTemplate, RoommatePreference, User)
from service import (agent_service, member_service, preference_service,
                     portrait_service, screener_service)

# 跑这一轮的角色，以及它把结论回填到哪张表
AGENT_CODE = agents.AGENT_AUDITOR
RUN_TYPE = "候选审核"
# 智能匹配里的审核步骤挂在整次“匹配编排”运行上，不会另开 AUDIT-* 运行。
MATCH_RUN_TYPE = "匹配编排"
# 每一位候选都要先把候选方的偏好读到手里、再把这一位的结论回填，两件都不许省。
# 少读那一次，审核官就是凭印象判；少写那一次，页面上这位候选会一直挂着待审核
REQUIRED_TOOLS = ("read_candidate_preference", "save_audit_result")
# 回填结论的工具编码，用它从步骤记录里取回这一批真正写了什么
SAVE_TOOL = "save_audit_result"
# 一位候选要两次工具调用：先读候选方的偏好与画像，再回填结论
TOOL_PER_CANDIDATE = 2
# 一批最多审几位。一位两次调用，一批十位刚好在默认的单角色上限内留出余量；
# 角色自己配的上限更小时按上限收窄，任何情况下都至少审一位
BATCH_SIZE = 10
# 一批里留给收尾和纠正的调用余量
BATCH_RESERVE = 4
# 分批的防御上限：候选池最多百来号人，超过这个数说明待审名单没有真的变短
BATCH_LIMIT = 60

# 结论与失败原因写库前的长度上限，error_message 那一列只放 500 字
SUMMARY_LIMIT = 2000
ERROR_LIMIT = 500

# 运行状态，取值和 agent_run.run_status 一致
RUN_RUNNING = "运行中"
RUN_DONE = "已完成"
RUN_FAILED = "运行失败"

# 候选刚进池子时的审核状态，以及审核官能给出的两种结论
AUDIT_WAIT = "待审核"

# 双方计划租期按档位比较：相邻档位视为可协商，相差 2 档及以上视为硬冲突。
# 例：3个月以下 vs 3-6个月 可协商；3个月以下 vs 6-12个月/1-2年/2年以上 不可。
LEASE_TERM_GAP_LIMIT = 2
AUDIT_PASS = tool_box.AUDIT_PASS
AUDIT_REJECT = tool_box.AUDIT_REJECT
# 三种否决分类的人话说明和下一步该做什么，页面和结论都读这两份
REJECT_LABELS = {
    "MISMATCH_HARD": "申请方不满足候选方标为必须的条件",
    "PREFERENCE_CONFLICT": "双方合住习惯直接冲突",
    "PORTRAIT_INSUFFICIENT": "申请方画像缺候选方在意的维度，判断不了",
}
# 代码复核改判时用的否决分类：必须项验不过、或者性别不同，都只能换人
RECHECK_CODE = "MISMATCH_HARD"
REJECT_SOLUTIONS = {
    "MISMATCH_HARD": "本候选不匹配",
    "PREFERENCE_CONFLICT": "本候选不匹配",
    "PORTRAIT_INSUFFICIENT": "补充资料后再匹配",
}


@dataclass
class AuditBatch:
    """一批审核的结果。

    written 是这一批真正回填的条数，passed 与 rejected 从库里数出来；
    mismatch 有值表示模型报的和库里存的对不上，结论里会写明。
    gate 有值表示这一批被闸拦下来了，这一批没有产出。
    """

    batch_no: int
    written: int = 0
    passed: int = 0
    rejected: int = 0
    codes: dict = field(default_factory=dict)
    conclusion: str = ""
    gate: str | None = None
    tool_calls: int = 0
    mismatch: str | None = None


@dataclass
class AuditResult:
    """一次审核跑完的结果。四个数都是从候选池现查出来的。"""

    batches: list[AuditBatch] = field(default_factory=list)
    passed: int = 0
    rejected: int = 0
    pending: int = 0
    codes: dict = field(default_factory=dict)
    conclusion: str = ""
    gate: str | None = None


@dataclass
class Recheck:
    """代码复核发现的一位「模型判通过、但数据上过不去」的候选。

    双向都必须记下来：violations 是申请方没满足候选方的必须项，reverse_violations
    是候选方没满足申请方的必须项，gender_conflict 是性别不同。改判理由里要写清是
    哪个方向、哪一条把这一位挡下来的，主管和页面都从这里知道下一步该做什么。
    """

    row: MatchCandidate
    candidate: MemberProfile
    violations: list[str] = field(default_factory=list)
    reverse_violations: list[str] = field(default_factory=list)
    gender_conflict: bool = False
    lease_conflict: bool = False
    lease_detail: str = ""

    def _detail(self) -> str:
        parts: list[str] = []
        if self.gender_conflict:
            parts.append("合租只找同性：申请方与候选方性别不同")
        if self.lease_conflict:
            parts.append(self.lease_detail or "双方计划租期档位相差过大，不适合合租")
        if self.violations:
            parts.append(f"申请方不满足候选方标为必须的「{'、'.join(self.violations)}」项")
        if self.reverse_violations:
            parts.append(f"候选方不满足申请方标为必须的「{'、'.join(self.reverse_violations)}」项")
        return "；".join(parts) or "代码复核不通过"

    def rejected_because(self) -> str:
        """写进候选行 reject_reason 的改判理由：含方向、维度或「合租只找同性」。"""
        return "代码复核改判：" + self._detail()

    def describe(self) -> str:
        """写进批次结论的一小句：候选是谁、为什么改判。"""
        return f"「{self.candidate.nickname}」{self._detail()}"


def reject_label(code: str | None) -> str | None:
    """否决分类的人话说明。没有分类时返回空，页面上一栏留白。"""
    return REJECT_LABELS.get(str(code or "").strip() or "") if code else None


def reject_solution(code: str | None) -> str | None:
    """这个分类下一步该做什么。"""
    return REJECT_SOLUTIONS.get(str(code or "").strip() or "") if code else None


def _text(value, suffix: str = "") -> str:
    """空值统一读成「未填」：审核官据此知道哪一项没有依据，可以判画像不够。"""
    body = str(value).strip() if value not in (None, "") else ""
    if not body:
        return "未填"
    return f"{body}{suffix}"


def profile_text(member: MemberProfile) -> str:
    """一位租客的档案，摊成给模型看的几行。"""
    return "\n".join([
        f"昵称：{_text(member.nickname)}",
        f"性别：{_text(member.gender)}",
        f"年龄：{_text(member_service.calc_age(member.birth_date), ' 岁')}",
        f"月租预算：{_text(member.rent_budget, ' 元')}",
        f"整洁度：{_text(member.tidiness)}",
        f"职业：{_text(member.occupation)}",
        f"计划租期：{_text(member.lease_term)}",
        f"意向门店：{_text(member_service.store_name(member.store_id))}"
        f"（{_text(member_service.area_name(member.store_id))}片区）",
        f"作息：{_text(member.schedule_type)}",
        f"是否养宠：{_text(member.has_pet)}",
        f"是否吸烟：{_text(member.smoking)}",
        f"兴趣标签：{'、'.join(split_values(member.interest_tags)) or '未填'}",
        f"自我介绍：{_text(member.self_intro)}",
        f"室友期望：{_text(member.roommate_expectation)}",
    ])


def applicant_text(member: MemberProfile, portrait: MemberPortrait | None,
                   preference: RoommatePreference | None) -> str:
    """申请方这一侧的情况。

    画像是补画像那一环的产物，还没生成时照样把档案给出去，另外说清缺了它——
    审核官据此才有机会判「判断不了」，而不是硬判不合适。
    申请方自己的合住偏好也一并给出去：习惯冲突那一类否决，要两边对照才看得出。
    """
    lines = [profile_text(member)]
    if preference is None:
        lines.append("他自己的合住偏好：还没有填，习惯冲突那一类判断不了")
    else:
        lines.append("他自己的合住偏好（作为习惯对照）：")
        lines.append(screener_service.preference_text(_preference_dict(preference)))
    if portrait is None:
        lines.append("画像：还没有生成画像，只有上面这份档案可供判断")
        return "\n".join(lines)
    lines.append(f"画像 v{portrait.version}：")
    lines.append("  性格标签：" + ("、".join(split_values(portrait.personality_tags)) or "空"))
    lines.append("  生活方式标签：" + ("、".join(split_values(portrait.lifestyle_tags)) or "空"))
    lines.append("  合住需求标签：" + ("、".join(split_values(portrait.cohabit_need_tags)) or "空"))
    lines.append("  画像小结：" + (portrait.summary or "空"))
    return "\n".join(lines)


def _preference_dict(preference: RoommatePreference) -> dict:
    """把偏好行摊成筛选那一套格式，两处读出来的偏好文字才是同一份口径。"""
    return {
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
    }


def candidate_text(rows: list) -> str:
    """这一批候选的名单。

    只列档案里的事实，不列他们各自的合住偏好：偏好要审核官自己一位一位去读，
    读到的是数据库里的现查结果，不是上一环塞进提示词里的原文。
    """
    if not rows:
        return "这一批没有候选。"
    lines = []
    for row, member in rows:
        lines.append(
            f"候选编号 {member.id}｜{member.nickname}｜{member.gender}｜"
            f"{_text(member_service.calc_age(member.birth_date), ' 岁')}｜"
            f"预算 {_text(member.rent_budget, ' 元')}｜整洁度 {_text(member.tidiness)}｜"
            f"{_text(member_service.store_name(member.store_id))}｜"
            f"{_text(member.schedule_type)}｜第 {row.found_round} 轮筛出")
    return "\n".join(lines)


def instruction(rows: list, pending: int, batch_no: int) -> str:
    """这一批交给审核官的交代：审谁、怎么审、结论怎么写。"""
    ids = "、".join(str(member.id) for _, member in rows)
    return "\n".join([
        f"这是第 {batch_no} 批，要审的候选编号是 {ids}；候选池里还有 {pending} 位等着审。",
        "一位一位来：先调用一次读候选方偏好的工具，拿到他标为必须的项和画像，"
        "再把这一位的结论回填一次，然后换下一位。已经回填过的不要再回填。",
        "候选方标为必须的项有一条不满足，判否决并写 MISMATCH_HARD；"
        "双方合住习惯直接冲突的（例如一方经常在屋里吸烟、另一方受不了烟味）写 PREFERENCE_CONFLICT；"
        "申请方的档案或画像不足以判断的写 PORTRAIT_INSUFFICIENT，"
        "并在理由里点名缺的是哪个维度（例如「缺作息：几点睡、几点起都没有依据」）。",
        "全批审完再给结论，只输出一个 JSON 对象：",
        '{"audited": [{"candidate_member_id": 候选编号, "audit_status": "通过或否决", '
        '"reject_code": "否决时必填", "reject_reason": "否决时的理由"}], '
        '"summary": "一句话结论"}',
        "这一批只审上面这几个候选编号，名单外的候选不要动。",
    ])


def _audited(data: dict) -> list:
    """模型结论里「audited」的条目。

    正常是一批一个列表；一批只审一位时，模型有时直接给一个对象。
    两种都收下来，单对象且带 audit_status 时按 1 条算。
    """
    rows = data.get("audited")
    if isinstance(rows, dict):
        return [rows] if rows.get("audit_status") else []
    return rows if isinstance(rows, list) else []


def _summarize(data: dict) -> str:
    """把模型的结论收敛成一句话写进步骤记录。"""
    rows = _audited(data)
    passed = len([one for one in rows
                  if isinstance(one, dict) and one.get("audit_status") == AUDIT_PASS])
    return f"模型给出结论 {len(rows)} 条，其中通过 {passed} 人、否决 {len(rows) - passed} 人"


async def batch_size(agent: AgentDefinition) -> int:
    """一批最多审几位候选。

    一位候选两次调用，再给这一批留出收尾的余量，剩下的就是能装的人数；
    角色自己配的工具调用上限更小时按它收窄，任何情况下至少一位。
    """
    max_tool_call, _ = await agents.role_limits(agent)
    capacity = (max_tool_call - BATCH_RESERVE) // TOOL_PER_CANDIDATE
    return max(1, min(BATCH_SIZE, capacity))


def _below(order: tuple, value, floor) -> bool:
    """按档位高低比：有一头没填就不判，比下限低才算不满足。"""
    if not value or not floor or value not in order or floor not in order:
        return False
    return order.index(value) < order.index(floor)


def _same_place(one_store_id, other_store_id, scope: str) -> bool:
    """门店这一项按「和候选方在不在一个地方」算：同门店看门店，同片区看片区。"""
    if scope == "同门店":
        return bool(one_store_id) and one_store_id == other_store_id
    area = member_service.area_name(other_store_id)
    return bool(area) and member_service.area_name(one_store_id) == area


def _violates(applicant: MemberProfile, candidate: MemberProfile,
              preference: RoommatePreference, code: str) -> bool:
    """申请方在候选方的某一个维度上是不是不满足。验不清的一律返回否。"""
    if code == "age":
        age = member_service.calc_age(applicant.birth_date)
        if age is None:
            return False
        return age < preference.age_min or age > preference.age_max
    if code == "budget":
        if applicant.rent_budget is None:
            return False
        return (applicant.rent_budget < preference.budget_min
                or applicant.rent_budget > preference.budget_max)
    if code == "tidiness":
        return _below(member_service.TIDINESS_LEVELS, applicant.tidiness,
                      preference.tidiness_min)
    if code == "store":
        return not _same_place(applicant.store_id, candidate.store_id, preference.store_scope)
    if code == "schedule":
        if not applicant.schedule_type:
            return False
        return applicant.schedule_type not in split_values(preference.schedule_accept)
    if code == "lease":
        return _below(member_service.LEASE_TERMS, applicant.lease_term,
                      preference.lease_min)
    if code == "pet":
        # 这一维度问的是「能不能接受室友养宠」，比的是档案里的是否养宠：
        # 只有「不接受」会把养宠的人挡掉，「接受」和「无所谓」都不设门槛
        if not applicant.has_pet:
            return False
        return preference.pet_accept == "不接受" and applicant.has_pet == "有"
    return False


def hard_violations(applicant: MemberProfile, candidate: MemberProfile,
                    preference: RoommatePreference) -> list[str]:
    """申请方在候选方标为必须的维度上被代码验不过的那几项。

    只验「标为必须」而且「确实有约束」的维度：填成不限、无所谓、三种作息全选的，
    对谁都成立，不该算不满足。两边有一头的值缺着也不在这里判——那属于「判断不了」，
    归审核官判 PORTRAIT_INSUFFICIENT 那条路，代码只判验得清的。
    """
    names: list[str] = []
    for item in preference_service.must_dimensions(preference):
        code = item["code"]
        if not preference_service.has_constraint(preference, code):
            continue
        if _violates(applicant, candidate, preference, code):
            names.append(item["name"])
    return names


def gender_conflict(applicant: MemberProfile, candidate: MemberProfile) -> bool:
    """合租只找同性：双方性别都填了而且不一样，就是硬冲突。

    性别不在合住偏好的七个维度里，模型从偏好文本上看不到它；
    这一条只能由代码在复核时兜住，历史候选池里混进异性时也要能拦住。
    """
    return bool(applicant.gender and candidate.gender
                and applicant.gender != candidate.gender)


def lease_term_gap(applicant: MemberProfile, candidate: MemberProfile) -> int | None:
    """双方计划租期在档位表里的距离；缺值或非法值返回 None（交给模型判断）。

    计划租期是「打算签多久」，不是偏好里的「最短租期」。两个人合租要签同一份合同，
    相差两档及以上（例如一方 3 个月以下、另一方 6-12 个月）没法共用一份合同，
    只有相邻档位（例如 6-12 个月与 1-2 年）才可能协商。
    """
    try:
        left = member_service.LEASE_TERMS.index(applicant.lease_term)
        right = member_service.LEASE_TERMS.index(candidate.lease_term)
    except (ValueError, AttributeError):
        return None
    return abs(left - right)


def lease_term_conflict(applicant: MemberProfile, candidate: MemberProfile) -> bool:
    gap = lease_term_gap(applicant, candidate)
    return gap is not None and gap >= LEASE_TERM_GAP_LIMIT


def lease_term_conflict_text(applicant: MemberProfile, candidate: MemberProfile) -> str:
    return (f"双方计划租期相差过大：申请方「{applicant.lease_term}」"
            f"vs 候选方「{candidate.lease_term}」，不适合合租")


def must_need(preference: RoommatePreference) -> list[dict]:
    """候选方标为必须、而且确实有约束的条件，连带它要求的内容。

    页面展示候选方要求、代码复核审核结论，都照着这几项逐项比对。
    """
    return [{"code": item["code"], "name": item["name"],
             "need": _need_text(preference, item["code"])}
            for item in preference_service.must_dimensions(preference)
            if preference_service.has_constraint(preference, item["code"])]


def _need_text(preference: RoommatePreference, code: str) -> str:
    """一个维度要求的内容，读成人话。"""
    if code == "age":
        return f"{preference.age_min}-{preference.age_max} 岁"
    if code == "budget":
        return f"{preference.budget_min}-{preference.budget_max} 元"
    if code == "tidiness":
        return f"{preference.tidiness_min}及以上"
    if code == "store":
        return f"{preference.store_scope}（以他自己的意向门店为基准）"
    if code == "schedule":
        return "、".join(split_values(preference.schedule_accept))
    if code == "lease":
        return f"{preference.lease_min}及以上"
    if code == "pet":
        if preference.pet_accept == "不接受":
            return "不接受室友养宠"
        return f"对室友养宠的接受度：{preference.pet_accept or '不限'}"
    return "不限"


def _step_params(step: AgentStep) -> dict:
    """读步骤记录里这一次工具调用的入参。"""
    try:
        value = json.loads(step.request_params or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


async def recheck_rows(applicant: MemberProfile, rows: list,
                       applicant_preference: RoommatePreference | None = None) -> list[Recheck]:
    """按当前硬规则复核一批候选：同性 + 双向必须项，返回结构化明细。

    模型判「通过」是一句话，验不验得上要看数据。这里做两件事：

    - 正向：申请方是不是满足候选方标为必须的条件（换一个立场重评）；
    - 反向：候选方是不是满足申请方标为必须的条件（申请方自己的偏好也要对得上）。

    「合租只找同性」一并复核。档案与偏好按 id__in 一次性预取，批次多大都只查固定
    几条 SQL；审核改判和交付前复核共用这一份判断，两处口径不会分叉。
    """
    if not rows:
        return []
    candidate_ids = [row.candidate_member_id for row in rows]
    members = {item.id: item for item in await MemberProfile.filter(id__in=candidate_ids)}
    preferences = {item.member_id: item for item in await RoommatePreference.filter(
        member_id__in=candidate_ids)}
    if applicant_preference is None:
        applicant_preference = await RoommatePreference.get_or_none(member_id=applicant.id)
    records: list[Recheck] = []
    for row in rows:
        candidate = members.get(row.candidate_member_id)
        if candidate is None:
            continue
        violations: list[str] = []
        candidate_preference = preferences.get(candidate.id)
        if candidate_preference is not None:
            violations = hard_violations(applicant, candidate, candidate_preference)
        reverse: list[str] = []
        if applicant_preference is not None:
            reverse = hard_violations(candidate, applicant, applicant_preference)
        conflict = gender_conflict(applicant, candidate)
        lease_bad = lease_term_conflict(applicant, candidate)
        if violations or reverse or conflict or lease_bad:
            records.append(Recheck(
                row=row, candidate=candidate,
                violations=violations,
                reverse_violations=reverse,
                gender_conflict=conflict,
                lease_conflict=lease_bad,
                lease_detail=lease_term_conflict_text(applicant, candidate) if lease_bad else ""))
    return records


async def _recheck(applicant: MemberProfile, rows: list) -> list[Recheck]:
    """代码复核入口：审核批内改判用，逻辑与交付前复核共用 recheck_rows。"""
    return await recheck_rows(applicant, rows)


async def _prompt_values(member: MemberProfile, rows: list) -> dict:
    """组装这一批的提示词变量。"""
    portrait = await MemberPortrait.filter(
        member_id=member.id).order_by("-version", "-id").first()
    preference = await RoommatePreference.get_or_none(member_id=member.id)
    return {"applicant_info": applicant_text(member, portrait, preference),
            "candidate_info": candidate_text(rows)}


def _decided_counts(pool: list) -> tuple[list, list, list, dict]:
    """一批候选里已经有结论的那些，以及其中的通过与否决分布。"""
    decided = [row for row in pool if row.audit_status != AUDIT_WAIT]
    passed = [row for row in decided if row.audit_status == AUDIT_PASS]
    rejected = [row for row in decided if row.audit_status == AUDIT_REJECT]
    codes: dict = {}
    for row in rejected:
        code = row.reject_code or "未分类"
        codes[code] = codes.get(code, 0) + 1
    return decided, passed, rejected, codes


async def audit_batch(member: MemberProfile, task: MatchTask, run_id: int, *,
                      batch_no: int, pending: int, rows: list,
                      custom_instruction: str | None = None,
                      round_no: int | None = None) -> AuditBatch:
    """审一批候选：交给审核官，回填结论，再反查这一批落成了什么。

    人数以候选池里这一批人的现查状态为准：模型说审了几位、通过几位，都不作数。

    round_no 是这一批该记在第几轮上；从匹配运行里传入调度轮次，
    步骤记录和审核结论都按它归轮。
    """
    ids = [row.candidate_member_id for row, _ in rows]
    values = await _prompt_values(member, rows)
    text = custom_instruction or instruction(rows, pending, batch_no)
    context = tool_box.ToolContext(run_id=run_id, agent_code=AGENT_CODE, task_id=task.id,
                                   member_id=member.id, round_no=round_no or batch_no)
    outcome = await agents.run_agent(
        AGENT_CODE, context,
        prompt_values=values,
        instruction=text,
        required_tools=REQUIRED_TOOLS,
        summarize=_summarize)
    if outcome.gate:
        # 被闸拦下来：这一批没有产出，把触发了哪道闸原样带回去
        return AuditBatch(batch_no=batch_no, gate=outcome.gate,
                          conclusion=outcome.conclusion, tool_calls=outcome.tool_calls)
    data = outcome.data or {}
    claimed = _audited(data)
    pool = await MatchCandidate.filter(task_id=task.id, candidate_member_id__in=ids)
    decided, passed, rejected, codes = _decided_counts(pool)
    notes: list[str] = []
    if len(claimed) != len(decided):
        notes.append(f"模型说审了 {len(claimed)} 位，候选池里这一批回填了 {len(decided)} 位")
    records = await _recheck(member, passed)
    if records:
        # 模型判通过但代码验不过：直接改判否决，再按库里的现查结果重算这一批的数
        for item in records:
            await MatchCandidate.filter(id=item.row.id).update(
                audit_status=AUDIT_REJECT,
                reject_code=RECHECK_CODE,
                reject_reason=item.rejected_because()[:500],
                audit_round=round_no or batch_no)
        pool = await MatchCandidate.filter(task_id=task.id, candidate_member_id__in=ids)
        decided, passed, rejected, codes = _decided_counts(pool)
        notes.append(f"代码复核改判 {len(records)} 人："
                     + "；".join(item.describe() for item in records))
    detail = "、".join(f"{reject_label(code) or code} {count} 人"
                       for code, count in codes.items()) or "没有否决"
    conclusion = (f"第 {batch_no} 批审了 {len(decided)} 人，通过 {len(passed)} 人，"
                  f"否决 {len(rejected)} 人（{detail}）")
    if notes:
        conclusion += "；" + "；".join(notes)
    return AuditBatch(batch_no=batch_no, written=len(decided), passed=len(passed),
                      rejected=len(rejected), codes=codes, conclusion=conclusion,
                      tool_calls=outcome.tool_calls,
                      mismatch="；".join(notes) or None)


def _counts(rows: list) -> dict:
    """候选池的四个数：一共多少、还挂着待审核多少、通过多少、否决多少。"""
    passed = len([row for row in rows if row.audit_status == AUDIT_PASS])
    rejected = [row for row in rows if row.audit_status == AUDIT_REJECT]
    codes: dict = {}
    for row in rejected:
        code = row.reject_code or "未分类"
        codes[code] = codes.get(code, 0) + 1
    return {"total": len(rows), "passed": passed, "rejected": len(rejected),
            "pending": len(rows) - passed - len(rejected), "codes": codes,
            "portrait": codes.get("PORTRAIT_INSUFFICIENT", 0)}


def _conclusion(batches: list[AuditBatch], counts: dict) -> str:
    """把每一批的结果拼成一句能直接显示的话。"""
    if not batches:
        return "候选池里没有等着审的人，这一次没有审任何人"
    text = (f"一共审了 {len(batches)} 批：通过 {counts['passed']} 人，"
            f"否决 {counts['rejected']} 人")
    if counts["codes"]:
        detail = "、".join(f"{reject_label(code) or code} {count} 人"
                           for code, count in counts["codes"].items())
        text += f"；否决分类：{detail}"
    if counts["portrait"]:
        text += (f"。其中 {counts['portrait']} 人是申请方的画像不够、判断不了，"
                 f"补上对应的维度之后这一批可以再审一次")
    mismatch = [item.mismatch for item in batches if item.mismatch]
    if mismatch:
        text += "；模型报的和库里的对不上的地方：" + "；".join(mismatch)
    if counts["pending"]:
        text += f"。候选池里还有 {counts['pending']} 人没有结论，主管会按当前进展决定下一步"
    return text


async def build_audit(member_id: int, task_id: int, run_id: int, *,
                      custom_instruction: str | None = None,
                      round_no: int | None = None) -> AuditResult:
    """把一次审核跑完：还没有结论的人分批交给审核官，审完一批换下一批。

    待审名单在每一批之前现查：这一批回填了，下一批的名单就短一截，全部审完自动停。
    一批里一个人也没回填时也停——再跑一批还是同样的人，白跑一次。

    round_no 传给每一批，让它们的步骤记录归到同一个调度轮次上。
    """
    member = await MemberProfile.get_or_none(id=member_id)
    if member is None:
        raise CustomException("没有找到这位租客的档案，请先让他把档案填好")
    task = await MatchTask.get_or_none(id=task_id)
    if task is None:
        raise CustomException("没有找到这次匹配任务，请先到【智能匹配】发起新任务")
    agent = await AgentDefinition.get_or_none(agent_code=AGENT_CODE)
    if agent is None:
        raise CustomException("平台没有找到审核官角色，请联系管理员到【子 Agent 定义】核对")
    size = await batch_size(agent)
    batches: list[AuditBatch] = []
    batch_no = 1
    while batch_no <= BATCH_LIMIT:
        pending_rows = await MatchCandidate.filter(
            task_id=task_id, audit_status=AUDIT_WAIT).order_by("id")
        if not pending_rows:
            break
        chunk = pending_rows[:size]
        members = {item.id: item for item in await MemberProfile.filter(
            id__in=[row.candidate_member_id for row in chunk])}
        rows = [(row, members[row.candidate_member_id]) for row in chunk
                if row.candidate_member_id in members]
        if not rows:
            # 名单里的租客档案已经查不到了，再审也是空转
            break
        one = await audit_batch(
            member, task, run_id, batch_no=batch_no, pending=len(pending_rows),
            rows=rows, custom_instruction=custom_instruction if batch_no == 1 else None,
            round_no=round_no)
        batches.append(one)
        if one.gate or not one.written:
            break
        batch_no += 1
    pool = await MatchCandidate.filter(task_id=task_id)
    counts = _counts(pool)
    gate = batches[-1].gate if batches and batches[-1].gate else None
    conclusion = _conclusion(batches, counts)
    if gate:
        # 被闸拦下来时把触发了哪道闸放在最前面：页面上的失败原因要能指到该改哪里
        conclusion = f"{batches[-1].conclusion}；{conclusion}"
    return AuditResult(batches=batches, passed=counts["passed"],
                       rejected=counts["rejected"], pending=counts["pending"],
                       codes=counts["codes"], conclusion=conclusion, gate=gate)


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
    """发起审核之前要过的七项检查。

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

    task = await MatchTask.filter(member_id=member.id).order_by("-id").first()
    if task is None:
        return blocked(_check("candidate", "候选池", False,
                              "还没有候选结果，请先到【智能匹配】发起新任务",
                              "/front/myMatch", "去智能匹配"))
    pool = await MatchCandidate.filter(task_id=task.id)
    if not pool:
        return blocked(_check("candidate", "候选池", False,
                              "候选池还是空的，请到【智能匹配】按当前档案重新匹配",
                              "/front/myMatch", "去智能匹配"))
    checks.append(_check("candidate", "候选池", True, f"候选池里有 {len(pool)} 位候选"))

    waiting = len([row for row in pool if row.audit_status == AUDIT_WAIT])
    if not waiting:
        return blocked(_check("complete", "审核状态", True,
                              "这一批候选已经全部审核完成"))
    checks.append(_check("pending", "待审候选", True, f"还有 {waiting} 位等着审"))

    agent = await AgentDefinition.get_or_none(agent_code=AGENT_CODE)
    if agent is None:
        return blocked(_check("agent", "审核官角色", False,
                              "平台没有找到审核官角色，请联系管理员到【子 Agent 定义】核对"))
    if agent.enabled != "是":
        return blocked(_check("agent", "审核官角色", False,
                              "审核官已被停用，请联系管理员到【子 Agent 定义】把它启用"))
    checks.append(_check("agent", "审核官角色", True, "审核官已启用"))

    prompt = await PromptTemplate.get_or_none(code=agent.prompt_code)
    state = agent_service.prompt_state(prompt)
    if state != "正常":
        return blocked(_check("prompt", "提示词模板", False,
                              f"审核官的提示词模板不可用（{state}），"
                              f"请联系管理员到【Prompt模板】处理"))
    checks.append(_check("prompt", "提示词模板", True, "提示词模板正常"))

    tool_count = await FunctionTool.filter(tool_group=agent.tool_group, enabled="是").count()
    if not tool_count:
        return blocked(_check("tool", "审核工具", False,
                              f"审核官的工具分组「{agent.tool_group}」下没有启用中的工具，"
                              f"请联系管理员到【工具中心】启用"))
    checks.append(_check("tool", "审核工具", True, f"可用工具 {tool_count} 个"))

    config = await AiModelConfig.filter(
        model_purpose=model_factory.PURPOSE_AUDIT, enabled="是").order_by("-id").first()
    if config is None:
        return blocked(_check("model", "审核模型", False,
                              "平台还没有启用「审核」用途的对话模型，"
                              "请联系管理员到【AI模型配置】启用一条"))
    if not config.api_key:
        return blocked(_check("model", "审核模型", False,
                              f"「{config.name}」还没有填写 API Key，"
                              f"请联系管理员到【AI模型配置】补上"))
    if not config.model_name:
        return blocked(_check("model", "审核模型", False,
                              f"「{config.name}」还没有填写模型名称，"
                              f"请联系管理员到【AI模型配置】补上"))
    checks.append(_check("model", "审核模型", True, f"已启用「{config.name}」"))
    return {"checks": checks, "blocker": None, "can_run": True}


async def pool_rows(task_id: int) -> tuple[list, dict]:
    """候选池的原始行和它们的租客档案，一次取回。

    排序和候选池页面同一套：先按筛出来的轮次，同一轮里初筛得分高的在前。
    """
    rows = await MatchCandidate.filter(task_id=task_id).order_by(
        "found_round", "-screen_score", "id")
    if not rows:
        return [], {}
    members = {item.id: item for item in await MemberProfile.filter(
        id__in=[row.candidate_member_id for row in rows])}
    return rows, members


def candidate_dict(row: MatchCandidate, member: MemberProfile | None) -> dict:
    """候选在审核页面上的样子：档案字段沿用候选池那一套，再补上审核结论。"""
    data = screener_service.candidate_dict(row, member)
    data.update({
        "reject_code": row.reject_code,
        "reject_label": reject_label(row.reject_code),
        "reject_reason": row.reject_reason,
        "audit_round": row.audit_round,
    })
    return data


def match_evidence(applicant: MemberProfile, candidate: MemberProfile,
                   row: MatchCandidate, applicant_preference: RoommatePreference | None,
                   candidate_preference: RoommatePreference | None) -> list[str]:
    """交付/审核卡上的「可核验依据」：每条都能回到档案字段或放宽记录。

    这不是模型写的解释，也不是画像标签；它是用当前数据现算的匹配依据，
    页面展示、质量检查和人工复核都用同一份口径。算不出的维度不写，
    避免把「没有依据」写成一句看起来很像结论的话。
    """
    evidence: list[str] = []
    if applicant.gender and candidate.gender and applicant.gender == candidate.gender:
        evidence.append(f"合租同性（{candidate.gender}）")
    age = member_service.calc_age(candidate.birth_date)
    if age is not None and applicant_preference is not None:
        if applicant_preference.age_min <= age <= applicant_preference.age_max:
            evidence.append(f"年龄 {age} 岁在申请方 {applicant_preference.age_min}-{applicant_preference.age_max} 岁区间")
    if candidate.rent_budget is not None and applicant_preference is not None:
        if applicant_preference.budget_min <= candidate.rent_budget <= applicant_preference.budget_max:
            evidence.append(f"预算 {candidate.rent_budget} 元在申请方 {applicant_preference.budget_min}-{applicant_preference.budget_max} 元区间")
    if candidate.tidiness and applicant_preference is not None:
        left = member_service.TIDINESS_LEVELS.index(candidate.tidiness) if candidate.tidiness in member_service.TIDINESS_LEVELS else None
        right = member_service.TIDINESS_LEVELS.index(applicant_preference.tidiness_min) if applicant_preference.tidiness_min in member_service.TIDINESS_LEVELS else None
        if left is not None and right is not None and left >= right:
            evidence.append(f"整洁度 {candidate.tidiness} 达到申请方 {applicant_preference.tidiness_min} 的要求")
    if candidate.store_id == applicant.store_id:
        evidence.append(f"同一意向门店（{member_service.store_name(candidate.store_id)}）")
    if candidate.schedule_type and applicant_preference is not None:
        if candidate.schedule_type in split_values(applicant_preference.schedule_accept):
            evidence.append(f"作息 {candidate.schedule_type} 在申请方接受范围内")
    gap = member_service.lease_term_gap(applicant.lease_term, candidate.lease_term)
    if gap is not None and gap < member_service.LEASE_TERM_GAP_LIMIT:
        evidence.append(f"计划租期档位相近（{candidate.lease_term}）")
    if row.relax_note:
        evidence.append(f"放宽记录：{row.relax_note}")
    if applicant.smoking or candidate.smoking:
        evidence.append(f"吸烟：申请方{applicant.smoking or '未填'} / 候选方{candidate.smoking or '未填'}（软冲突，需租客确认）")
    if applicant_preference is not None and not hard_violations(candidate, applicant, applicant_preference):
        evidence.append("候选方满足申请方标为必须的条件")
    if candidate_preference is not None and not hard_violations(applicant, candidate, candidate_preference):
        evidence.append("申请方满足候选方标为必须的条件")
    return evidence


def run_dict(run: AgentRun | None) -> dict | None:
    """最近一次审核运行在页面上的样子。"""
    if run is None:
        return None
    return {
        "id": run.id,
        "run_no": run.run_no,
        "run_type": run.run_type,
        "run_status": run.run_status,
        "total_round": run.total_round,
        "output_summary": run.output_summary,
        "error_message": run.error_message,
        "cost_millis": run.cost_millis,
        "create_time": format_datetime(run.create_time),
    }


def distribution(rows: list[dict]) -> list[dict]:
    """否决分类的人数分布。

    三类固定列全，没有出现的那一类补 0：只列出现过的分类，看的人分不清是没出现
    还是漏了一类，而这三类的分布正是判断下一步该换人还是该补画像的依据。
    """
    counts: dict = {}
    for row in rows:
        code = row.get("reject_code")
        if code:
            counts[code] = counts.get(code, 0) + 1
    return [{"code": code, "label": reject_label(code), "solution": reject_solution(code),
             "count": counts.get(code, 0)} for code in tool_box.REJECT_CODES]


async def _open_run(member: MemberProfile, user_id: int, task: MatchTask,
                    pending: int) -> AgentRun:
    """开一条运行记录。入参快照留着，运行失败之后能复现当时的输入。"""
    snapshot = json.dumps({
        "task_id": task.id,
        "task_no": task.task_no,
        "member_id": member.id,
        "nickname": member.nickname,
        "pending": pending,
    }, ensure_ascii=False)
    return await AgentRun.create(
        run_no=f"AUDIT-{now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}",
        task_id=task.id,
        user_id=user_id,
        run_type=RUN_TYPE,
        run_status=RUN_RUNNING,
        current_round=1,
        input_snapshot=snapshot,
        start_time=now())


async def _close_run(run: AgentRun, started, failed: bool, summary: str,
                     batches: int) -> None:
    """收尾运行记录：状态、最终结论、失败原因、耗时一次写全。"""
    await AgentRun.filter(id=run.id).update(
        run_status=RUN_FAILED if failed else RUN_DONE,
        total_round=batches,
        output_summary=summary[:SUMMARY_LIMIT],
        error_message=summary[:ERROR_LIMIT] if failed else None,
        end_time=now(),
        cost_millis=cost_millis(started))


async def generate(current_user: User) -> dict:
    """按当前租客和最新候选任务执行一轮完整审核。"""
    member = await member_service.get_my_member(current_user, "审核候选")
    state = await readiness(member)
    if not state["can_run"]:
        # 条件不满足就在这里停下，一步都不往模型走，也不留半条运行记录
        raise CustomException(state["blocker"]["message"])
    task = await MatchTask.filter(member_id=member.id).order_by("-id").first()
    pending = await MatchCandidate.filter(
        task_id=task.id, audit_status=AUDIT_WAIT).count()
    started = precise_now()
    run = await _open_run(member, current_user.id, task, pending)
    try:
        result = await build_audit(member.id, task.id, run.id)
    except CustomException as exc:
        await _close_run(run, started, True, exc.message, 0)
        raise
    if result.gate:
        message = (f"审核被中断：{result.conclusion}。请稍后重试；"
                   f"如果每次都这样，请让管理员到【子 Agent 定义】检查审核官的单次工具调用上限")
        await _close_run(run, started, True, message, len(result.batches))
        raise CustomException(message)
    await _close_run(run, started, False, result.conclusion, len(result.batches))
    return {"task_id": task.id, "run_no": run.run_no, "batches": len(result.batches),
            "passed": result.passed, "rejected": result.rejected,
            "pending": result.pending, "conclusion": result.conclusion}


async def my_page(current_user: User) -> dict:
    """租客端【审核结果】：最近一次任务的否决分布、名单与审核结论。"""
    member_service.check_member_role(current_user)
    member = await MemberProfile.get_or_none(user_id=current_user.id)
    state = await readiness(member)
    empty = {"has_profile": member is not None, "readiness": state, "task": None,
             "run": None,
             "counts": {"total": 0, "passed": 0, "rejected": 0, "pending": 0},
             "distribution": distribution([]), "candidates": [], "rejected": []}
    if member is None:
        return empty
    task = await MatchTask.filter(member_id=member.id).order_by("-id").first()
    if task is None:
        return empty
    rows, members = await pool_rows(task.id)
    applicant_preference = await RoommatePreference.get_or_none(member_id=member.id)
    candidate_preferences = {item.member_id: item for item in await RoommatePreference.filter(
        member_id__in=[row.candidate_member_id for row in rows])}
    candidates = []
    for row in rows:
        candidate = members.get(row.candidate_member_id)
        data = candidate_dict(row, candidate)
        if candidate is not None:
            data["evidence"] = match_evidence(
                member, candidate, row, applicant_preference,
                candidate_preferences.get(candidate.id))
        candidates.append(data)
    run = await AgentRun.filter(
        task_id=task.id, run_type=RUN_TYPE).order_by("-id").first()
    if run is None:
        # MATCH-* 任务由主管统一开“匹配编排”运行，审核步骤是其中一轮，
        # 不能因为没有独立 AUDIT-* 运行就误报“还没有审核过”。
        run = await AgentRun.filter(
            task_id=task.id, run_type=MATCH_RUN_TYPE).order_by("-id").first()
    counts = _counts(rows)
    return {
        "has_profile": True,
        "readiness": state,
        "task": screener_service.task_dict(task),
        "run": run_dict(run),
        "counts": {"total": counts["total"], "passed": counts["passed"],
                   "rejected": counts["rejected"], "pending": counts["pending"]},
        "distribution": distribution(candidates),
        "candidates": candidates,
        "rejected": [row for row in candidates if row["audit_status"] == AUDIT_REJECT],
    }


async def candidate_detail(current_user: User, candidate_id: int) -> dict:
    """看一位候选的审核详情：他在意的条件、审核结论与代码复核，走弹窗看。"""
    member = await member_service.get_my_member(current_user, "查看审核详情")
    row = await MatchCandidate.get_or_none(id=candidate_id)
    if row is None:
        raise CustomException("没有找到这位候选，请刷新页面后重试")
    task = await MatchTask.get_or_none(id=row.task_id)
    if task is None or task.member_id != member.id:
        raise CustomException("这位候选不在你的候选池里，请从自己的候选池里打开")
    candidate = await MemberProfile.get_or_none(id=row.candidate_member_id)
    data = candidate_dict(row, candidate)
    if candidate is None:
        return data
    data.update({
        "self_intro": candidate.self_intro,
        "roommate_expectation": candidate.roommate_expectation,
    })
    preference = await RoommatePreference.get_or_none(member_id=candidate.id)
    if preference is None:
        data.update({
            "preference_text": None,
            "must_need": [],
            "recheck": {"violations": [],
                        "note": "这位候选还没有填合住偏好，反向评估没有依据，"
                                "审核时按判断不了处理"},
        })
        return data
    data["preference_text"] = screener_service.preference_text(_preference_dict(preference))
    portrait = await MemberPortrait.filter(
        member_id=candidate.id).order_by("-version", "-id").first()
    data["candidate_portrait"] = portrait_service.portrait_dict(portrait) if portrait else None
    applicant_preference = await RoommatePreference.get_or_none(member_id=member.id)
    data["evidence"] = match_evidence(member, candidate, row, applicant_preference, preference)
    bad = hard_violations(member, candidate, preference)
    lease_bad = lease_term_conflict(member, candidate)
    if lease_bad:
        bad = list(bad) + ["计划租期"]
    data["must_need"] = must_need(preference)
    if bad:
        note = (f"代码按当前硬规则复核：{'、'.join(bad)}这几项不满足，"
                f"这几项正是判 MISMATCH_HARD 的依据")
    else:
        note = "代码按当前硬规则复核：验得清的几项都对得上"
    data["recheck"] = {"violations": bad, "note": note}
    return data
