"""兴趣标签词表接口。"""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from common.auth import get_current_user, require_admin
from common.result import Result
from models import User
from service import interest_tag_service

# 这个 router 带 prefix="/interestTag"，下面所有路径前面都自动加上 /interestTag
router = APIRouter(prefix="/interestTag")


class TagPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # 字段都允许为空，哪些必填由 service 判断并给出人话提示
    id: int | None = None
    tag_name: str | None = None
    category: str | None = None
    enabled: str | None = None
    sort: int | None = None


class EnabledPayload(BaseModel):
    tag_id: int
    # 是 / 否
    enabled: str


@router.get("/selectPage")
async def select_page(
    tag_name: str = "",
    category: str = "",
    enabled: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(await interest_tag_service.select_page(
        tag_name, category, enabled, page_num, page_size))


@router.post("/add")
async def add(payload: TagPayload, _: User = Depends(require_admin)):
    # exclude_unset=True 只保留前端真正传了的字段，没填的交给 service 决定默认值
    await interest_tag_service.add(payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/update")
async def update(payload: TagPayload, _: User = Depends(require_admin)):
    await interest_tag_service.update(
        payload.id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.delete("/delete/{tag_id}")
async def delete(tag_id: int, _: User = Depends(require_admin)):
    await interest_tag_service.remove(tag_id)
    return Result.success()


@router.delete("/deleteBatch")
async def delete_batch(ids: List[int], _: User = Depends(require_admin)):
    # 请求体是一个纯数字数组，FastAPI 直接解析成 List[int]
    await interest_tag_service.remove_batch(ids)
    return Result.success()


@router.post("/updateEnabled")
async def update_enabled(payload: EnabledPayload, _: User = Depends(require_admin)):
    await interest_tag_service.update_enabled(payload.tag_id, payload.enabled)
    return Result.success()


@router.get("/categories")
async def categories(_: User = Depends(get_current_user)):
    # 类目清单由后端给出，页面不自己维护一份
    return Result.success(interest_tag_service.list_categories())
