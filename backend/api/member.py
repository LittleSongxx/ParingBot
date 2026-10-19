"""租客档案接口。"""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from common.auth import get_current_user, require_admin
from common.result import Result
from models import User
from service import member_service

# 这个 router 带 prefix="/member"，下面所有路径前面都自动加上 /member
router = APIRouter(prefix="/member")


class MemberPayload(BaseModel):
    # 全部字段都允许为空，哪些必填由 service 判断并给出人话提示
    nickname: str | None = None
    gender: str | None = None
    birth_date: str | None = None
    rent_budget: int | None = None
    tidiness: str | None = None
    occupation: str | None = None
    lease_term: str | None = None
    store_id: int | None = None
    schedule_type: str | None = None
    has_pet: str | None = None
    smoking: str | None = None
    self_intro: str | None = None
    roommate_expectation: str | None = None
    # 兴趣标签和生活照是数组，页面多选、多图上传之后直接传数组过来
    interest_tags: List[str] | None = None
    photo_paths: List[str] | None = None


class AuditPayload(BaseModel):
    member_id: int
    # 已通过 / 已驳回
    audit_status: str
    # 驳回时必填，通过时可以不写
    audit_remark: str | None = None


class EnabledPayload(BaseModel):
    member_id: int
    # 是 / 否
    enabled: str


@router.get("/my")
async def my(current_user: User = Depends(get_current_user)):
    return Result.success(await member_service.get_my_profile(current_user))


@router.post("/saveMy")
async def save_my(payload: MemberPayload, current_user: User = Depends(get_current_user)):
    return Result.success(await member_service.save_my_profile(current_user, payload.model_dump()))


@router.get("/selectPage")
async def select_page(
    nickname: str = "",
    gender: str = "",
    # 门店不选时前端传 0，0 不在门店清单里，按不加筛选处理
    store_id: int = 0,
    audit_status: str = "",
    enabled: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(await member_service.select_page(
        nickname, gender, store_id or None, audit_status, enabled, page_num, page_size))


@router.get("/selectById/{member_id}")
async def select_by_id(member_id: int, _: User = Depends(require_admin)):
    return Result.success(await member_service.select_by_id(member_id))


@router.post("/audit")
async def audit(payload: AuditPayload, _: User = Depends(require_admin)):
    await member_service.audit_member(payload.member_id, payload.audit_status, payload.audit_remark)
    return Result.success()


@router.post("/updateEnabled")
async def update_enabled(payload: EnabledPayload, _: User = Depends(require_admin)):
    await member_service.update_enabled(payload.member_id, payload.enabled)
    return Result.success()


@router.get("/stores")
async def stores(_: User = Depends(get_current_user)):
    # 用户端填档案、管理端做筛选都要这份清单，登录之后两边都能取
    return Result.success(member_service.list_stores())


@router.get("/interestTags")
async def interest_tags(_: User = Depends(get_current_user)):
    return Result.success(await member_service.list_interest_tags())