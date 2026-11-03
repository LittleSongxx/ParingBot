#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线评测的规则口径（纯标准库，无后端依赖）。

这里只回答一件事：按当前业务规则，两位租客在硬条件上到底能不能合住。
口径与 backend/service 对齐（2026-11 版本）：

* 只验「双方标为必须、而且确实有约束」的维度，共七维：年龄、预算、整洁度、
  门店、作息、租期、宠物态度；
* 「不限」「无所谓」「三档作息全选」「最低整洁度/最短租期选最低档」都算没有约束，
  不参与硬规则判定；
* 合租只找同性；双方计划租期档位差 >= 2 视为硬冲突（相邻档位可协商）；
* 值缺失时不判违规（那属于「判断不了」，交给模型），代码只判验得清的。

年龄按 as_of 日期现算，默认取调用当天；冻结标签/场景生成时传固定 as_of，
保证离线产物可复现。
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

# 有序档位：整洁度与租期都是「前面的档低、后面的档高」
TIDINESS_LEVELS = ("随意", "一般", "整洁", "洁癖")
LEASE_TERMS = ("3个月以下", "3-6个月", "6-12个月", "1-2年", "2年以上")
SCHEDULE_TYPES = ("早睡早起", "正常作息", "夜猫子")

# 计划租期档位差 >= 2 视为硬冲突（与 backend/service/member_service.py 一致）
LEASE_TERM_GAP_LIMIT = 2

# 七个偏好维度的编码与中文名，顺序与 backend/service/preference_service.py 一致
DIMENSIONS = (
    ("age", "年龄"),
    ("budget", "预算"),
    ("tidiness", "整洁度"),
    ("store", "门店"),
    ("schedule", "作息"),
    ("lease", "租期"),
    ("pet", "宠物态度"),
)
DIM_NAMES = dict(DIMENSIONS)
MUST = "必须"
BONUS = "加分"

# 固定的 20 家门店与片区（与 backend/service/member_service.py 保持一致）
STORE_LIST = (
    (1, "张江店"), (2, "金桥店"), (3, "唐镇店"), (4, "川沙店"),
    (5, "漕河泾店"), (6, "徐家汇店"), (7, "龙华店"), (8, "田林店"),
    (9, "五角场店"), (10, "新江湾店"), (11, "控江店"), (12, "大桥店"),
    (13, "莘庄店"), (14, "七宝店"), (15, "虹桥枢纽店"), (16, "紫竹店"),
    (17, "长风店"), (18, "真如店"), (19, "桃浦店"), (20, "中山北路店"),
)
STORE_NAMES = dict(STORE_LIST)
STORE_AREAS = {
    1: "浦东", 2: "浦东", 3: "浦东", 4: "浦东",
    5: "徐汇", 6: "徐汇", 7: "徐汇", 8: "徐汇",
    9: "杨浦", 10: "杨浦", 11: "杨浦", 12: "杨浦",
    13: "闵行", 14: "闵行", 15: "闵行", 16: "闵行",
    17: "普陀", 18: "普陀", 19: "普陀", 20: "普陀",
}

# 性别冲突时用的统一标签；性别不在七维偏好里，由代码兜底
GENDER_DIM = "性别"


def store_name(store_id: int | None) -> str | None:
    """按门店编码取门店名。"""
    return STORE_NAMES.get(store_id)


def area_of(store_id: int | None) -> str | None:
    """按门店编码取片区名。"""
    return STORE_AREAS.get(store_id)


def age_of(birth: date | None, as_of: date | None = None) -> int | None:
    """按出生日期现算年龄；缺值时返回 None。"""
    if birth is None:
        return None
    today = as_of or date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def term_gap(one: str | None, other: str | None) -> int | None:
    """两个计划租期的档位距离；任一侧缺值/非法返回 None。"""
    try:
        return abs(LEASE_TERMS.index(one) - LEASE_TERMS.index(other))
    except (ValueError, AttributeError):
        return None


def lease_conflict(one: str | None, other: str | None) -> bool:
    """双方计划租期档位差 >= 2 即硬冲突（例如 3个月以下 vs 6-12个月）。"""
    gap = term_gap(one, other)
    return gap is not None and gap >= LEASE_TERM_GAP_LIMIT


def gender_conflict(applicant, candidate) -> bool:
    """合租只找同性：双方性别都填了而且不一样。"""
    return bool(applicant.gender and candidate.gender and applicant.gender != candidate.gender)


def _below(order: tuple, value, floor) -> bool:
    """按档位高低比：有一头没填或不合法就不判，比下限低才算不满足。"""
    if not value or not floor or value not in order or floor not in order:
        return False
    return order.index(value) < order.index(floor)


def same_place(one_store_id: int | None, other_store_id: int | None, scope: str | None) -> bool:
    """门店维度按「和另一方在不在一个地方」算：同门店看门店，同片区看片区。"""
    if scope == "同门店":
        return bool(one_store_id) and one_store_id == other_store_id
    area = area_of(other_store_id)
    return bool(area) and area_of(one_store_id) == area


