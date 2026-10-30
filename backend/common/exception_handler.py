from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette import status
from starlette.responses import JSONResponse

# 校验失败时最多把几个字段名带进提示里，避免字段很多时提示长到看不清
MAX_REPORTED_FIELDS = 3


# 自定义异常类
class CustomException(Exception):
    def __init__(self, message: str, code: str = "500"):
        self.message = message
        self.code = code


def _validation_fields(exc: RequestValidationError) -> str:
    """从 pydantic 的校验错误里挑出字段名，拼成一句能指回页面的提示。"""
    names: list[str] = []
    for item in exc.errors():
        location = item.get("loc") or ()
        # loc 的第一段是请求位置（query/body/header），后面才是页面上的字段名
        parts = [str(part) for part in location if str(part) not in ("query", "body", "header", "path")]
        name = parts[-1] if parts else ""
        if name and name not in names:
            names.append(name)
        if len(names) >= MAX_REPORTED_FIELDS:
            break
    return "、".join(names)


def setup_exceptions(app: FastAPI):
    @app.exception_handler(CustomException)
    async def custom_exception_handler(request: Request, exc: CustomException):
        return JSONResponse(
            status_code=status.HTTP_200_OK,  # http总是返回200
            content={"code": exc.code, "msg": exc.message}
        )

    @app.exception_handler(RequestValidationError)
    async def validate_exception_handler(request: Request, exc: RequestValidationError):
        print("捕获到422错误:", exc.errors())
        """处理422异常"""
        # 返回统一格式。参数对不上是页面提交的内容有问题，
        # 提示要指回页面去改，不能只说一句「参数错误」
        fields = _validation_fields(exc)
        message = "提交的内容格式不对"
        if fields:
            message += f"（{fields}）"
        message += "，请检查页面上填写的内容后重试"
        return JSONResponse(
            status_code=status.HTTP_200_OK,  # http总是返回200
            content={"code": "500", "msg": message}
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # 兜底分支。走到这里说明是没预料到的错误，详细信息打到后端控制台供排查
        print("捕获到未处理的错误:", repr(exc))
        """处理所有异常"""
        # 返回统一格式。用户看的是页面上这句提示，
        # 所以要说清下一步能做什么，不能只甩一句笼统的错误提示。
        # 这里不手工写 CORS 头：跨域响应头统一由 CORSMiddleware 按白名单加，
        # 兜底分支自己写一份 "*" 等于给异常响应单开一个任意站点可读的口子
        return JSONResponse(
            status_code=status.HTTP_200_OK,  # http总是返回200
            content={"code": "500", "msg": "服务器处理出错，请稍后重试；如果一直失败，请把操作步骤告诉管理员"}
        )