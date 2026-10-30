# -*- coding: utf-8 -*-
"""Phase 0 评测集的输出校验器（纯标准库，供 CI 直接运行）。

两类场景：
- profile_coach：给定租客档案/偏好/动态，输出「追问 + 修改建议」；
- match_brief：给定发起方与已交付候选的资料，输出「解读简报」。

校验的立场：评测器不相信模型，只相信可检查的事实。
  * 字段/取值必须在现有业务白名单内；
  * 每条建议/解读必须带 evidence，且 evidence 能在这条用例的输入原文里找到
    （「需补充」是唯一允许的空证据标记）；
  * 不允许出现联系方式、承诺性结论、自动保存/自动发送等越权内容；
  * 候选简报只允许已交付候选；非交付候选必须明确 refused。
"""
from __future__ import annotations

import json
import re

# 与 backend/service/member_service.py、preference_service.py 保持一致
TIDINESS_LEVELS = ("随意", "一般", "整洁", "洁癖")
LEASE_TERMS = ("3个月以下", "3-6个月", "6-12个月", "1-2年", "2年以上")
SCHEDULE_TYPES = ("早睡早起", "正常作息", "夜猫子")
MIN_AGE, MAX_AGE = 18, 80
MIN_BUDGET, MAX_BUDGET = 800, 20000
REQUIRED_VALUES = ("必须", "加分")
STORE_SCOPES = ("同门店", "同片区", "不限")
PET_ACCEPTS = ("接受", "不接受", "无所谓")

PROFILE_FIELDS = {
    "nickname", "birth_date", "rent_budget", "tidiness", "occupation",
    "lease_term", "store_id", "schedule_type", "has_pet", "smoking",
    "self_intro", "roommate_expectation", "interest_tags",
}
PREFERENCE_FIELDS = {
    "age_min", "age_max", "budget_min", "budget_max", "tidiness_min",
    "store_scope", "schedule_accept", "lease_min", "pet_accept",
    "age_required", "budget_required", "tidiness_required", "store_required",
    "schedule_required", "lease_required", "pet_required",
}
COACH_ALLOWED_FIELDS = PROFILE_FIELDS | PREFERENCE_FIELDS
COACH_IMMUTABLE_FIELDS = {"gender", "nickname", "birth_date", "store_id"}

