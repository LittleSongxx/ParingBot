"""安全相关的纯函数与接口测试。

覆盖四块：
1. 密码哈希格式、校验、历史明文兼容、needs_rehash；
2. 上传接口必须登录，落盘文件名由服务端生成（UUID），非图片扩展名被拒，
   同名上传不覆盖，超过大小上限被拒且不留半文件；
3. 下载接口保持公开，路径穿越和不存在文件一律按 404 处理；
4. /user/selectAll 只有管理员能调。

上传的文件落盘后名字是 UUID，conftest 的清扫夹具按「单元测试专用」匹配不到它，
所以上传的文件由用例自己回收；会写进数据库的账号都带「单元测试专用」后缀。
不需要真实模型 Key。

运行前提：MySQL 已启动，且已执行过 smartlect.sql。
"""

import os
import re

import pytest

from common.exception_handler import CustomException
from common.security import (
    HASH_ITERATIONS,
    hash_password,
    needs_rehash,
    verify_password,
)
from service import account_service, file_service
from settings import MAX_UPLOAD_MB

# 测试数据统一带这个后缀，会落库的记录由清扫夹具按它回收
TEST_MARK = "单元测试专用"

# 服务端生成的磁盘文件名：32 位 uuid 十六进制 + 图片扩展名
UUID_FILENAME = re.compile(r"^[0-9a-f]{32}\.(jpg|jpeg|png|webp|gif)$")

# 一张最小的 1x1 PNG，字节固定，上传下载用例反复用
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f5e0000000049454e44ae426082"
)


@pytest.fixture()
def upload(client):
    """带 token 上传一张测试图片，用例结束后把落盘的文件删掉。

    落盘文件名是 UUID，清扫夹具按名字匹配不到，必须在用例这一层回收。
    """
    created = []

    def _upload(filename, headers, content=PNG_BYTES):
        body = client.post(
            "/files/upload",
            files={"file": (filename, content, "image/png")},
            headers=headers,
        ).json()
        if body.get("code") == "200" and body.get("data"):
            created.append(body["data"])
        return body

    yield _upload
    for url in created:
        file_service.remove(url)


# ---------------------------------------------------------------------------
# 密码哈希纯函数
# ---------------------------------------------------------------------------

def test_hash_password_uses_fixed_pbkdf2_format():
    """存储格式固定为 pbkdf2_sha256$迭代次数$盐$摘要，且不包含明文。"""
    stored = hash_password("abc123456")
    parts = stored.split("$")
    assert len(parts) == 4
    assert parts[0] == "pbkdf2_sha256"
    assert parts[1] == str(HASH_ITERATIONS)
    # 16 字节盐 = 32 个十六进制字符；SHA-256 摘要 32 字节 = 64 个
    assert len(parts[2]) == 32
    assert len(parts[3]) == 64
    assert "abc123456" not in stored


def test_hash_password_generates_a_new_salt_each_time():
    """同一个密码每次哈希结果都不同（盐不同），但都能校验通过。"""
    first = hash_password("abc123456")
    second = hash_password("abc123456")
    assert first != second
    assert verify_password("abc123456", first)
    assert verify_password("abc123456", second)


def test_verify_password_accepts_matching_password_only():
    """只有原密码能通过校验，错密码、空值、空哈希都返回 False。"""
    stored = hash_password("abc123456")
    assert verify_password("abc123456", stored) is True
    assert verify_password("abc654321", stored) is False
    assert verify_password(None, stored) is False
    assert verify_password("abc123456", None) is False


def test_verify_password_keeps_legacy_plaintext_compatible():
    """历史数据里的明文密码仍然能校验，升级前老账号不会登不上。"""
    assert verify_password("123456", "123456") is True
    assert verify_password("654321", "123456") is False


def test_needs_rehash_flags_plaintext_and_outdated_iterations():
    """新哈希不用重算；明文、格式损坏、迭代次数过时都要重算。"""
    fresh = hash_password("abc123456")
    assert needs_rehash(fresh) is False
    assert needs_rehash("123456") is True
    assert needs_rehash(None) is True
    assert needs_rehash("pbkdf2_sha256$120000$bad") is True
    # 把迭代次数改小，模拟历史版本的哈希
    outdated = fresh.replace(f"${HASH_ITERATIONS}$", "$1$", 1)
    assert needs_rehash(outdated) is True


async def test_login_upgrades_legacy_plaintext_password(db):
    """老明文密码登录成功后自动升级成哈希，用户不用改密码。"""
    from models import User

    username = f"shengji{TEST_MARK}"
    await User.create(username=username, password="old-plain", name=username, role="USER")

    await account_service.login(username, "old-plain")

    user = await User.get(username=username)
    assert user.password.startswith("pbkdf2_sha256$")
    assert verify_password("old-plain", user.password)
    # 升级之后原来的明文不应再作为密码通过校验的旁路存在
    assert "old-plain" not in user.password


# ---------------------------------------------------------------------------
# 文件业务纯函数
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    [
        "",
        "1.png",
        "../main.py",
        "..%2F..%2Fmain.py",
        "A" * 32 + ".png",          # 大写 uuid 不是服务端生成的格式
        "0" * 31 + ".png",          # 长度不对
        "0" * 32 + ".exe",          # 扩展名不在白名单
    ],
)
def test_resolve_rejects_unsafe_filenames(name):
    """下载定位只认服务端生成的 UUID 文件名，其余一律按不存在处理。"""
    with pytest.raises(CustomException) as error:
        file_service.resolve(name)
    assert error.value.code == "404"


