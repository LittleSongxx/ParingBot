"""Prompt 模板接口。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from common.auth import require_admin
from common.result import Result
from models import User
from service import prompt_service

# 这个 router 带 prefix="/promptTemplate"，下面所有路径前面都自动加上 /promptTemplate
router = APIRouter(prefix="/promptTemplate")


class PromptPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # 变量清单不在这里：它由内容自动识别，不接受前端传
    id: int | None = None
    code: str | None = None
    name: str | None = None
    scene: str | None = None
    content: str | None = None
    enabled: str | None = None
    remark: str | None = None


class EnabledPayload(BaseModel):
    template_id: int
    # 是 / 否
    enabled: str


class PreviewPayload(BaseModel):
    # 模板 id 加一组变量值，用来预览真正发给模型的文本
    id: int
    values: dict = {}


@router.get("/selectPage")
async def select_page(
    keyword: str = "",
    scene: str = "",
    enabled: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(await prompt_service.select_page(
        keyword, scene, enabled, page_num, page_size))


@router.get("/sceneOptions")
async def scene_options(_: User = Depends(require_admin)):
    # 场景的可选项由后端给出，页面不自己维护一份
    return Result.success(prompt_service.scene_options())


@router.post("/add")
async def add(payload: PromptPayload, _: User = Depends(require_admin)):
    await prompt_service.add(payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/update")
async def update(payload: PromptPayload, _: User = Depends(require_admin)):
    await prompt_service.update(payload.id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.post("/updateEnabled")
async def update_enabled(payload: EnabledPayload, _: User = Depends(require_admin)):
    await prompt_service.update_enabled(payload.template_id, payload.enabled)
    return Result.success()


@router.delete("/delete/{template_id}")
async def delete(template_id: int, _: User = Depends(require_admin)):
    await prompt_service.remove(template_id)
    return Result.success()


@router.post("/preview")
async def preview(payload: PreviewPayload, _: User = Depends(require_admin)):
    """把变量值填进模板，返回真正会发给模型的完整文本。"""
    return Result.success(await prompt_service.preview(payload.id, payload.values))
