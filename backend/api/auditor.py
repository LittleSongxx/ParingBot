"""候选审核接口。"""

from fastapi import APIRouter, Depends

from common.auth import get_current_user
from common.result import Result
from models import User
from service import auditor_service

# 这个 router 带 prefix="/auditor"，下面所有路径前面都自动加上 /auditor
router = APIRouter(prefix="/auditor")


@router.get("/my")
async def my_audit(current_user: User = Depends(get_current_user)):
    """审核结果：展示智能匹配产生的否决分布、名单与审核结论。"""
    return Result.success(await auditor_service.my_page(current_user))


@router.get("/selectCandidate")
async def select_candidate(candidate_id: int, current_user: User = Depends(get_current_user)):
    """一位候选的审核详情，带他在意的条件和代码复核，在弹窗里看。"""
    return Result.success(await auditor_service.candidate_detail(current_user, candidate_id))


@router.post("/candidatePortrait")
async def candidate_portrait(candidate_id: int, current_user: User = Depends(get_current_user)):
    """按需生成候选画像（只允许自己候选池里的候选）。"""
    return Result.success(await auditor_service.generate_candidate_portrait(current_user, candidate_id))


@router.post("/warmCandidatePortraits")
async def warm_candidate_portraits(limit: int = 8, current_user: User = Depends(get_current_user)):
    """给当前候选池批量补画像，每批最多 8 人（上限 20）。"""
    return Result.success(await auditor_service.warm_candidate_portraits(current_user, limit))
