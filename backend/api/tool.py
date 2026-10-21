"""工具中心接口。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from common.auth import require_admin
from common.result import Result
from models import User
from service import tool_service

# 这个 router 带 prefix="/functionTool"，下面所有路径前面都自动加上 /functionTool
router = APIRouter(prefix="/functionTool")


class ToolPayload(BaseModel):
    id: int | None = None
    tool_code: str | None = None
    tool_name: str | None = None
    description: str | None = None
    input_schema: str | None = None
    tool_group: str | None = None
    max_return_rows: int | None = None
    enabled: str | None = None
    sort: int | None = None


class EnabledPayload(BaseModel):
    tool_id: int
    # 是 / 否
    enabled: str


class TestPayload(BaseModel):
    tool_code: str
    # 试跑时的租客上下文，读租客档案这类工具要用
    member_id: int | None = None
    # 工具入参，键名必须是参数 Schema 里声明过的
    params: dict = {}


@router.get("/selectPage")
async def select_page(
    keyword: str = "",
    tool_group: str = "",
    enabled: str = "",
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    return Result.success(await tool_service.select_page(
        keyword, tool_group, enabled, page_num, page_size))


@router.get("/summary")
async def summary(_: User = Depends(require_admin)):
    """工具总览与健康检查。"""
    return Result.success(await tool_service.summary())


@router.get("/groupOptions")
async def group_options(_: User = Depends(require_admin)):
    return Result.success(await tool_service.group_options())


@router.get("/codeOptions")
async def code_options(_: User = Depends(require_admin)):
    """新增工具时能选的编码，来自代码里已实现、清单里还没登记的那些。"""
    return Result.success(await tool_service.code_options())


@router.get("/memberOptions")
async def member_options(keyword: str = "", _: User = Depends(require_admin)):
    """试跑时选租客用的下拉。"""
    return Result.success(await tool_service.member_options(keyword))


@router.post("/add")
async def add(payload: ToolPayload, _: User = Depends(require_admin)):
    await tool_service.add(payload.model_dump(exclude_unset=True))
    return Result.success()


@router.put("/update")
async def update(payload: ToolPayload, _: User = Depends(require_admin)):
    await tool_service.update(payload.id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.post("/updateEnabled")
async def update_enabled(payload: EnabledPayload, _: User = Depends(require_admin)):
    """启用或停用工具。停用之后模型手上的工具清单里就没有它了。"""
    await tool_service.update_enabled(payload.tool_id, payload.enabled)
    return Result.success()


@router.delete("/delete/{tool_id}")
async def delete(tool_id: int, _: User = Depends(require_admin)):
    await tool_service.remove(tool_id)
    return Result.success()


@router.post("/testCall")
async def test_call(payload: TestPayload, _: User = Depends(require_admin)):
    """在页面上试跑一个读取类工具，看它的入参和返回。"""
    return Result.success(await tool_service.test_call(
        payload.tool_code, payload.member_id, payload.params))