def has_constraint(preference, code: str) -> bool:
    """这个维度有没有实际约束（决定硬规则要不要验它）。"""
    if code == "age":
        return preference.age_min is not None and preference.age_max is not None
    if code == "budget":
        return preference.budget_min is not None and preference.budget_max is not None
    if code == "tidiness":
        return preference.tidiness_min not in (None, TIDINESS_LEVELS[0])
    if code == "store":
        return preference.store_scope in ("同门店", "同片区")
    if code == "schedule":
        accepted = {item for item in (preference.schedule_accept or []) if item}
        return bool(accepted) and accepted != set(SCHEDULE_TYPES)
    if code == "lease":
        return preference.lease_min not in (None, LEASE_TERMS[0])
    if code == "pet":
        return preference.pet_accept == "不接受"
    raise ValueError("未知的偏好维度编码：" + str(code))


def required_dimensions(preference) -> list[str]:
    """标为「必须」的维度编码；顺序固定为七维顺序。"""
    codes = []
    for code, _name in DIMENSIONS:
        if getattr(preference, code + "_required", BONUS) == MUST:
            codes.append(code)
    return codes


def required_constraints(preference) -> list[str]:
    """标为「必须」、而且确实有约束的维度编码 —— 硬规则真正要验的清单。"""
    return [code for code in required_dimensions(preference) if has_constraint(preference, code)]


def violates(applicant, candidate, preference, code: str, as_of: date | None = None) -> bool:
    """申请方在「候选方的某一个维度」上是不是不满足；验不清时返回 False。"""
    if code == "age":
        age = age_of(applicant.birth_date, as_of)
        if age is None or preference.age_min is None or preference.age_max is None:
            return False
        return age < preference.age_min or age > preference.age_max
    if code == "budget":
        if applicant.rent_budget is None:
            return False
        if preference.budget_min is None or preference.budget_max is None:
            return False
        return (applicant.rent_budget < preference.budget_min
                or applicant.rent_budget > preference.budget_max)
    if code == "tidiness":
        return _below(TIDINESS_LEVELS, applicant.tidiness, preference.tidiness_min)
    if code == "store":
        return not same_place(applicant.store_id, candidate.store_id, preference.store_scope)
    if code == "schedule":
        accepted = [item for item in (preference.schedule_accept or []) if item]
        if not applicant.schedule_type or not accepted:
            return False
        return applicant.schedule_type not in accepted
    if code == "lease":
        return _below(LEASE_TERMS, applicant.lease_term, preference.lease_min)
    if code == "pet":
        # 这一维问的是「能不能接受室友养宠」，比的是档案里的是否养宠：
        # 只有「不接受」会把养宠的人挡掉，「接受」「无所谓」都不设门槛
        if not applicant.has_pet:
            return False
        return preference.pet_accept == "不接受" and applicant.has_pet == "有"
    raise ValueError("未知的偏好维度编码：" + str(code))


def hard_violations(applicant, candidate, candidate_preference,
                    as_of: date | None = None) -> list[str]:
    """候选方标为必须、且申请方确实违反的维度中文名列表。

    这是「候选方那一侧」的单向判定：申请方没满足候选方的必须项。
    """
    names = []
    for code in required_constraints(candidate_preference):
        if violates(applicant, candidate, candidate_preference, code, as_of):
            names.append(DIM_NAMES[code])
    return names


def bidirectional_violations(applicant, applicant_preference, candidate,
                             candidate_preference, as_of: date | None = None) -> list[str]:
    """双向硬规则违规：性别、租期档差，以及双方各自的必须项。

    返回中文名去重后的列表；同一维度两边都违规只记一次。
    """
    found: list[str] = []
    if gender_conflict(applicant, candidate):
        found.append(GENDER_DIM)
    if lease_conflict(applicant.lease_term, candidate.lease_term):
        found.append(DIM_NAMES["lease"])
    found.extend(hard_violations(applicant, candidate, candidate_preference, as_of))
    found.extend(hard_violations(candidate, applicant, applicant_preference, as_of))
    return list(dict.fromkeys(found))


def is_hard_eligible(applicant, applicant_preference, candidate,
                     candidate_preference, as_of: date | None = None) -> bool:
    """双向硬规则全部通过才算硬可匹配。"""
    return not bidirectional_violations(applicant, applicant_preference,
                                        candidate, candidate_preference, as_of)


def lease_terms_within(term: str | None) -> list[str]:
    """与这个计划租期档位差 < 2 的档位清单（候选池预筛用）。"""
    if term not in LEASE_TERMS:
        return []
    index = LEASE_TERMS.index(term)
    return [value for position, value in enumerate(LEASE_TERMS)
            if abs(position - index) < LEASE_TERM_GAP_LIMIT]


def split_values(value: Iterable[str] | str | None) -> list[str]:
    """把 SQL 里逗号分隔的多值字段拆成清单（兼容中文逗号与空白）。"""
    if not value:
        return []
    if isinstance(value, str):
        raw = value.replace("，", ",").split(",")
    else:
        raw = list(value)
    return [item.strip() for item in raw if item and item.strip()]