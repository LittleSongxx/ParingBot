"""候选筛选接口。"""

from fastapi import APIRouter, Depends

from common.auth import get_current_user
from common.result import Result
from models import User
from service import screener_service

# 这个 router 带 prefix="/screener"，下面所有路径前面都自动加上 /screener
router = APIRouter(prefix="/screener")


@router.get("/my")
async def my_candidates(current_user: User = Depends(get_current_user)):
    """候选结果：展示智能匹配每一轮筛出来的人与候选列表。"""
    return Result.success(await screener_service.my_page(current_user))


@router.get("/selectCandidate")
async def select_candidate(candidate_id: int, current_user: User = Depends(get_current_user)):
    """候选详情，带自我介绍和室友期望，在弹窗里看。"""
    return Result.success(await screener_service.candidate_detail(current_user, candidate_id))
