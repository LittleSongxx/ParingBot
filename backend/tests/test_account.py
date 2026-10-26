"""登录、注册、修改密码、当前登录账号的接口测试。

覆盖注册的格式校验与账号查重、登录的成败分支、修改密码的原密码校验，
以及未登录访问受保护接口时的返回码。

测试造出来的账号都带「单元测试专用」后缀，跑完由 conftest 的清扫夹具统一回收。
"""

import pytest

from common.exception_handler import CustomException
from service import account_service

# 测试账号统一带这个后缀，名字里出现它的记录会被清扫夹具删掉
TEST_MARK = "单元测试专用"
PASSWORD = "abc123456"
NEW_PASSWORD = "abc654321"

REGISTER_USERNAME = f"zhuce{TEST_MARK}"
DUPLICATE_USERNAME = f"chongfu{TEST_MARK}"
DISABLED_USERNAME = f"tingyong{TEST_MARK}"
UPDATE_USERNAME = f"gaimi{TEST_MARK}"
UNKNOWN_USERNAME = f"meiyou{TEST_MARK}"


def _register(client, username=REGISTER_USERNAME, password=PASSWORD, confirm_password=None):
    return client.post(
        "/register",
        json={
            "username": username,
            "password": password,
            "confirmPassword": password if confirm_password is None else confirm_password,
        },
    ).json()


def _login(client, username, password=PASSWORD):
    return client.post("/login", json={"username": username, "password": password}).json()


def test_register_then_login_returns_user_role(client):
    """自助注册出来的账号是租客角色，注册完就能直接登录。"""
    assert _register(client)["code"] == "200"

    body = _login(client, REGISTER_USERNAME)
    assert body["code"] == "200"
    assert body["data"]["role"] == "USER"
    assert body["data"]["status"] == "NORMAL"
    # 姓名没填时默认用账号顶上，个人中心里不会是空的一栏
    assert body["data"]["name"] == REGISTER_USERNAME
    assert body["data"]["token"]
    # 登录返回的是脱敏后的账号信息，密码不出现在响应里
    assert "password" not in body["data"]


def test_register_with_existing_username_is_rejected(client):
    """账号唯一，重复注册会被拦下并提示换一个。"""
    assert _register(client, DUPLICATE_USERNAME)["code"] == "200"

    body = _register(client, DUPLICATE_USERNAME)
    assert body["code"] == "500"
    assert body["msg"] == "账号已存在，请换一个账号"


def test_register_with_mismatched_confirm_password_is_rejected(client):
    """两次输入的密码不一致时拦在写库之前。"""
    body = _register(client, f"bumatch{TEST_MARK}", confirm_password="abc654321")
    assert body["code"] == "500"
    assert body["msg"] == "两次输入的密码不一致"


def test_register_with_too_short_password_is_rejected(client):
    """密码长度不够时，提示里写清要求几位。"""
    body = _register(client, f"duanmi{TEST_MARK}", password="123")
    assert body["code"] == "500"
    assert "密码长度需要在 6 到 30 个字符之间" == body["msg"]


def test_register_with_too_short_username_is_rejected(client):
    """账号太短时同样给明确提示。"""
    body = _register(client, "ab")
    assert body["code"] == "500"
    assert body["msg"] == "账号长度需要在 3 到 30 个字符之间"


def test_register_with_blank_username_is_rejected(client):
    """账号只填空格等于没填，拦在写库之前。"""
    body = _register(client, "   ")
    assert body["code"] == "500"
    assert body["msg"] == "请输入账号"


def test_login_with_unknown_username_uses_the_same_message(client):
    """账号不存在和密码错误给同一句提示，不透露账号是否注册过。"""
    unknown = _login(client, UNKNOWN_USERNAME)
    wrong_password = _login(client, "admin", password="wrong-password")
    assert unknown["code"] == "500"
    assert unknown["msg"] == wrong_password["msg"] == "账号或密码错误"


def test_login_ignores_spaces_around_username(client):
    """账号前后多打了空格也能登录成功，不用用户自己找原因。"""
    assert _register(client, f"kongge{TEST_MARK}")["code"] == "200"

    body = _login(client, f"  kongge{TEST_MARK}  ")
    assert body["code"] == "200"
    assert body["data"]["username"] == f"kongge{TEST_MARK}"


async def test_disabled_account_cannot_login(db):
    """被停用的账号密码对也不让登录，直接调 service 校验这条业务规则。"""
    from models import User

    await User.create(
        username=DISABLED_USERNAME,
        password=PASSWORD,
        name=DISABLED_USERNAME,
        role="USER",
        status="DISABLED",
    )

    with pytest.raises(CustomException) as error:
        await account_service.login(DISABLED_USERNAME, PASSWORD)
    assert error.value.message == "账号已被停用"


def test_update_password_requires_correct_old_password(client):
    """原密码不对时不能改密，防止别人趁页面没锁屏直接改。"""
    assert _register(client, UPDATE_USERNAME)["code"] == "200"
    headers = {"token": _login(client, UPDATE_USERNAME)["data"]["token"]}

    body = client.put(
        "/updatePassword",
        json={"password": "wrong-password", "newPassword": NEW_PASSWORD},
        headers=headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "原密码错误"


def test_update_password_then_login_with_new_password(client):
    """改完密码之后旧密码失效、新密码可用。"""
    assert _register(client, f"huanyong{TEST_MARK}")["code"] == "200"
    headers = {"token": _login(client, f"huanyong{TEST_MARK}")["data"]["token"]}

    body = client.put(
        "/updatePassword",
        json={"password": PASSWORD, "newPassword": NEW_PASSWORD},
        headers=headers,
    ).json()
    assert body["code"] == "200"

    assert _login(client, f"huanyong{TEST_MARK}", password=PASSWORD)["code"] == "500"
    assert _login(client, f"huanyong{TEST_MARK}", password=NEW_PASSWORD)["code"] == "200"


def test_update_password_too_short_is_rejected(client):
    """改密码这一步不能绕开注册时的密码长度要求。"""
    assert _register(client, f"gaiduani{TEST_MARK}")["code"] == "200"
    headers = {"token": _login(client, f"gaiduani{TEST_MARK}")["data"]["token"]}

    body = client.put(
        "/updatePassword",
        json={"password": PASSWORD, "newPassword": "123"},
        headers=headers,
    ).json()
    assert body["code"] == "500"
    assert body["msg"] == "密码长度需要在 6 到 30 个字符之间"


def test_current_user_returns_login_account_without_password(client, user_headers):
    """当前登录账号接口返回自己的信息，且不含密码字段。"""
    body = client.get("/currentUser", headers=user_headers).json()
    assert body["code"] == "200"
    assert body["data"]["username"] == "member01"
    assert body["data"]["role"] == "USER"
    assert "password" not in body["data"]


def test_current_user_without_token_returns_401_code(client):
    """未登录访问当前登录账号接口，返回 401 业务码。"""
    body = client.get("/currentUser").json()
    assert body["code"] == "401"
