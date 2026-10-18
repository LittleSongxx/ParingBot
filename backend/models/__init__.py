"""Tortoise 模型包。

脚手架把所有模型放在单个 models.py 里，本项目表数量多，按业务域拆成七个文件：

    user.py        用户
    member.py      租客档案
    preference.py  合住偏好
    content.py     兴趣标签、租客动态
    config.py      模型配置、Prompt 模板、系统参数、Agent 与工具注册
    process.py     Agent 运行、步骤、工具调用日志
    result.py      匹配任务、候选池、画像

引入新表时按域放进对应文件，并在本文件里导入，Tortoise 才能扫描到。
"""

from models.config import (
    AgentDefinition,
    AiModelConfig,
    FunctionTool,
    PromptTemplate,
    SysConfig,
)
from models.content import InterestTag, MemberMoment
from models.member import MemberProfile
from models.preference import RoommatePreference
from models.process import AgentRun, AgentStep, ToolCallLog
from models.result import MatchCandidate, MatchTask, MemberPortrait
from models.user import User

__all__ = [
    "User",
    "MemberProfile",
    "RoommatePreference",
    "InterestTag",
    "MemberMoment",
    "AiModelConfig",
    "PromptTemplate",
    "SysConfig",
    "AgentDefinition",
    "FunctionTool",
    "AgentRun",
    "AgentStep",
    "ToolCallLog",
    "MatchTask",
    "MatchCandidate",
    "MemberPortrait",
]
