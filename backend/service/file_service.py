"""文件上传下载业务逻辑。"""

import os
import shutil

from fastapi import UploadFile

from common.exception_handler import CustomException

# 上传的文件统一放在 fastapi-app/files 目录下
UPLOAD_DIR = "files"
# 下载地址前缀，和后端启动端口保持一致；
# 上传成功后拼上文件名返回给前端，前端把这个地址存进数据库
DOWNLOAD_PREFIX = "http://127.0.0.1:9090/files/download/"


def save(file: UploadFile) -> str:
    """保存上传的文件，返回可直接访问的下载地址。"""
    # 目录不存在时自动建，避免第一次上传报找不到路径
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    # 用原始文件名保存，同名文件会被覆盖
    file_location = os.path.join(UPLOAD_DIR, file.filename)
    # 以二进制写入，copyfileobj 分块拷贝，大文件不会一次性读进内存
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return DOWNLOAD_PREFIX + file.filename


def resolve(filename: str) -> str:
    """按文件名定位磁盘路径，文件不存在时给出明确提示。"""
    file_path = os.path.join(UPLOAD_DIR, filename)
    # 文件被手工删掉或者文件名拼错时，返回人话提示而不是 500
    if not os.path.exists(file_path):
        raise CustomException("文件不存在，可能已经被删除，请回到原来的页面重新上传")
    return file_path


def remove(file_url: str | None) -> None:
    """删除已经上传的文件，删不掉就跳过。

    传进来的既可能是保存时返回的下载地址，也可能是逗号分隔的多个地址。
    文件是跟着业务记录走的从属数据，记录删掉了就没有地方再引用它，
    磁盘上的文件要跟着一起清，否则 files 目录只涨不消。
    删文件失败不影响数据库删除已经完成的事实，所以这里忽略错误，不往上抛。
    """
    if not file_url:
        return
    for one in file_url.split(","):
        # 地址形如 http://127.0.0.1:9090/files/download/3.png，取最后一段就是文件名
        filename = one.strip().rsplit("/", 1)[-1]
        if not filename:
            continue
        try:
            os.remove(os.path.join(UPLOAD_DIR, filename))
        except OSError:
            pass
