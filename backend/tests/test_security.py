"""安全相关的纯函数与接口测试。

覆盖：
1. 密码哈希格式、校验、历史明文兼容、needs_rehash、密码指纹；
2. 日志脱敏 redact_text（手机号/邮箱/身份证号打码）；
3. 分页参数归一化 normalize_page，以及接口层的负数/超大/非数字分页；
4. 上传接口必须登录、UUID 文件名、图片文件头（魔数）校验、非图片扩展名、
   同名不覆盖、超过大小上限且不留半文件；
5. 下载保持公开、路径穿越/不存在文件一律 404；
6. 全局异常不再手写 ACAO:*、CORS 白名单生效；
7. /user/selectAll 死接口已删除、列表接口权限；
8. 账号级联删除使用事务（静态断言）。

上传的文件落盘后名字是 UUID，conftest 的清扫夹具按「单元测试专用」匹配不到它，
所以上传的文件由用例自己回收；会写进数据库的账号都带「单元测试专用」后缀。
不需要真实模型 Key。

运行前提：MySQL 已启动，且已执行过 paringbot.sql。
"""

import inspect
import os
import re

import pytest
from fastapi.testclient import TestClient

from common.exception_handler import CustomException
from common.pagination import MAX_PAGE_NUM, MAX_PAGE_SIZE, normalize_page
from common.redact import redact_text
from common.security import (
    HASH_ITERATIONS,
    hash_password,
    needs_rehash,
    verify_password,
)
from main import app
from service import file_service, user_service
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
# 最小 JPEG 头（只看文件头，服务端不解码图片内容）
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
# 改名伪装成 .png 的 HTML
FAKE_IMAGE_BYTES = b"<html><script>alert(1)</script></html>"


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


# ---------------------------------------------------------------------------
# 日志脱敏
# ---------------------------------------------------------------------------

def test_redact_text_masks_phone_email_and_id_card():
    """手机号、邮箱、身份证号打码，排查日志仍看得出字段形态。"""
    text = "联系 13800138000，邮箱 zhangsan@example.com，身份证 110101199001011234"
    masked = redact_text(text)
    assert "13800138000" not in masked
    assert "138****8000" in masked
    assert "zhangsan@example.com" not in masked
    assert "z***@example.com" in masked
    assert "110101199001011234" not in masked
    assert "110***********1234" in masked


def test_redact_text_keeps_normal_text_and_none():
    """没有 PII 的正常文本原样返回；None 保持 None。"""
    text = "预算 3500 元，张江店，早睡早起，工号 20261030"
    assert redact_text(text) == text
    assert redact_text(None) is None


# ---------------------------------------------------------------------------
# 分页参数归一化
# ---------------------------------------------------------------------------

def test_normalize_page_clamps_negative_and_zero():
    """负数、0 一律夹回合法范围：页码至少 1，每页至少 1 条。"""
    assert normalize_page(-5, -3) == (1, 1)
    assert normalize_page(0, 0) == (1, 1)


def test_normalize_page_caps_huge_values():
    """超大每页条数夹到上限，超大页码也会封顶，offset 不会撑爆 BIGINT。"""
    page_num, page_size = normalize_page(10 ** 20, 10 ** 20)
    assert page_num == MAX_PAGE_NUM
    assert page_size == MAX_PAGE_SIZE
    assert normalize_page(2, 100000) == (2, MAX_PAGE_SIZE)


def test_normalize_page_falls_back_for_non_numbers():
    """非数字输入用兜底值，不抛异常。"""
    assert normalize_page("abc", "xyz") == (1, 10)
    assert normalize_page(None, None, default=20) == (1, 20)


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


def test_upload_rejects_html_disguised_as_png(client, admin_headers):
    """HTML 改名成 .png 也会被文件头校验拒绝，且不留下半文件。"""
    os.makedirs(file_service.UPLOAD_DIR, exist_ok=True)
    before = set(os.listdir(file_service.UPLOAD_DIR))

    body = client.post(
        "/files/upload",
        files={"file": (f"weizhuang{TEST_MARK}.png", FAKE_IMAGE_BYTES, "image/png")},
        headers=admin_headers,
    ).json()

    assert body["code"] == "500"
    assert "文件头校验失败" in body["msg"]
    assert set(os.listdir(file_service.UPLOAD_DIR)) == before


