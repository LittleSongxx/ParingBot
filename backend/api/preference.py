"""合住偏好接口。"""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from common.auth import get_current_user
from common.result import Result
from models import User
from service import preference_service

# 这个 router 带 prefix="/preference"，下面所有路径前面都自动加上 /preference
router = APIRouter(prefix="/preference")


class PreferencePayload(BaseModel):
    # 七个维度各有一份取值和一个「必须 / 加分」标注，哪些必填由 service 判断并给出人话提示
    age_min: int | None = None
    age_max: int | None = None
    age_required: str | None = None
    budget_min: int | None = None
    budget_max: int | None = None
    budget_required: str | None = None
    # 随意 / 一般 / 整洁 / 洁癖 / 不限
    tidiness_min: str | None = None
    tidiness_required: str | None = None
    # 同门店 / 同片区 / 不限
    store_scope: str | None = None
    store_required: str | None = None
    # 作息是多选，页面直接把选中的数组传过来
    schedule_accept: List[str] | None = None
    schedule_required: str | None = None
    # 最短租期，取值同租客档案里的计划租期，多一个「不限」
    lease_min: str | None = None
    lease_required: str | None = None
    # 接受 / 不接受 / 无所谓
    pet_accept: str | None = None
    pet_required: str | None = None


@router.get("/my")
async def my(current_user: User = Depends(get_current_user)):
    return Result.success(await preference_service.get_my_preference(current_user))


@router.post("/saveMy")
async def save_my(payload: PreferencePayload, current_user: User = Depends(get_current_user)):
    return Result.success(await preference_service.save_my_preference(
        current_user, payload.model_dump()))


@router.get("/options")
async def options(_: User = Depends(get_current_user)):
    # 各维度的取值清单和必须项区间都由后端给出，页面不自己维护一份
    return Result.success(preference_service.list_options())
