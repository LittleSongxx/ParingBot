from datetime import datetime, timedelta, timezone

import hmac

import jwt
from fastapi import Header

from common.exception_handler import CustomException
from common.security import password_fingerprint
from models import User
from settings import JWT_ALGORITHM, JWT_EXPIRE_HOURS, JWT_SECRET

# token 失效统一一句提示，不透露是过期、篡改还是改密导致的
TOKEN_INVALID_MESSAGE = "登录状态已失效，请重新登录"


def create_token(user: User) -> str:
    expire_time = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "exp": expire_time,
        # 密码指纹：库里密码一变（改密/重置），这个值就对不上，旧 token 自动失效
        "pv": password_fingerprint(user.password),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(token: str | None = Header(default=None)) -> User:
    if not token:
        raise CustomException(TOKEN_INVALID_MESSAGE, "401")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
        token_fingerprint = str(payload.get("pv") or "")
    except (jwt.InvalidTokenError, TypeError, ValueError):
        raise CustomException(TOKEN_INVALID_MESSAGE, "401")
    user = await User.get_or_none(id=user_id)
    if user is None or user.status != "NORMAL":
        raise CustomException("账号不存在或已被停用，请联系管理员", "401")
    # 指纹对不上说明这个 token 是改密之前签发的：按失效处理，等同把旧 token 吊销。
    # 没有 pv 的是改造前的旧 token，同样不认。
    if not token_fingerprint or not hmac.compare_digest(
            token_fingerprint, password_fingerprint(user.password)):
        raise CustomException(TOKEN_INVALID_MESSAGE, "401")
    return user


async def require_admin(token: str | None = Header(default=None)) -> User:
    user = await get_current_user(token)
    if user.role != "ADMIN":
        raise CustomException("这个操作只有管理员能做，请换成管理员账号后再试", "403")
    return user
