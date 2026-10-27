"""应用入口。

启动时注册数据库、跨域、全部业务路由和统一异常处理器。
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import RegisterTortoise

from api import api_router
from common.exception_handler import setup_exceptions
from common.result import Result
from service import match_service
from settings import TORTOISE_ORM


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用从起来到关掉之间这一段：进出数据库，顺带把上次没跑完的运行收尾。

    匹配要跟模型来回几十次，跑的过程中服务被关掉，运行记录就会一直停在「运行中」，
    页面上永远挂着一个转不完的圈。启动时统一改成中断并写清下一步，
    看的人知道该重新发起一次。
    """
    # 进出这个上下文就是一次连库和断开，放在这里意味着服务起来时连上、关掉时断开
    async with orm:
        recovered = await match_service.recover_unfinished()
        if recovered:
            print(f"[运行恢复] 有 {recovered} 次运行没有跑完，已经标记为中断，可以在页面上重新发起")
        yield


app = FastAPI(title="SmartLect 智能合租匹配平台", lifespan=lifespan)

# 跨域配置 CORS。前端跑在 5173 端口、后端在 9090，属于跨域请求，
# 不配的话浏览器会拦掉所有接口调用。
app.add_middleware(
    CORSMiddleware,
    # 允许所有源
    allow_origins=["*"],
    # 允许所有 HTTP 方法
    allow_methods=["*"],
    # 允许所有请求头，前端要带自定义的 token 头
    allow_headers=["*"],
)

# 注册全部业务路由
app.include_router(api_router)

# 数据库连接。构造这一步会把两个 ORM 异常处理器挂到 app 上：记录不存在返回 404、
# 唯一键冲突返回 422。异常处理器必须在应用开始处理请求之前挂好——挪进 lifespan 里
# 就晚了，那时候中间件栈已经建好，后挂上去的处理器不会被用上。所以构造留在模块顶层，
# 连库与断开交给上面的 lifespan 进出它完成
orm = RegisterTortoise(app, config=TORTOISE_ORM, add_exception_handlers=True)
# 注册统一异常处理器
setup_exceptions(app)


@app.get("/")
async def root():
    return Result.success()


if __name__ == "__main__":
    uvicorn.run("main:app", host="localhost", reload=True, port=9090)
