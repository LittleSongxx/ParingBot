from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette import status
from starlette.responses import JSONResponse


# 自定义异常类
class CustomException(Exception):
    def __init__(self, message: str, code: str = "500"):
        self.message = message
        self.code = code


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
        return JSONResponse(
            status_code=status.HTTP_200_OK,  # http总是返回200
            content={"code": "500", "msg": "提交的内容格式不对，请检查页面上填写的内容后重试"}
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # 兜底分支。走到这里说明是没预料到的错误，详细信息打到后端控制台供排查
        print("捕获到未处理的错误:", repr(exc))
        """处理所有异常"""
        # 返回统一格式。用户看的是页面上这句提示，
        # 所以要说清下一步能做什么，不能只甩一句笼统的错误提示
        response = JSONResponse(
            status_code=status.HTTP_200_OK,  # http总是返回200
            content={"code": "500", "msg": "服务器处理出错，请稍后重试；如果一直失败，请把操作步骤告诉管理员"}
        )
        # 允许所有源（与你的 CORS 配置一致）
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response
