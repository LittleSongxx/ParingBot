"""测试公共夹具。

登录一次拿到管理员 token，后面各轮的功能测试都靠它调受保护接口。

运行前提：MySQL 已启动，且已执行过 ai_coliving.sql。
运行方式（在 fastapi-app 目录下）：pytest
"""

import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient
from tortoise import Tortoise

from main import app
from settings import TORTOISE_ORM

# 测试数据的统一后缀。会落库的测试数据都带上它，跑完自动回收
TEST_MARK = "单元测试专用"


@pytest.fixture()
async def db():
    """给直接调 service 或 ai 层函数的异步测试用的数据库连接。

    走接口的测试由 TestClient 负责连库，这一条只给没走接口的用例用。
    """
    await Tortoise.init(config=TORTOISE_ORM)
    yield
    await Tortoise.close_connections()


@pytest.fixture()
def client():
    """带生命周期的测试客户端，进入时连数据库，退出时释放连接。"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def admin_headers(client):
    """用初始化数据里的管理员账号登录，返回带 token 的请求头。"""
    response = client.post("/login", json={"username": "admin", "password": "admin"})
    body = response.json()
    assert body["code"] == "200", "管理员登录失败，请确认已执行 ai_coliving.sql 且密码未被改过"
    return {"token": body["data"]["token"]}


@pytest.fixture()
def user_headers(client):
    """用初始化数据里的租客账号登录，返回带 token 的请求头。"""
    response = client.post("/login", json={"username": "member01", "password": "123456"})
    body = response.json()
    assert body["code"] == "200", "租客登录失败，请确认已执行 ai_coliving.sql 且密码未被改过"
    return {"token": body["data"]["token"]}


async def _sweep() -> dict:
    """按名字后缀回收测试数据，返回各表删了多少条。

    删除顺序是从属表在前、主表在后，反过来的话主表没了，
    从属表就成了查不到出处的孤儿数据。
    """
    await Tortoise.init(config=TORTOISE_ORM)
    from models import (
        AgentRun,
        AgentStep,
        AiModelConfig,
        AgentDefinition,
        FunctionTool,
        InterestTag,
        MatchCandidate,
        MatchTask,
        RoommatePreference,
        MemberMoment,
        MemberPortrait,
        MemberProfile,
        PromptTemplate,
        SysConfig,
        ToolCallLog,
        User,
    )

    removed: dict[str, int] = {}

    async def drop(model, **filters):
        count = await model.filter(**filters).count()
        if count:
            await model.filter(**filters).delete()
            removed[model.__name__] = removed.get(model.__name__, 0) + count

    # 租客的从属数据挂在租客档案上，先按测试账号找出这些资料，再顺着资料往下清
    test_user_ids = [user.id for user in await User.filter(username__contains=TEST_MARK)]
    member_ids: list[int] = []
    if test_user_ids:
        member_ids = [profile.id for profile in await MemberProfile.filter(user_id__in=test_user_ids)]
    if member_ids:
        await drop(MemberPortrait, member_id__in=member_ids)
        await drop(RoommatePreference, member_id__in=member_ids)
        await drop(MemberMoment, member_id__in=member_ids)
        await drop(MemberProfile, id__in=member_ids)
    # 昵称里带标记的租客档案，也从这一侧兜一遍：有的用例只造资料不造账号
    orphan_ids = [
        profile.id for profile in await MemberProfile.filter(nickname__contains=TEST_MARK)]
    if orphan_ids:
        await drop(MemberPortrait, member_id__in=orphan_ids)
        await drop(RoommatePreference, member_id__in=orphan_ids)
        await drop(MemberMoment, member_id__in=orphan_ids)
        await drop(MemberProfile, id__in=orphan_ids)

    # 候选池挂在匹配任务上，先顺测试任务找出候选；测试租客自己发起的任务
    # 任务编号里没有标记，从租客这一侧再兜一遍，两种都在任务之前清掉
    test_task_ids = {task.id for task in await MatchTask.filter(task_no__contains=TEST_MARK)}
    if member_ids:
        test_task_ids |= {task.id for task in await MatchTask.filter(member_id__in=member_ids)}
    if orphan_ids:
        test_task_ids |= {task.id for task in await MatchTask.filter(member_id__in=orphan_ids)}
    if test_task_ids:
        await drop(MatchCandidate, task_id__in=list(test_task_ids))
        await drop(MatchTask, id__in=list(test_task_ids))
    # 词表是独立的小表，租客档案的兴趣标签只是引用它的词，没有外键
    await drop(InterestTag, tag_name__contains=TEST_MARK)
    await drop(User, username__contains=TEST_MARK)
    # 系统参数没有从属表，测试造出来的参数直接清
    await drop(SysConfig, config_key__contains=TEST_MARK)
    # AI 模型配置和 Prompt 模板也是独立的小表，测试造出来的直接清
    await drop(AiModelConfig, name__contains=TEST_MARK)
    await drop(PromptTemplate, name__contains=TEST_MARK)
    # 测试跑出来的运行记录：先顺运行编号和测试任务找出步骤与工具日志，再删运行本身，
    # 反过来的话运行没了，步骤和日志就成了查不到出处的孤儿数据。
    # 运行编号由业务代码生成的那一类不带测试标记，从它挂在哪个任务上兜一遍
    test_run_ids = {run.id for run in await AgentRun.filter(run_no__contains=TEST_MARK)}
    if test_task_ids:
        test_run_ids |= {run.id for run in await AgentRun.filter(
            task_id__in=list(test_task_ids))}
    if test_run_ids:
        await drop(AgentStep, run_id__in=list(test_run_ids))
        await drop(ToolCallLog, run_id__in=list(test_run_ids))
    await drop(AgentRun, id__in=list(test_run_ids))
    # 工具调用日志挂在某次运行上，先按工具编码清，再清测试造出来的角色和工具
    await drop(ToolCallLog, tool_code__contains=TEST_MARK)
    await drop(FunctionTool, tool_code__contains=TEST_MARK)
    await drop(AgentDefinition, agent_code__contains=TEST_MARK)
    # 测试上传的文件要跟着一起清，否则每跑一轮 files 目录就多留一份
    if os.path.isdir("files"):
        for name in os.listdir("files"):
            if TEST_MARK in name:
                try:
                    os.remove(os.path.join("files", name))
                except OSError:
                    pass

    await Tortoise.close_connections()
    return removed


@pytest.fixture(scope="session", autouse=True)
def sweep_test_data():
    """整批测试跑完后把测试数据从开发库里清掉。

    autouse 表示不用任何测试显式引用它，整个 session 自动生效；
    yield 之前什么都不做，之后才清扫，所以不影响测试本身的执行。
    新增业务表之后，在这里按从属表在前、主表在后的顺序补上清扫。
    """
    yield
    # Windows 默认的 ProactorEventLoop 在关闭时会让 aiomysql 报 Event loop is closed，
    # 换成 SelectorEventLoop 再跑清扫
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    removed = asyncio.run(_sweep())
    if removed:
        detail = "、".join(f"{name} {count} 条" for name, count in removed.items())
        print(f"\n[测试数据清扫] {detail}")
