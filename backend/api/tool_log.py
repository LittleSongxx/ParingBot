"""工具调用日志接口。"""

from typing import List

from fastapi import APIRouter, Depends

from common.auth import require_admin
from common.result import Result
from models import User
from service import tool_service

# 这个 router 带 prefix="/toolCallLog"，下面所有路径前面都自动加上 /toolCallLog
router = APIRouter(prefix="/toolCallLog")


@router.get("/selectPage")
async def select_page(
    run_id: int | None = None,
    agent_code: str = "",
    tool_code: str = "",
    success: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(await tool_service.call_log_page(
        run_id, agent_code, tool_code, success, page_num, page_size))


@router.get("/selectOne")
async def select_one(log_id: int, _: User = Depends(require_admin)):
    """一条调用日志的完整入参与返回，页面上放在弹窗里看。"""
    return Result.success(await tool_service.call_log_detail(log_id))


@router.get("/options")
async def options(_: User = Depends(require_admin)):
    """筛选用的下拉：角色、工具、调用结果。"""
    return Result.success(await tool_service.log_options())


@router.delete("/delete/{log_id}")
async def delete(log_id: int, _: User = Depends(require_admin)):
    await tool_service.remove_log(log_id)
    return Result.success()


@router.delete("/deleteBatch")
async def delete_batch(ids: List[int], _: User = Depends(require_admin)):
    return Result.success(await tool_service.remove_logs(ids))