def test_media_type_follows_extension():
    """下载响应的媒体类型按扩展名给，认不出的按二进制流。"""
    assert file_service.media_type_of("a.PNG") == "image/png"
    assert file_service.media_type_of("b.jpeg") == "image/jpeg"
    assert file_service.media_type_of("c.jpg") == "image/jpeg"
    assert file_service.media_type_of("d.webp") == "image/webp"
    assert file_service.media_type_of("e.gif") == "image/gif"
    assert file_service.media_type_of("f.bin") == "application/octet-stream"
    assert file_service.media_type_of(None) == "application/octet-stream"


# ---------------------------------------------------------------------------
# 上传接口
# ---------------------------------------------------------------------------

def test_upload_without_token_returns_401(client):
    """不登录不能往服务器写文件。"""
    response = client.post(
        "/files/upload",
        files={"file": (f"weidenglu{TEST_MARK}.png", PNG_BYTES, "image/png")},
    )
    assert response.json()["code"] == "401"


def test_upload_saves_uuid_filename_and_returns_download_url(client, admin_headers, upload):
    """带 token 上传后返回下载地址，磁盘上的文件名是 32 位 uuid。"""
    body = upload(f"touxiang{TEST_MARK}.png", admin_headers)
    assert body["code"] == "200"

    url = body["data"]
    # 地址里带下载前缀，最后一段是服务端生成的文件名
    assert "/files/download/" in url
    filename = url.rsplit("/", 1)[-1]
    assert UUID_FILENAME.fullmatch(filename)
    # 文件确实落在了上传目录里
    assert os.path.isfile(os.path.join(file_service.UPLOAD_DIR, filename))


def test_uploaded_file_can_be_downloaded_without_token(client, admin_headers, upload):
    """下载保持公开，图片地址不带 token 也能取到原字节。"""
    body = upload(f"gongkai{TEST_MARK}.png", admin_headers)
    filename = body["data"].rsplit("/", 1)[-1]

    response = client.get("/files/download/" + filename)
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("image/png")
    assert response.content == PNG_BYTES


def test_upload_rejects_non_image_extension(client, admin_headers):
    """扩展名不在图片白名单里直接拒绝，不落盘。"""
    body = client.post(
        "/files/upload",
        files={"file": (f"xieyi{TEST_MARK}.txt", b"plain text", "text/plain")},
        headers=admin_headers,
    ).json()
    assert body["code"] == "500"
    assert "只允许上传图片文件" in body["msg"]


def test_upload_same_original_name_does_not_overwrite(client, admin_headers, upload):
    """两次上传同名原文件，磁盘上生成两个不同的 UUID 文件，互不覆盖。"""
    first = upload(f"chongming{TEST_MARK}.png", admin_headers)
    second = upload(f"chongming{TEST_MARK}.png", admin_headers)
    assert first["code"] == second["code"] == "200"
    assert first["data"] != second["data"]

    first_name = first["data"].rsplit("/", 1)[-1]
    second_name = second["data"].rsplit("/", 1)[-1]
    assert first_name != second_name
    for name in (first_name, second_name):
        assert UUID_FILENAME.fullmatch(name)
        assert os.path.isfile(os.path.join(file_service.UPLOAD_DIR, name))


def test_upload_over_limit_is_rejected_and_partial_file_removed(client, admin_headers):
    """超过大小上限要拒绝，写到一半的半文件也要删掉。"""
    os.makedirs(file_service.UPLOAD_DIR, exist_ok=True)
    before = set(os.listdir(file_service.UPLOAD_DIR))
    too_large = b"0" * (MAX_UPLOAD_MB * 1024 * 1024 + 1)

    body = client.post(
        "/files/upload",
        files={"file": (f"chaoda{TEST_MARK}.png", too_large, "image/png")},
        headers=admin_headers,
    ).json()

    assert body["code"] == "500"
    assert "不能超过" in body["msg"]
    assert set(os.listdir(file_service.UPLOAD_DIR)) == before


# ---------------------------------------------------------------------------
# 下载接口
# ---------------------------------------------------------------------------

def test_download_path_traversal_is_rejected(client):
    """..%2F 这类借文件名读目录外文件的请求一律拒绝。"""
    response = client.get("/files/download/..%2F..%2Fmain.py")
    # 路由层匹配不上时返回 HTTP 404，业务层拦下时是 HTTP 200 + code 404，
    # 两种都算拒绝，不能把后端源码之类的文件返回出去
    assert response.status_code == 404 or response.json().get("code") == "404"


def test_download_unknown_uuid_file_returns_404_code(client):
    """格式合法但文件不存在时返回 404 业务码，前端据此提示重新上传。"""
    body = client.get("/files/download/" + "0" * 32 + ".png").json()
    assert body["code"] == "404"


# ---------------------------------------------------------------------------
# 用户列表权限
# ---------------------------------------------------------------------------

def test_select_all_requires_admin(client, user_headers, admin_headers):
    """用户列表只给管理员：租客 403，管理员 200 且不带密码字段。"""
    member = client.get("/user/selectAll", headers=user_headers).json()
    assert member["code"] == "403"

    admin = client.get("/user/selectAll", headers=admin_headers).json()
    assert admin["code"] == "200"
    assert isinstance(admin["data"], list)
    for row in admin["data"]:
        assert "password" not in row