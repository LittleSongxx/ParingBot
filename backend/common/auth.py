from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Header

from common.exception_handler import CustomException
from models import User
from settings import JWT_ALGORITHM, JWT_EXPIRE_HOURS, JWT_SECRET


def create_token(user: User) -> str:
    expire_time = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {"sub": str(user.id), "role": user.role, "exp": expire_time}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(token: str | None = Header(default=None)) -> User:
    if not token:
        raise CustomException("登录状态已失效，请重新登录", "401")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
    except (jwt.InvalidTokenError, TypeError, ValueError):
        raise CustomException("登录状态已失效，请重新登录", "401")
    user = await User.get_or_none(id=user_id)
    if user is None or user.status != "NORMAL":
        raise CustomException("账号不存在或已被停用，请联系管理员", "401")
    return user


async def require_admin(token: str | None = Header(default=None)) -> User:
    user = await get_current_user(token)
    if user.role != "ADMIN":
        raise CustomException("这个操作只有管理员能做，请换成管理员账号后再试", "403")
    return user
