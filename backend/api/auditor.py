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
