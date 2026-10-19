"""合住偏好业务逻辑。

租客在用户端把七个维度填一遍：年龄、预算、整洁度、门店范围、作息、租期、宠物态度。
每个维度都带一个「必须 / 加分」标注，这个标注决定了后面筛选候选时谁能被放宽：
标「必须」的维度任何情况下都不许动，只有标「加分」的才可能放宽。

七个维度里标「必须」的要控制在 2 到 4 个。全填必须的话，候选不够时筛选官一个
维度都动不了，匹配会直接卡死；一个必须都不填，等于没有任何硬性条件。
"""

from typing import List, Tuple

from common.exception_handler import CustomException
from common.text import split_values
from common.times import format_datetime
from models import RoommatePreference, User
from service import member_service
from service.member_service import (LEASE_TERMS, MAX_AGE, MAX_BUDGET, MIN_AGE, MIN_BUDGET,
                                    SCHEDULE_TYPES, TIDINESS_LEVELS)

# 「必须」这个条件是硬门槛，「加分」只是优先满足，候选不够时可以被筛选官放宽
REQUIRED_OPTIONS = ("必须", "加分")
MUST = "必须"
BONUS = "加分"

# 七个维度：编码给程序和模型用，中文名给页面和日志用，最后一列是对应的标注列名
DIMENSIONS: Tuple[Tuple[str, str, str], ...] = (
    ("age", "年龄", "age_required"),
    ("budget", "预算", "budget_required"),
    ("tidiness", "整洁度", "tidiness_required"),
    ("store", "门店", "store_required"),
    ("schedule", "作息", "schedule_required"),
    ("lease", "租期", "lease_required"),
    ("pet", "宠物态度", "pet_required"),
)

STORE_SCOPES = ("同门店", "同片区", "不限")
PET_ACCEPTS = ("接受", "不接受", "无所谓")
# 「不限」在整洁度和租期上表示不设下限，落库时存空值；
# 「无所谓」表示这个维度对谁都成立
NO_LIMIT = "不限"
NO_OPINION = "无所谓"

# 必须项的数量区间，同时卡住「不许全填必须」和「至少留几个能给筛选官放宽的」
MIN_MUST_COUNT = 2
MAX_MUST_COUNT = 4


def _check_range(payload: dict, min_key: str, max_key: str, label: str,
                 low: int, high: int) -> Tuple[int, int]:
    """校验成对出现的上下限，返回整理好的两个整数。"""
    try:
        low_value = int(payload.get(min_key))
        high_value = int(payload.get(max_key))
    except (TypeError, ValueError):
        raise CustomException(f"请填写{label}范围")
    if low_value < low or high_value > high:
        raise CustomException(f"{label}范围请填 {low} 到 {high} 之间")
    if low_value > high_value:
        raise CustomException(f"{label}的下限不能大于上限")
    return low_value, high_value


def _check_flag(payload: dict, key: str, label: str) -> str:
    """校验「必须 / 加分」标注。标注决定了这个维度能不能被放宽，不许留空。"""
    value = (payload.get(key) or "").strip()
    if value not in REQUIRED_OPTIONS:
        raise CustomException(f"{label}要选「" + "」或「".join(REQUIRED_OPTIONS) + "」")
    return value


def _check_choice(payload: dict, key: str, label: str, options: tuple) -> str | None:
    """校验单选取值，选「不限」时返回空值表示不设下限。"""
    value = (payload.get(key) or "").strip()
    if not value:
        raise CustomException(f"请选择{label}")
    if value == NO_LIMIT:
        return None
    if value not in options:
        raise CustomException(f"{label}只能在 " + "、".join(list(options) + [NO_LIMIT]) + " 里选")
    return value


def _check_direct_choice(payload: dict, key: str, label: str, options: tuple) -> str:
    """校验取值本身就是完整清单的单选，没有「不限」这一档。"""
    value = (payload.get(key) or "").strip()
    if not value:
        raise CustomException(f"请选择{label}")
    if value not in options:
        raise CustomException(f"{label}只能在 " + "、".join(options) + " 里选")
    return value


def _check_schedule(payload: dict) -> str:
    """作息是多选，至少选一个；三档全选等于不限制，后面算可放宽维度时会认出来。"""
    values = split_values(payload.get("schedule_accept"))
    if not values:
        raise CustomException("请至少选一个可以接受的作息")
    unknown = [one for one in values if one not in SCHEDULE_TYPES]
    if unknown:
        raise CustomException("作息只能在 " + "、".join(SCHEDULE_TYPES) + " 里选")
    return ",".join(values)


def has_constraint(preference: RoommatePreference, code: str) -> bool:
    """这个维度有没有实际约束。

    「不限」「无所谓」、最低整洁度与最短租期选最低一档、把三种作息全选上，
    这些取值对谁都成立，放宽它们等于没放宽。筛选官不该把有限的放宽次数花在这种维度上。
    """
    if code == "age":
        return preference.age_min is not None and preference.age_max is not None
    if code == "budget":
        return preference.budget_min is not None and preference.budget_max is not None
    if code == "tidiness":
        # 最低档就是最宽的一档，选了它等于不设下限
        return preference.tidiness_min not in (None, TIDINESS_LEVELS[0])
    if code == "store":
        return preference.store_scope in ("同门店", "同片区")
    if code == "schedule":
        accepted = set(split_values(preference.schedule_accept))
        return bool(accepted) and accepted != set(SCHEDULE_TYPES)
    if code == "lease":
        return preference.lease_min not in (None, LEASE_TERMS[0])
    if code == "pet":
        # 「接受」和「无所谓」都不排除任何人，只有「不接受室友养宠」是真约束
        return preference.pet_accept == "不接受"
    raise ValueError("未知的偏好维度编码：" + str(code))


