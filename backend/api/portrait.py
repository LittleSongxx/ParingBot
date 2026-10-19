"""租客画像接口。"""

from fastapi import APIRouter, Depends

from common.auth import get_current_user
from common.result import Result
from models import User
from service import portrait_service

# 这个 router 带 prefix="/portrait"，下面所有路径前面都自动加上 /portrait
router = APIRouter(prefix="/portrait")


@router.get("/my")
async def my_portrait(current_user: User = Depends(get_current_user)):
    """画像结果：展示智能匹配生成的最新画像与标签依据。"""
    return Result.success(await portrait_service.my_page(current_user))


@router.get("/selectOne")
async def select_one(portrait_id: int, current_user: User = Depends(get_current_user)):
    """某一个版本画像的详情，带每个标签依据的那段原文。"""
    return Result.success(await portrait_service.detail(current_user, portrait_id))
