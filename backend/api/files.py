"""文件上传下载接口。"""

from fastapi import APIRouter, Depends, File, UploadFile
from starlette.responses import FileResponse

from common.auth import get_current_user
from common.result import Result
from models import User
from service import file_service

router = APIRouter(prefix="/files")


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传单个文件，返回可直接访问的下载地址。

    必须登录才能上传：不登录就能往服务器磁盘写文件，等于把存储空间敞开给任何人。
    当前用户只用来鉴权，文件本身不记归属，业务表里存的是返回的下载地址。
    """
    # 参数类型写成 UploadFile 而不是普通字段，
    # 因为浏览器上传走的是 multipart/form-data，不是 JSON
    return Result.success(file_service.save(file))


@router.get("/download/{filename}")
async def download_file(filename: str):
    """按文件名下载文件。下载保持公开，页面上的图片地址可以直接指向这里。"""
    # 文件名写在路径上，浏览器 img 标签的 src 可以直接指向这个地址。
    # resolve 只认服务端生成的 UUID 文件名，并且确认文件就在上传目录里，
    # 借道 ../ 之类的路径读别的文件会在这层被拦下
    return FileResponse(
        path=file_service.resolve(filename),
        filename=filename,
        # 按扩展名给响应类型，浏览器拿图片地址就能直接显示，不用猜类型
        media_type=file_service.media_type_of(filename),
    )