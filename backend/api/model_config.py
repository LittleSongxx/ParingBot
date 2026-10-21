"""AI 模型配置接口。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from common.auth import require_admin
from common.result import Result
from models import User
from service import model_config_service

# 这个 router 带 prefix="/aiModelConfig"，下面所有路径前面都自动加上 /aiModelConfig
router = APIRouter(prefix="/aiModelConfig")


class ModelConfigPayload(BaseModel):
    # Pydantic 默认把 model_ 开头的字段名当成保留前缀，model_purpose 和 model_name
    # 是这张表的业务字段，这里关掉这个保护
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    # 字段都允许为空，哪些必填由 service 判断并给出人话提示
    id: int | None = None
    name: str | None = None
    model_purpose: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    enabled: str | None = None
    remark: str | None = None


class EnabledPayload(BaseModel):
    config_id: int
    # 是 / 否
    enabled: str


@router.get("/selectPage")
async def select_page(
    name: str = "",
    model_purpose: str = "",
    enabled: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(await model_config_service.select_page(
        name, model_purpose, enabled, page_num, page_size))


@router.get("/purposeOptions")
async def purpose_options(_: User = Depends(require_admin)):
    # 用途的可选项由后端给出，页面不自己维护一份
    return Result.success(model_config_service.purpose_options())


@router.post("/add")
async def add(payload: ModelConfigPayload, _: User = Depends(require_admin)):
    # exclude_unset=True 只保留前端真正传了的字段，没填的交给 service 决定默认值
    await model_config_service.add(payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/update")
async def update(payload: ModelConfigPayload, _: User = Depends(require_admin)):
    await model_config_service.update(payload.id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.post("/updateEnabled")
async def update_enabled(payload: EnabledPayload, _: User = Depends(require_admin)):
    await model_config_service.update_enabled(payload.config_id, payload.enabled)
    return Result.success()


@router.delete("/delete/{config_id}")
async def delete(config_id: int, _: User = Depends(require_admin)):
    await model_config_service.remove(config_id)
    return Result.success()


@router.post("/test/{config_id}")
async def test(config_id: int, _: User = Depends(require_admin)):
    """连通性测试，用库里保存的配置真实调一次模型。"""
    return Result.success(await model_config_service.test_connection(config_id))
