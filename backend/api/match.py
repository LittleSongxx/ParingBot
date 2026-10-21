"""智能匹配接口。"""

from fastapi import APIRouter, BackgroundTasks, Depends

from common.auth import get_current_user
from common.result import Result
from models import User
from service import match_service

# 这个 router 带 prefix="/match"，下面所有路径前面都自动加上 /match
router = APIRouter(prefix="/match")


@router.get("/my")
async def my_match(current_user: User = Depends(get_current_user)):
    """我的智能匹配：条件核对、最近一次运行、调度过程、候选统计。"""
    return Result.success(await match_service.my_page(current_user))


@router.post("/rerun")
async def rerun(background_tasks: BackgroundTasks,
                current_user: User = Depends(get_current_user)):
    """按当前最新档案重新智能匹配：每次新建任务，页面展示最新一轮。"""
    data = await match_service.rerun(current_user)
    if not data["already_running"]:
        background_tasks.add_task(
            match_service.execute_task, data["task_id"], data["run_id"])
    return Result.success(data)