def must_dimensions(preference: RoommatePreference) -> List[dict]:
    """标了「必须」的维度，这些维度筛选官任何情况下都不许放宽。"""
    return [
        {"code": code, "name": name}
        for code, name, column in DIMENSIONS
        if getattr(preference, column) == MUST
    ]


def relaxable_dimensions(preference: RoommatePreference) -> List[dict]:
    """标了「加分」、而且确实有约束的维度，筛选官只能从这几个里挑着放宽。"""
    return [
        {"code": code, "name": name}
        for code, name, column in DIMENSIONS
        if getattr(preference, column) == BONUS and has_constraint(preference, code)
    ]


def preference_dict(preference: RoommatePreference) -> dict:
    """手写转字典：作息拆成数组，再带上两份派生信息。

    must_dimensions 和 relaxable_dimensions 是偏好的两份派生清单：页面上直接标出来
    哪些条件不能动、哪些以后可以松，筛选候选时也读这两份清单。
    """
    return {
        "id": preference.id,
        "member_id": preference.member_id,
        "age_min": preference.age_min,
        "age_max": preference.age_max,
        "age_required": preference.age_required,
        "budget_min": preference.budget_min,
        "budget_max": preference.budget_max,
        "budget_required": preference.budget_required,
        "tidiness_min": preference.tidiness_min,
        "tidiness_required": preference.tidiness_required,
        "store_scope": preference.store_scope,
        "store_required": preference.store_required,
        "schedule_accept": split_values(preference.schedule_accept),
        "schedule_required": preference.schedule_required,
        "lease_min": preference.lease_min,
        "lease_required": preference.lease_required,
        "pet_accept": preference.pet_accept,
        "pet_required": preference.pet_required,
        "must_dimensions": must_dimensions(preference),
        "relaxable_dimensions": relaxable_dimensions(preference),
        "create_time": format_datetime(preference.create_time),
        "update_time": format_datetime(preference.update_time),
    }


async def get_my_preference(current_user: User) -> dict | None:
    """取当前登录租客的合住偏好，还没设置过时返回空，由页面提示去填。"""
    member = await member_service.get_my_member(current_user, "设置合住偏好")
    preference = await RoommatePreference.get_or_none(member_id=member.id)
    return preference_dict(preference) if preference else None


async def save_my_preference(current_user: User, payload: dict) -> dict:
    """保存当前登录租客的合住偏好，第一次保存就是新建。"""
    member = await member_service.get_my_member(current_user, "设置合住偏好")
    age_min, age_max = _check_range(
        payload, "age_min", "age_max", "年龄", MIN_AGE, MAX_AGE)
    budget_min, budget_max = _check_range(
        payload, "budget_min", "budget_max", "预算", MIN_BUDGET, MAX_BUDGET)
    values = {
        "age_min": age_min,
        "age_max": age_max,
        "age_required": _check_flag(payload, "age_required", "年龄"),
        "budget_min": budget_min,
        "budget_max": budget_max,
        "budget_required": _check_flag(payload, "budget_required", "预算"),
        "tidiness_min": _check_choice(
            payload, "tidiness_min", "最低整洁度", TIDINESS_LEVELS),
        "tidiness_required": _check_flag(payload, "tidiness_required", "整洁度"),
        "store_scope": _check_direct_choice(
            payload, "store_scope", "门店范围", STORE_SCOPES),
        "store_required": _check_flag(payload, "store_required", "门店"),
        "schedule_accept": _check_schedule(payload),
        "schedule_required": _check_flag(payload, "schedule_required", "作息"),
        "lease_min": _check_choice(
            payload, "lease_min", "最短租期", LEASE_TERMS),
        "lease_required": _check_flag(payload, "lease_required", "租期"),
        "pet_accept": _check_direct_choice(
            payload, "pet_accept", "对室友养宠的态度", PET_ACCEPTS),
        "pet_required": _check_flag(payload, "pet_required", "宠物态度"),
    }

    # 必须项数量是这个表单最容易填错的地方，提示里直接把当前数量写出来，
    # 租客照着这句话就能改
    must_count = sum(1 for _, _, column in DIMENSIONS if values[column] == MUST)
    if must_count < MIN_MUST_COUNT or must_count > MAX_MUST_COUNT:
        raise CustomException(
            f"标为「必须」的维度要在 {MIN_MUST_COUNT} 到 {MAX_MUST_COUNT} 个之间，"
            f"现在有 {must_count} 个；其余的请标成「加分」")

    preference = await RoommatePreference.get_or_none(member_id=member.id)
    if preference is None:
        preference = await RoommatePreference.create(member_id=member.id, **values)
    else:
        await RoommatePreference.filter(id=preference.id).update(**values)
        preference = await RoommatePreference.get(id=preference.id)
    return preference_dict(preference)


def list_options() -> dict:
    """页面下拉框和提示文案要用到的取值清单，全部从这一处取，页面不再自己维护一份。"""
    return {
        "tidiness_levels": list(TIDINESS_LEVELS),
        "lease_terms": list(LEASE_TERMS),
        "schedule_types": list(SCHEDULE_TYPES),
        "store_scopes": list(STORE_SCOPES),
        "pet_accepts": list(PET_ACCEPTS),
        "required_options": list(REQUIRED_OPTIONS),
        "age_range": {"min": MIN_AGE, "max": MAX_AGE},
        "budget_range": {"min": MIN_BUDGET, "max": MAX_BUDGET},
        "must_count_range": {"min": MIN_MUST_COUNT, "max": MAX_MUST_COUNT},
        "dimension_count": len(DIMENSIONS),
    }
