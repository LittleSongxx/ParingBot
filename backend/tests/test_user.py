"""用户管理接口测试。

覆盖分页查询的权限、新增的格式与重复校验、编辑时的自我保护，
以及删除账号时的连带清理与业务流水拦截。

测试造出来的账号都带「单元测试专用」后缀，跑完由 conftest 的清扫夹具统一回收。
"""

import os

import pytest

from common.exception_handler import CustomException
from models import (
    MatchTask,
    RoommatePreference,
    MemberMoment,
    MemberPortrait,
    MemberProfile,
    User,
)
from service import user_service

# 测试账号统一带这个后缀，名字里出现它的记录会被清扫夹具删掉
TEST_MARK = "单元测试专用"
PASSWORD = "abc123456"


def _add(client, admin_headers, username, **extra):
    return client.post("/user/add", json={"username": username, **extra}, headers=admin_headers).json()


def _id_of(client, admin_headers, username):
    """按账号在列表里反查它的 id。"""
    page = client.get(
        "/user/selectPage", params={"name": TEST_MARK, "page_size": 100}, headers=admin_headers
    ).json()
    for row in page["data"]["list"]:
        if row["username"] == username:
            return row["id"]
    raise AssertionError(f"列表里没找到账号 {username}")


def _current_user_id(client, headers):
    return client.get("/currentUser", headers=headers).json()["data"]["id"]


def test_member_cannot_read_user_list(client, user_headers):
    """租客拿自己的 token 调用户管理接口会被拦下。"""
    body = client.get("/user/selectPage", headers=user_headers).json()
    assert body["code"] == "403"
    assert body["msg"] == "这个操作只有管理员能做，请换成管理员账号后再试"


def test_add_user_with_default_password_then_login(client, admin_headers):
    """新增账号时密码留空给默认密码，列表里的注册时间是页面能直接展示的格式。"""
    username = f"yhglxinjian{TEST_MARK}"
    assert _add(client, admin_headers, username, name=f"新账号{TEST_MARK}")["code"] == "200"

    login = client.post("/login", json={"username": username, "password": "123456"}).json()
    assert login["code"] == "200"
    # 管理端新建的账号默认是租客，能直接进用户端
    assert login["data"]["role"] == "USER"

    row = client.get(
        "/user/selectPage", params={"name": TEST_MARK, "page_size": 100}, headers=admin_headers
    ).json()["data"]["list"][0]
    assert row["username"] == username
    assert row["status"] == "NORMAL"
    assert row["email"] is None
    # 注册时间已经格式化成「年-月-日 时:分:秒」，长度固定 19 位
    assert len(row["create_time"]) == 19


def test_add_user_with_duplicate_username_is_rejected(client, admin_headers):
    """账号唯一，重复添加会被拦下并提示换一个。"""
    username = f"yhglchongfu{TEST_MARK}"
    assert _add(client, admin_headers, username)["code"] == "200"

    body = _add(client, admin_headers, username)
    assert body["code"] == "500"
    assert body["msg"] == "账号已存在，请换一个账号"


def test_add_user_with_too_short_username_is_rejected(client, admin_headers):
    """账号长度不够时给明确提示，提示里写清要几位。"""
    body = _add(client, admin_headers, "ab")
    assert body["code"] == "500"
    assert body["msg"] == "账号长度需要在 3 到 30 个字符之间"


def test_add_user_with_too_short_password_is_rejected(client, admin_headers):
    """密码框里填了内容就要过格式校验，不能因为留空有默认值就放行短密码。"""
    body = _add(client, admin_headers, f"yhglduanmi{TEST_MARK}", password="123")
    assert body["code"] == "500"
    assert body["msg"] == "密码长度需要在 6 到 30 个字符之间"


def test_add_user_with_unknown_role_is_rejected(client, admin_headers):
    """角色只有管理员和租客两档，绕过页面传别的值会被拦下。"""
    body = _add(client, admin_headers, f"yhgljiaose{TEST_MARK}", role="GUEST")
    assert body["code"] == "500"
    assert body["msg"] == "角色参数错误"


def test_disabled_user_cannot_login(client, admin_headers):
    """编辑弹窗里把状态改成停用之后，这个账号就登不上了。"""
    username = f"yhgltingyong{TEST_MARK}"
    assert _add(client, admin_headers, username)["code"] == "200"
    user_id = _id_of(client, admin_headers, username)

    assert client.put(
        "/user/update", json={"id": user_id, "status": "DISABLED"}, headers=admin_headers
    ).json()["code"] == "200"

    login = client.post("/login", json={"username": username, "password": "123456"}).json()
    assert login["code"] == "500"
    # 登录失败提示已统一成「账号或密码错误」，不暴露账号是否被停用
    assert login["msg"] == "账号或密码错误"


