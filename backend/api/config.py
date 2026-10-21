"""系统参数接口。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from common.auth import require_admin
from common.result import Result
from models import User
from service import config_service

# 这个 router 带 prefix="/sysConfig"，下面所有路径前面都自动加上 /sysConfig
router = APIRouter(prefix="/sysConfig")


class ConfigPayload(BaseModel):
    # 只有这两个字段能改：参数编码、名称、值类型由代码和初始化数据固定
    id: int
    config_value: str | None = None
    enabled: str | None = None


class EnabledPayload(BaseModel):
    config_id: int
    # 是 / 否
    enabled: str


@router.get("/selectPage")
async def select_page(
    keyword: str = "",
    enabled: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(await config_service.select_page(
        keyword, enabled, page_num, page_size))


@router.put("/update")
async def update(payload: ConfigPayload, _: User = Depends(require_admin)):
    await config_service.update(payload.id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.post("/updateEnabled")
async def update_enabled(payload: EnabledPayload, _: User = Depends(require_admin)):
    await config_service.update_enabled(payload.config_id, payload.enabled)
    return Result.success()