def test_upload_accepts_jpeg_by_magic(client, admin_headers, upload):
    """JPEG 文件头对上就能上传（媒体类型仍按扩展名给）。"""
    body = upload(f"zhaopian{TEST_MARK}.jpg", admin_headers, content=JPEG_BYTES)
    assert body["code"] == "200"
    filename = body["data"].rsplit("/", 1)[-1]
    assert filename.endswith(".jpg")
    assert os.path.isfile(os.path.join(file_service.UPLOAD_DIR, filename))


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
    """超过大小上限要拒绝，写到一半的半文件也要删掉。

    内容要以合法 PNG 头开头，否则会先被文件头校验拦下，测的就不是大小上限了。
    """
    os.makedirs(file_service.UPLOAD_DIR, exist_ok=True)
    before = set(os.listdir(file_service.UPLOAD_DIR))
    too_large = PNG_BYTES + b"0" * (MAX_UPLOAD_MB * 1024 * 1024)

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
# 分页接口（负数/超大/非数字不再打到全局 500）
# ---------------------------------------------------------------------------

def test_user_list_page_size_is_capped(client, admin_headers):
    """page_size 传 100000 也最多返回 MAX_PAGE_SIZE 条。"""
    body = client.get(
        "/user/selectPage?page_size=100000", headers=admin_headers).json()
    assert body["code"] == "200"
    assert len(body["data"]["list"]) <= MAX_PAGE_SIZE


def test_negative_page_num_is_clamped(client, admin_headers):
    """page_num 传 -1 按第 1 页处理，不再拼出非法 offset。"""
    body = client.get(
        "/user/selectPage?page_num=-1&page_size=5", headers=admin_headers).json()
    assert body["code"] == "200"
    assert len(body["data"]["list"]) <= 5


def test_negative_page_size_is_clamped_for_member_moments(client, user_headers):
    """租客动态列表 page_size=-1 也被夹到合法值，接口不再 500。"""
    body = client.get(
        "/moment/selectMyPage?page_size=-1", headers=user_headers).json()
    assert body["code"] == "200"


def test_member_page_size_is_capped(client, admin_headers):
    """租客管理列表同样受全局上限约束。"""
    body = client.get(
        "/member/selectPage?page_size=100000", headers=admin_headers).json()
    assert body["code"] == "200"
    assert len(body["data"]["list"]) <= MAX_PAGE_SIZE


def test_non_numeric_page_size_returns_readable_error(client, admin_headers):
    """非数字分页参数走校验分支，给出能指回字段的提示。"""
    body = client.get(
        "/member/selectPage?page_size=abc", headers=admin_headers).json()
    assert body["code"] == "500"
    assert "格式不对" in body["msg"]
    assert "page_size" in body["msg"]


# ---------------------------------------------------------------------------
# 全局异常 / CORS
# ---------------------------------------------------------------------------

def test_cors_only_allows_whitelisted_origin(client):
    """白名单来源能拿到 ACAO，其它来源拿不到。"""
    allowed = client.get("/", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    evil = client.get("/", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in {key.lower() for key in evil.headers}


def test_global_error_does_not_add_wildcard_cors(monkeypatch):
    """未处理异常走全局兜底时不再手工写 ACAO:*，跨域头只由 CORSMiddleware 决定。"""
    async def boom(*args, **kwargs):
        raise RuntimeError("unit-test boom")

    monkeypatch.setattr(user_service, "select_page", boom)
    # 兜底异常会再抛出给 TestClient，用 False 让测试拿到响应本身
    with TestClient(app, raise_server_exceptions=False) as failure_client:
        login = failure_client.post(
            "/login", json={"username": "admin", "password": "admin123"}).json()
        assert login["code"] == "200"
        token = login["data"]["token"]
        response = failure_client.get(
            "/user/selectPage",
            headers={"token": token, "Origin": "http://evil.example"},
        )

    assert response.json()["code"] == "500"
    header_names = {key.lower() for key in response.headers}
    assert "access-control-allow-origin" not in header_names


# ---------------------------------------------------------------------------
# 用户列表权限 / 死接口 / 级联删除事务
# ---------------------------------------------------------------------------

def test_select_all_endpoint_is_removed(client, admin_headers):
    """前端没在用、又容易变成用户枚举入口的 /user/selectAll 已删除。"""
    response = client.get("/user/selectAll", headers=admin_headers)
    assert response.status_code == 404


def test_user_list_requires_admin(client, user_headers, admin_headers):
    """用户列表只给管理员：租客 403，管理员 200 且不带密码字段。"""
    member = client.get("/user/selectPage", headers=user_headers).json()
    assert member["code"] == "403"

    admin = client.get("/user/selectPage?page_size=20", headers=admin_headers).json()
    assert admin["code"] == "200"
    for row in admin["data"]["list"]:
        assert "password" not in row


def test_cascade_delete_uses_a_transaction():
    """账号级联删除的五张表删除必须包在事务里（文件删除放事务后）。"""
    source = inspect.getsource(user_service._delete_one)
    assert "in_transaction" in source
    # 文件清理放在事务之后：事务里只做数据库删除
    assert source.index("in_transaction") < source.index("file_service.remove")