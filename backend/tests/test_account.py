"""登录、注册、修改密码、当前登录账号的接口测试。

覆盖注册的格式校验与账号查重、登录的成败分支、修改密码的原密码校验、未登录访问
受保护接口时的返回码，以及本轮新增的登录限流（账号/IP 双维度）、未知账号常量时间
对齐、JWT 密码指纹吊销（改密后旧 token 立即失效）。

测试造出来的账号都带「单元测试专用」后缀，跑完由 conftest 的清扫夹具统一回收。
conftest 里有一个 autouse 夹具在每个用例前后清空登录失败计数，用例之间不会互相影响。
"""

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from common import rate_limit
from common.exception_handler import CustomException
from service import account_service
from settings import JWT_ALGORITHM, JWT_SECRET

# 测试账号统一带这个后缀，名字里出现它的记录会被清扫夹具删掉
TEST_MARK = "单元测试专用"
PASSWORD = "abc123456"
NEW_PASSWORD = "abc654321"

REGISTER_USERNAME = f"zhuce{TEST_MARK}"
DUPLICATE_USERNAME = f"chongfu{TEST_MARK}"
DISABLED_USERNAME = f"tingyong{TEST_MARK}"
UPDATE_USERNAME = f"gaimi{TEST_MARK}"
UNKNOWN_USERNAME = f"meiyou{TEST_MARK}"

# 登录失败限流的阈值从模块取：环境变量改过时测试不用跟着改数字
MAX_FAILS = rate_limit.MAX_FAILS


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


def _craft_token(user_id, *, pv=None, expires_hours: int = 1) -> str:
    """按服务的密钥手工签一个 token，用来验证旧格式/指纹不对的 token 会被拒。"""
    payload = {
        "sub": str(user_id),
        "role": "USER",
        "exp": datetime.now(timezone.utc) + timedelta(hours=expires_hours),
    }
    if pv is not None:
        payload["pv"] = pv
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


# ---------------------------------------------------------------- 注册


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


# ---------------------------------------------------------------- 登录


def test_login_with_unknown_username_uses_the_same_message(client):
    """账号不存在、密码错误、账号停用给同一句提示，不透露账号是否有/什么状态。"""
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
    """被停用的账号密码对也不让登录，提示和密码错误一致（不暴露账号状态）。"""
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
    assert error.value.message == "账号或密码错误"


# ---------------------------------------------------------------- 登录限流


def test_login_failures_lock_the_account(client):
    """同一账号连续输错 10 次后进入锁定：正确密码也先拒绝（业务码 429），重置后可登录。"""
    username = f"suoding{TEST_MARK}"
    assert _register(client, username)["code"] == "200"

    for _ in range(MAX_FAILS):
        assert _login(client, username, password="wrong-password")["code"] == "500"

    locked = _login(client, username)
    assert locked["code"] == "429"
    assert "锁定" in locked["msg"]

    # 锁定在进程内存里，测试里手动重置即模拟「等锁定窗口过去」
    rate_limit.reset()
    assert _login(client, username)["code"] == "200"


def test_login_failures_lock_the_client_ip(client):
    """同一来源 IP 连续失败达到上限后，换一个账号、密码正确也会被 IP 维度挡住。"""
    victim = f"ipzheng{TEST_MARK}"
    assert _register(client, victim)["code"] == "200"

    # 每次换一个不存在的账号：账号维度各自只有 1 次，IP 维度累计到上限
    for index in range(MAX_FAILS):
        assert _login(client, f"ip{index}{TEST_MARK}")["code"] == "500"

    locked = _login(client, victim)
    assert locked["code"] == "429"
    assert "锁定" in locked["msg"]

    rate_limit.reset()
    assert _login(client, victim)["code"] == "200"


