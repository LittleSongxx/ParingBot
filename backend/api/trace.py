"""Agent 调度时间线与候选漏斗接口。"""

from fastapi import APIRouter, Depends

from common.auth import require_admin
from common.result import Result
from models import User
from service import trace_service

# 这个 router 带 prefix="/trace"，下面所有路径前面都自动加上 /trace
router = APIRouter(prefix="/trace")


@router.get("/selectPage")
async def select_page(
    run_no: str = "",
    run_type: str = "",
    run_status: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    """运行记录分页查询：一次运行一行，点进去看它的漏斗和时间线。"""
    return Result.success(await trace_service.run_page(
        run_no, run_type, run_status, page_num, page_size))


@router.get("/options")
async def options(_: User = Depends(require_admin)):
    """筛选用的下拉：运行类型、运行状态。"""
    return Result.success(await trace_service.run_options())


@router.get("/detail")
async def detail(run_id: int, _: User = Depends(require_admin)):
    """一次运行的完整过程：运行总览、候选漏斗、调度时间线。"""
    return Result.success(await trace_service.run_detail(run_id))