def test_admin_cannot_disable_self(client, admin_headers):
    """停用自己会立刻丢掉管理端入口，拦在写库之前。"""
    admin_id = _current_user_id(client, admin_headers)
    body = client.put(
        "/user/update", json={"id": admin_id, "status": "DISABLED"}, headers=admin_headers
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "不能停用当前登录账号"


def test_admin_cannot_demote_self(client, admin_headers):
    """把自己改成租客同样会丢掉管理端入口。"""
    admin_id = _current_user_id(client, admin_headers)
    body = client.put("/user/update", json={"id": admin_id, "role": "USER"}, headers=admin_headers).json()
    assert body["code"] == "500"
    assert body["msg"] == "不能把自己的角色改成租客"


def test_member_cannot_update_other_user(client, user_headers):
    """租客只能改自己那条，改别人的账号信息会被拦下。"""
    body = client.put(
        "/user/update", json={"id": 1, "name": "被改掉的名字"}, headers=user_headers
    ).json()
    assert body["code"] == "403"
    assert body["msg"] == "只能修改自己的账号信息，要改别人的账号请用管理员账号操作"


def test_admin_cannot_delete_self(client, admin_headers):
    """删掉自己会让当前会话立刻失效，直接拦住。"""
    admin_id = _current_user_id(client, admin_headers)
    body = client.delete(f"/user/delete/{admin_id}", headers=admin_headers).json()
    assert body["code"] == "500"
    assert body["msg"] == "不能删除当前登录账号"


def test_delete_batch_containing_self_is_rejected_as_a_whole(client, admin_headers):
    """勾选里混进自己就整批拦下，不做「跳过自己删其他人」。"""
    username = f"yhglpiliang{TEST_MARK}"
    assert _add(client, admin_headers, username)["code"] == "200"
    other_id = _id_of(client, admin_headers, username)
    admin_id = _current_user_id(client, admin_headers)

    body = client.request(
        "DELETE", "/user/deleteBatch", json=[admin_id, other_id], headers=admin_headers
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "不能删除当前登录账号"
    # 整批都被拦下，另一个账号还在列表里
    assert _id_of(client, admin_headers, username) == other_id


async def _make_member(username: str, nickname: str):
    """造一个带租客档案的账号，资料下面挂齐各类从属数据。"""
    user = await User.create(username=username, password=PASSWORD, name=nickname, role="USER")
    profile = await MemberProfile.create(user_id=user.id, nickname=nickname, gender="男")
    await RoommatePreference.create(member_id=profile.id)
    await MemberMoment.create(member_id=profile.id, content="周末去爬山")
    await MemberPortrait.create(member_id=profile.id, summary="喜欢运动的租客")
    return user, profile


async def test_delete_user_cleans_member_data(db):
    """删账号时连带清掉他名下的租客档案，以及挂在资料上的偏好、动态与画像。"""
    user, profile = await _make_member(f"lianji{TEST_MARK}", f"连一{TEST_MARK}")
    admin = await User.get(username="admin")

    await user_service.delete(admin, user.id)

    assert await User.get_or_none(id=user.id) is None
    assert await MemberProfile.get_or_none(id=profile.id) is None
    assert await RoommatePreference.filter(member_id=profile.id).count() == 0
    assert await MemberMoment.filter(member_id=profile.id).count() == 0
    assert await MemberPortrait.filter(member_id=profile.id).count() == 0


def _write_file(name: str) -> str:
    """在 files 目录里放一个测试用的小文件，返回文件名。"""
    file_name = f"{name}_{TEST_MARK}"
    with open(os.path.join("files", file_name), "wb") as handle:
        handle.write(b"unit test")
    return file_name


async def test_delete_user_cleans_uploaded_files(db):
    """生活照和动态配图都是上传下来的磁盘文件，跟着账号一起清掉。"""
    user = await User.create(username=f"wenjian{TEST_MARK}", password=PASSWORD,
                             name=f"文件{TEST_MARK}", role="USER")
    photo = _write_file("photo.png")
    moment_image = _write_file("moment.png")
    profile = await MemberProfile.create(
        user_id=user.id, nickname=f"文件{TEST_MARK}", gender="女",
        photo_paths="http://127.0.0.1:9090/files/download/" + photo)
    await MemberMoment.create(member_id=profile.id, content="周末去爬山",
                              image_paths="http://127.0.0.1:9090/files/download/" + moment_image)
    admin = await User.get(username="admin")

    await user_service.delete(admin, user.id)

    for file_name in (photo, moment_image):
        assert not os.path.exists(os.path.join("files", file_name))


async def test_delete_user_with_match_task_is_blocked(db):
    """已经发起过匹配的租客属于业务流水，账号删不掉，提示改为停用。"""
    user, profile = await _make_member(f"liushui{TEST_MARK}", f"流水一{TEST_MARK}")
    await MatchTask.create(member_id=profile.id, task_no=f"T{TEST_MARK}", status="已完成")
    admin = await User.get(username="admin")

    with pytest.raises(CustomException) as error:
        await user_service.delete(admin, user.id)

    assert "账号不能删除，请改为停用" in error.value.message
    # 拦下来之后账号和资料都还在
    assert await User.get_or_none(id=user.id) is not None
    assert await MemberProfile.get_or_none(id=profile.id) is not None


async def test_delete_batch_checks_the_whole_selection_first(db):
    """批量删除里只要有一个删不掉，整批都不动。"""
    keeper, _ = await _make_member(f"keyi{TEST_MARK}", f"可删{TEST_MARK}")
    blocked, blocked_profile = await _make_member(f"buneng{TEST_MARK}", f"不可删{TEST_MARK}")
    await MatchTask.create(member_id=blocked_profile.id, task_no=f"B{TEST_MARK}", status="已完成")
    admin = await User.get(username="admin")

    with pytest.raises(CustomException):
        await user_service.delete_batch(admin, [keeper.id, blocked.id])

    assert await User.get_or_none(id=keeper.id) is not None
    assert await User.get_or_none(id=blocked.id) is not None