def test_unknown_account_is_checked_against_a_dummy_hash(client, monkeypatch):
    """账号不存在时也要跑一次 PBKDF2 校验，两条分支的耗时才对得齐。"""
    checked = []
    real_verify = account_service.verify_password

    def spy(raw, stored):
        checked.append(stored)
        return real_verify(raw, stored)

    monkeypatch.setattr(account_service, "verify_password", spy)

    body = _login(client, f"bucunzai{TEST_MARK}")
    assert body["code"] == "500"
    assert body["msg"] == "账号或密码错误"
    assert checked and str(checked[0]).startswith("pbkdf2_sha256$")


def test_unknown_account_login_time_is_comparable(client):
    """未知账号与已存在账号的登录耗时在同一量级（原来未知账号会快 12 倍，可被用来枚举）。"""
    existing = f"shixu{TEST_MARK}"
    assert _register(client, existing)["code"] == "200"

    def average(username, rounds=4):
        started = time.perf_counter()
        for _ in range(rounds):
            _login(client, username, password="wrong-password")
        return (time.perf_counter() - started) / rounds

    existing_avg = average(existing)
    unknown_avg = average(f"bucunzai{TEST_MARK}")
    # 未知账号也必须真的算了哈希；比值放宽到 0.1（修复前约 0.08）
    assert unknown_avg > existing_avg * 0.1
    assert unknown_avg < existing_avg * 10


# ---------------------------------------------------------------- 改密码


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


# ---------------------------------------------------------------- JWT 吊销


def test_old_token_is_revoked_after_password_change(client):
    """改密前签发的 token 在改密后立即 401：token 里带着密码指纹，存储值一变就对不上。"""
    username = f"diaoxiao{TEST_MARK}"
    assert _register(client, username)["code"] == "200"
    login = _login(client, username)
    old_token = login["data"]["token"]
    old_headers = {"token": old_token}
    assert client.get("/currentUser", headers=old_headers).json()["code"] == "200"

    changed = client.put(
        "/updatePassword",
        json={"password": PASSWORD, "newPassword": NEW_PASSWORD},
        headers=old_headers,
    ).json()
    assert changed["code"] == "200"

    assert client.get("/currentUser", headers=old_headers).json()["code"] == "401"

    new_login = _login(client, username, password=NEW_PASSWORD)
    assert new_login["code"] == "200"
    new_headers = {"token": new_login["data"]["token"]}
    assert client.get("/currentUser", headers=new_headers).json()["code"] == "200"


def test_token_without_password_fingerprint_is_rejected(client):
    """改造前的旧 token 没有 pv 字段，或者 pv 不对，都按失效处理。"""
    username = f"jiutoken{TEST_MARK}"
    assert _register(client, username)["code"] == "200"
    user_id = _login(client, username)["data"]["id"]

    legacy = _craft_token(user_id)                     # 无 pv
    wrong = _craft_token(user_id, pv="0" * 16)         # pv 不对
    assert client.get("/currentUser", headers={"token": legacy}).json()["code"] == "401"
    assert client.get("/currentUser", headers={"token": wrong}).json()["code"] == "401"


def test_disabled_account_token_is_rejected(client, admin_headers):
    """账号被停用后，已经拿到的 token 也立即不能用；重新启用后同一 token 恢复可用。"""
    username = f"beiting{TEST_MARK}"
    added = client.post(
        "/user/add", json={"username": username, "name": username}, headers=admin_headers
    ).json()
    assert added["code"] == "200"
    login = _login(client, username, password="123456")
    assert login["code"] == "200"
    headers = {"token": login["data"]["token"]}
    user_id = login["data"]["id"]

    disabled = client.put(
        "/user/update", json={"id": user_id, "status": "DISABLED"}, headers=admin_headers
    ).json()
    assert disabled["code"] == "200"
    assert client.get("/currentUser", headers=headers).json()["code"] == "401"

    restored = client.put(
        "/user/update", json={"id": user_id, "status": "NORMAL"}, headers=admin_headers
    ).json()
    assert restored["code"] == "200"


# ---------------------------------------------------------------- 当前登录账号


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