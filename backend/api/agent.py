"""子 Agent 定义接口。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from common.auth import require_admin
from common.result import Result
from models import User
from service import agent_service

# 这个 router 带 prefix="/agentDefinition"，下面所有路径前面都自动加上 /agentDefinition
router = APIRouter(prefix="/agentDefinition")


class AgentPayload(BaseModel):
    agent_id: int
    agent_name: str | None = None
    prompt_code: str | None = None
    tool_group: str | None = None
    # 留空表示这个角色的工具调用上限跟随系统参数
    max_tool_call: int | None = None
    sort: int | None = None


class EnabledPayload(BaseModel):
    agent_id: int
    # 是 / 否
    enabled: str


@router.get("/list")
async def list_all(_: User = Depends(require_admin)):
    """四个角色的完整配置，附带一份配置问题清单。"""
    return Result.success(await agent_service.list_all())


@router.get("/options")
async def options(_: User = Depends(require_admin)):
    """编辑弹窗要用的两个下拉：工具分组和可用的提示词模板。"""
    return Result.success({
        "groups": await agent_service.group_options(),
        "prompts": await agent_service.prompt_options(),
    })


@router.put("/update")
async def update(payload: AgentPayload, _: User = Depends(require_admin)):
    await agent_service.update(payload.agent_id, payload.model_dump(exclude_unset=True))
    return Result.success()


@router.post("/updateEnabled")
async def update_enabled(payload: EnabledPayload, _: User = Depends(require_admin)):
    """启用或停用角色。停用之后主管派不了它。"""
    await agent_service.update_enabled(payload.agent_id, payload.enabled)
    return Result.success()
