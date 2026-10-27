"""文件上传下载业务逻辑。

上传落盘的文件名由服务端生成，不再用用户传上来的原始文件名：
1. 同名文件不会互相覆盖；
2. 用户传的名字不会变成磁盘上的路径，从根上避开路径穿越；
3. 扩展名白名单只放图片，别的类型一律拒绝。
"""

import os
import re
import uuid

from fastapi import UploadFile

from common.exception_handler import CustomException
from settings import MAX_UPLOAD_MB, PUBLIC_BASE_URL, UPLOAD_DIR

# 允许上传的图片扩展名，统一按小写比较
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
# 磁盘文件名格式：32 位 uuid 十六进制 + 小写扩展名。
# 下载接口只认这种由服务端生成的名字，其它名字（包括 ../ 之类的东西）一律不认
FILENAME_PATTERN = re.compile(r"^[0-9a-f]{32}\.(jpg|jpeg|png|webp|gif)$")
# 下载地址前缀。PUBLIC_BASE_URL 配了域名 / 端口就拼成绝对地址；
# 留空表示返回相对地址，页面跟着当前域名走，换域名不用重新上传已有图片
DOWNLOAD_PREFIX = (
    PUBLIC_BASE_URL.rstrip("/") + "/files/download/"
    if PUBLIC_BASE_URL
    else "/files/download/"
)
# 读取上传流的分块大小。按块读写，大文件不会整个读进内存
CHUNK_SIZE = 64 * 1024
# 每种扩展名对应的响应类型，下载时按扩展名告诉浏览器怎么打开
MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}
# 文件不存在时统一用 404 业务码，前端据此提示用户重新上传
NOT_FOUND_CODE = "404"
# 文件不存在时的统一提示，下载和删除都复用这一句
NOT_FOUND_MESSAGE = "文件不存在，可能已经被删除，请回到原来的页面重新上传"


def _extension_of(filename: str | None) -> str:
    """取上传文件的后缀并做白名单校验，返回小写后缀。"""
    name = (filename or "").strip()
    # 没有点说明连扩展名都没有，直接按「不是图片」处理
    if "." not in name:
        raise CustomException("只允许上传图片文件（jpg、jpeg、png、webp、gif）")
    extension = name.rsplit(".", 1)[-1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise CustomException("只允许上传图片文件（jpg、jpeg、png、webp、gif）")
    return extension


def _remove_quietly(file_path: str) -> None:
    """删除磁盘文件，删不掉就跳过。清理半文件时用，失败不往上抛。"""
    try:
        os.remove(file_path)
    except OSError:
        pass


def _upload_root() -> str:
    """上传目录的真实绝对路径，用来判断目标文件是否还在目录里面。"""
    return os.path.realpath(UPLOAD_DIR)


def _inside_upload_dir(file_path: str, upload_root: str) -> bool:
    """判断真实路径的父目录是不是就是上传目录本身。

    realpath 会把 ../ 和符号链接都展开，再比父目录，
    这样「上传目录里的文件」和「借路径读目录外的文件」就能分得开。
    """
    return os.path.dirname(file_path) == upload_root


def save(file: UploadFile) -> str:
    """保存上传的文件，返回可直接访问的下载地址。"""
    extension = _extension_of(file.filename)
    # 目录不存在时自动建，避免第一次上传报找不到路径
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{extension}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    try:
        with open(file_path, "wb") as buffer:
            written = 0
            while True:
                chunk = file.file.read(CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                # 超限立刻停：已经写进去的半文件也要删掉，
                # 否则每次被拒的上传都会在磁盘里留下一份垃圾
                if written > max_bytes:
                    raise CustomException(f"上传的文件不能超过 {MAX_UPLOAD_MB} MB")
                buffer.write(chunk)
    except CustomException:
        _remove_quietly(file_path)
        raise
    except OSError:
        _remove_quietly(file_path)
        raise CustomException("文件保存失败，请稍后重试")
    return DOWNLOAD_PREFIX + filename


def resolve(filename: str) -> str:
    """按文件名定位磁盘路径，文件名不合法或文件不存在时抛出人话提示。"""
    name = (filename or "").strip()
    # 第一道闸：文件名必须正好是服务端生成的样子
    if not FILENAME_PATTERN.fullmatch(name):
        raise CustomException(NOT_FOUND_MESSAGE, NOT_FOUND_CODE)
    upload_root = _upload_root()
    file_path = os.path.realpath(os.path.join(upload_root, name))
    # 第二道闸：展开后的文件必须直接躺在上传目录里
    if not _inside_upload_dir(file_path, upload_root):
        raise CustomException(NOT_FOUND_MESSAGE, NOT_FOUND_CODE)
    # 文件被手工删掉时，返回人话提示而不是 500
    if not os.path.isfile(file_path):
        raise CustomException(NOT_FOUND_MESSAGE, NOT_FOUND_CODE)
    return file_path


def _filename_of(file_url: str) -> str | None:
    """从相对或绝对的下载地址里取文件名，取不出安全的文件名时返回 None。"""
    text = (file_url or "").strip()
    if not text:
        return None
    # 去掉查询串和锚点，再取最后一段；绝对地址和相对地址走的是同一套
    text = text.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    name = text.rsplit("/", 1)[-1]
    if not name or name in {".", ".."}:
        return None
    # 正常取到的是磁盘文件名，不可能还带路径分隔符
    if "/" in name or "\\" in name or "\x00" in name:
        return None
    return name


def remove(file_url: str | None) -> None:
    """删除已经上传的文件，删不掉就跳过。

    传进来的既可能是保存时返回的下载地址（绝对或相对），也可能是逗号分隔的多个地址。
    文件是跟着业务记录走的从属数据，记录删掉了就没有地方再引用它，
    磁盘上的文件要跟着一起清，否则 files 目录只涨不消。
    删文件失败不影响数据库删除已经完成的事实，所以这里忽略错误，不往上抛。

    老数据里的文件名不一定是 UUID（历史文件名、占位图），所以这里不套
    FILENAME_PATTERN，但仍要求取出来的名字不带路径分隔符，并且真实路径
    必须就在上传目录里，防止借删除动作碰到目录外的文件。
    """
    if not file_url:
        return
    upload_root = _upload_root()
    for one in file_url.split(","):
        filename = _filename_of(one)
        if not filename:
            continue
        file_path = os.path.realpath(os.path.join(upload_root, filename))
        if not _inside_upload_dir(file_path, upload_root):
            continue
        _remove_quietly(file_path)


def media_type_of(filename: str | None) -> str:
    """按扩展名给出下载响应的媒体类型，认不出的按二进制流下载。"""
    extension = (filename or "").rsplit(".", 1)[-1].lower()
    return MEDIA_TYPES.get(extension, "application/octet-stream")