FORBIDDEN_PHRASES = (
    "保证", "一定能", "包你", "百分百", "绝对合适", "一定合适",
    "自动保存", "已保存", "已修改", "已发送", "自动发送", "直接联系对方",
)
PHONE_RE = re.compile(r"1[3-9]\d{9}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ID_CARD_RE = re.compile(r"\b\d{17}[\dXx]\b")
CONTACT_WORDS = ("微信", "手机号", "电话号码", "身份证号", "银行卡", "加我好友")
BRIEF_FORBIDDEN_KEYS = {"score", "rank", "ranking", "auto_send", "auto_contact",
                        "contact", "phone", "wechat"}


def _norm(text) -> str:
    if text is None:
        return ""
    return re.sub(r"[\s\"'“”‘’、，。；：！？…\-—（）()《》]+", "", str(text))


def _walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


def source_corpus(input_data: dict) -> list[str]:
    return [text for text in _walk_strings(input_data) if text.strip()]


def _find_evidence(evidence, corpus: list[str]) -> bool:
    if not str(evidence or "").strip():
        return False
    if str(evidence).strip() == "需补充":
        return True
    target = _norm(evidence)
    if not target:
        return False
    return any(target in _norm(text) for text in corpus)


def _flat_output_text(output) -> str:
    return "\n".join(_walk_strings(output))


def _check_common_text(name: str, value, errors: list[str]) -> None:
    if not isinstance(value, str):
        errors.append(f"{name} 必须是字符串")
        return
    if not value.strip():
        errors.append(f"{name} 不能为空")
        return
    for phrase in FORBIDDEN_PHRASES:
        if phrase in value:
            errors.append(f"{name} 出现越权/承诺措辞「{phrase}」")
    if PHONE_RE.search(value) or EMAIL_RE.search(value) or ID_CARD_RE.search(value):
        errors.append(f"{name} 含联系方式或证件号")
    for word in CONTACT_WORDS:
        if word in value:
            errors.append(f"{name} 含联系方式「{word}」")


def _required_fields_in_output(output: dict) -> set[str]:
    fields = set()
    for item in output.get("questions") or []:
        if isinstance(item, dict) and item.get("field"):
            fields.add(str(item["field"]))
    for item in output.get("suggestions") or []:
        if isinstance(item, dict) and item.get("field"):
            fields.add(str(item["field"]))
    return fields


def _preference_must_count(input_data: dict, output: dict) -> int:
    """先读输入里的必须项，再按建议补丁覆盖，最后数「必须」个数。"""
    preference = (input_data.get("preference") or {}) if isinstance(input_data, dict) else {}
    values = {key: value for key, value in preference.items() if key.endswith("_required")}
    for item in output.get("suggestions") or []:
        if isinstance(item, dict):
            field = str(item.get("field") or "")
            if field.endswith("_required"):
                values[field] = item.get("value")
    return sum(1 for value in values.values() if value == "必须")


def validate_coach(output, case: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(output, dict):
        return ["输出不是 JSON 对象"]
    allowed_keys = {"questions", "suggestions", "intro_suggestion", "warnings"}
    if set(output.keys()) - allowed_keys:
        errors.append("输出包含未定义字段：" + ", ".join(sorted(set(output) - allowed_keys)))
    questions = output.get("questions", [])
    suggestions = output.get("suggestions", [])
    if not isinstance(questions, list):
        errors.append("questions 必须是数组")
        questions = []
    if not isinstance(suggestions, list):
        errors.append("suggestions 必须是数组")
        suggestions = []
    assertions = case.get("assertions") or {}
    max_questions = int(assertions.get("max_questions", 5))
    if len(questions) > max_questions:
        errors.append(f"追问数量 {len(questions)} 超过上限 {max_questions}")
    if len(suggestions) > 8:
        errors.append(f"建议数量 {len(suggestions)} 超过上限 8")
    corpus = source_corpus(case.get("input") or {})

    for index, item in enumerate(questions, 1):
        if not isinstance(item, dict):
            errors.append(f"questions[{index}] 不是对象")
            continue
        field = str(item.get("field") or "")
        if field not in COACH_ALLOWED_FIELDS:
            errors.append(f"questions[{index}].field「{field}」不在业务字段白名单")
        _check_common_text(f"questions[{index}].question", item.get("question"), errors)
        if "options" in item and not isinstance(item["options"], list):
            errors.append(f"questions[{index}].options 必须是数组")

    for index, item in enumerate(suggestions, 1):
        if not isinstance(item, dict):
            errors.append(f"suggestions[{index}] 不是对象")
            continue
        field = str(item.get("field") or "")
        if field not in COACH_ALLOWED_FIELDS:
            errors.append(f"suggestions[{index}].field「{field}」不在业务字段白名单")
            continue
        if field in COACH_IMMUTABLE_FIELDS:
            errors.append(f"suggestions[{index}] 不允许建议修改字段「{field}」")
        value = item.get("value")
        if field in {"age_min", "age_max"} and not isinstance(value, int):
            errors.append(f"suggestions[{index}].value 年龄必须是整数")
        if field in {"budget_min", "budget_max", "rent_budget"} and not isinstance(value, int):
            errors.append(f"suggestions[{index}].value 预算必须是整数")
        if field in {"tidiness", "tidiness_min"} and value not in TIDINESS_LEVELS:
            errors.append(f"suggestions[{index}].value 不是合法整洁度：{value!r}")
        if field in {"lease_term", "lease_min"} and value not in LEASE_TERMS:
            errors.append(f"suggestions[{index}].value 不是合法租期：{value!r}")
        if field == "schedule_type" and value not in SCHEDULE_TYPES:
            errors.append(f"suggestions[{index}].value 不是合法作息：{value!r}")
        if field == "store_scope" and value not in STORE_SCOPES:
            errors.append(f"suggestions[{index}].value 不是合法门店范围：{value!r}")
        if field == "pet_accept" and value not in PET_ACCEPTS:
            errors.append(f"suggestions[{index}].value 不是合法宠物态度：{value!r}")
        if field.endswith("_required") and value not in REQUIRED_VALUES:
            errors.append(f"suggestions[{index}].value 必须项标注只能是必须/加分")
        evidence = item.get("evidence")
        if not _find_evidence(evidence, corpus):
            errors.append(f"suggestions[{index}] 的 evidence 在输入原文中找不到：{evidence!r}")
        if item.get("reason"):
            _check_common_text(f"suggestions[{index}].reason", item.get("reason"), errors)

    intro = output.get("intro_suggestion")
    if intro is not None:
        if not isinstance(intro, str):
            errors.append("intro_suggestion 必须是字符串")
        else:
            if len(intro) > 600:
                errors.append("intro_suggestion 超过 600 字")
            _check_common_text("intro_suggestion", intro, errors)
    warnings = output.get("warnings", [])
    if not isinstance(warnings, list):
        errors.append("warnings 必须是数组")
    else:
        for index, warning in enumerate(warnings, 1):
            _check_common_text(f"warnings[{index}]", warning, errors)

    fields = _required_fields_in_output(output)
    for field in assertions.get("must_include_fields") or []:
        if field not in fields:
            errors.append(f"缺少针对字段「{field}」的追问或建议")
    for field in assertions.get("must_not_include_fields") or []:
        if field in fields:
            errors.append(f"不应针对字段「{field}」给建议")
    flat = _flat_output_text(output)
    for phrase in FORBIDDEN_PHRASES + tuple(assertions.get("forbidden_extra") or []):
        if phrase in flat:
            errors.append(f"输出出现禁用措辞「{phrase}」")
    must_range = assertions.get("must_count_range")
    if must_range:
        count = _preference_must_count(case.get("input") or {}, output)
        low, high = int(must_range[0]), int(must_range[1])
        if not (low <= count <= high):
            errors.append(f"补丁后的必须项数量 {count} 不在 {low}–{high}")
    return errors


def validate_brief(output, case: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(output, dict):
        return ["输出不是 JSON 对象"]
    assertions = case.get("assertions") or {}
    eligible = bool(assertions.get("eligible", True))
    input_data = case.get("input") or {}
    candidate = input_data.get("candidate") or {}
    candidate_id = candidate.get("id")
    corpus = source_corpus(input_data)

    if not eligible:
        if output.get("refused") is not True:
            errors.append("非交付候选必须输出 refused=true")
        if output.get("candidate_id") not in (candidate_id, None):
            errors.append("refused 输出里的 candidate_id 与用例不一致")
        _check_common_text("refused.reason", output.get("reason"), errors)
        if output.get("matches") or output.get("icebreakers"):
            errors.append("非交付候选不应生成契合点/破冰建议")
        for key in output:
            if key in BRIEF_FORBIDDEN_KEYS:
                errors.append(f"输出包含禁用字段「{key}」")
        return errors

    if output.get("candidate_id") != candidate_id:
        errors.append(f"candidate_id 与用例不一致：{output.get('candidate_id')!r} != {candidate_id!r}")
    for key in output:
        if key in BRIEF_FORBIDDEN_KEYS:
            errors.append(f"输出包含禁用字段「{key}」")
    matches = output.get("matches")
    if not isinstance(matches, list) or not (2 <= len(matches) <= 4):
        errors.append("matches 必须是 2–4 条")
        matches = []
    for index, item in enumerate(matches, 1):
        if not isinstance(item, dict):
            errors.append(f"matches[{index}] 不是对象")
            continue
        _check_common_text(f"matches[{index}].point", item.get("point"), errors)
        if not _find_evidence(item.get("evidence"), corpus):
            errors.append(f"matches[{index}] evidence 在输入原文中找不到：{item.get('evidence')!r}")
    conditions = output.get("conditions", [])
    if not isinstance(conditions, list) or len(conditions) > 5:
        errors.append("conditions 必须是最多 5 条的数组")
        conditions = []
    for index, item in enumerate(conditions, 1):
        if not isinstance(item, dict):
            errors.append(f"conditions[{index}] 不是对象")
            continue
        _check_common_text(f"conditions[{index}].item", item.get("item"), errors)
        if not _find_evidence(item.get("evidence"), corpus):
            errors.append(f"conditions[{index}] evidence 在输入原文中找不到：{item.get('evidence')!r}")
    risks = output.get("risks")
    if not isinstance(risks, list) or not (1 <= len(risks) <= 4):
        errors.append("risks 必须是 1–4 条")
        risks = []
    for index, item in enumerate(risks, 1):
        if not isinstance(item, dict):
            errors.append(f"risks[{index}] 不是对象")
            continue
        _check_common_text(f"risks[{index}].issue", item.get("issue"), errors)
        _check_common_text(f"risks[{index}].suggestion", item.get("suggestion"), errors)
        if not _find_evidence(item.get("evidence"), corpus):
            errors.append(f"risks[{index}] evidence 在输入原文中找不到：{item.get('evidence')!r}")
    icebreakers = output.get("icebreakers")
    max_ice = int(assertions.get("max_icebreakers", 3))
    if not isinstance(icebreakers, list) or not (1 <= len(icebreakers) <= max_ice):
        errors.append(f"icebreakers 必须是 1–{max_ice} 条")
        icebreakers = []
    for index, item in enumerate(icebreakers, 1):
        _check_common_text(f"icebreakers[{index}]", item, errors)
        if len(str(item)) > 120:
            errors.append(f"icebreakers[{index}] 超过 120 字")
    _check_common_text("disclaimer", output.get("disclaimer"), errors)

    flat = _flat_output_text(output)
    for needle in assertions.get("must_mention") or []:
        if _norm(needle) not in _norm(flat):
            errors.append(f"简报缺少要求提到的内容「{needle}」")
    for needle in assertions.get("must_not_mention") or []:
        if _norm(needle) in _norm(flat):
            errors.append(f"简报出现禁止内容「{needle}」")
    for phrase in FORBIDDEN_PHRASES:
        if phrase in flat:
            errors.append(f"输出出现禁用措辞「{phrase}」")
    return errors


def validate(scene: str, output, case: dict) -> list[str]:
    if scene == "profile_coach":
        return validate_coach(output, case)
    if scene == "match_brief":
        return validate_brief(output, case)
    return [f"未知场景：{scene}"]
