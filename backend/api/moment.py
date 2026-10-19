"""租客动态接口。"""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from common.auth import get_current_user
from common.result import Result
from models import User
from service import moment_service

# 这个 router 带 prefix="/moment"，下面所有路径前面都自动加上 /moment
router = APIRouter(prefix="/moment")


class MomentPayload(BaseModel):
    # 字段都允许为空，哪些必填由 service 判断并给出人话提示
    content: str | None = None
    visible: str | None = None
    # 配图是数组，页面多图上传之后直接传数组过来
    image_paths: List[str] | None = None


@router.get("/selectMyPage")
async def select_my_page(
    page_num: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_current_user),
):
    return Result.success(await moment_service.select_my_page(current_user, page_num, page_size))


@router.post("/publish")
async def publish(payload: MomentPayload, current_user: User = Depends(get_current_user)):
    return Result.success(await moment_service.publish(
        current_user, payload.model_dump(exclude_unset=True)))


@router.put("/update")
async def update(moment_id: int, payload: MomentPayload,
                 current_user: User = Depends(get_current_user)):
    return Result.success(await moment_service.update(
        current_user, moment_id, payload.model_dump(exclude_unset=True)))


@router.delete("/delete/{moment_id}")
async def delete(moment_id: int, current_user: User = Depends(get_current_user)):
    await moment_service.remove(current_user, moment_id)
    return Result.success()


@router.get("/visibleOptions")
async def visible_options(_: User = Depends(get_current_user)):
    # 可见范围的取值由后端给出，页面不自己维护一份
    return Result.success(moment_service.list_visible_options())
