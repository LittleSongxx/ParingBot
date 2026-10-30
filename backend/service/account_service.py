"""登录、注册、修改密码相关的业务逻辑。"""

import math
import uuid

from common import rate_limit
from common.auth import create_token
from common.exception_handler import CustomException
from common.security import (hash_password, needs_rehash, password_fingerprint,
                             verify_password)
from models import User

# 系统只有两种用户角色：管理端 ADMIN、用户端 USER
ROLES = {"ADMIN", "USER"}
STATUSES = {"NORMAL", "DISABLED"}

# 账号和密码的长度范围。下限是为了拦住一个字符的账号和过于简单的密码，
# 上限是给 user 表里 username 100 / password 255 的列宽留出余量
USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 30
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 30

# 登录失败统一提示。「账号不存在 / 密码错 / 账号被停用」三种情况共用这一句，
# 从提示上分不出账号状态，配合限流和常量时间校验一起用
LOGIN_FAILED_MESSAGE = "账号或密码错误"

# 账号不存在时用来跑一次校验的假哈希。真实账号错密码会跑一次 PBKDF2，
# 未知账号如果不跑，响应耗时明显更短，就能被用来枚举哪些账号存在。
_DUMMY_STORED: str | None = None


def _dummy_stored_password() -> str:
    """懒加载一条固定格式的假哈希，只消耗和真实校验相同的算力。"""
    global _DUMMY_STORED
    if _DUMMY_STORED is None:
        _DUMMY_STORED = hash_password(uuid.uuid4().hex)
    return _DUMMY_STORED


def _login_keys(username: str | None, client_ip: str | None) -> list[str]:
    """限流要记的两个维度：账号（统一小写）和来源 IP。"""
    keys: list[str] = []
    name = (username or "").strip().lower()
    if name:
        keys.append(f"账号:{name}")
    if client_ip:
        keys.append(f"IP:{client_ip}")
    return keys


def _lock_message(seconds: int) -> str:
    """锁定期间给用户的提示：说清多久之后可以再试。"""
    if seconds >= 60:
        minutes = max(1, math.ceil(seconds / 60))
        return f"登录失败次数太多，账号或来源已被锁定，请 {minutes} 分钟后再试"
    return f"登录失败次数太多，账号或来源已被锁定，请 {max(1, seconds)} 秒后再试"


def check_username(username: str | None) -> str:
    """账号格式校验，返回去掉首尾空格后的账号。

    账号规则只写在这一处，其它入口要校验账号时直接复用这个函数，
    不要各自再写一遍长度判断。
    """
    # 前端表单已经拦过一次空值，后端再拦一次，防止绕过页面直接调接口
    if not username or not username.strip():
        raise CustomException("请输入账号")
    username = username.strip()
    # 长度不在范围内时，提示里直接写清要几位，用户不用猜
    if len(username) < USERNAME_MIN_LENGTH or len(username) > USERNAME_MAX_LENGTH:
        raise CustomException(f"账号长度需要在 {USERNAME_MIN_LENGTH} 到 {USERNAME_MAX_LENGTH} 个字符之间")
    # 账号里带空格容易在登录时被误输成两个账号，直接拦下
    if " " in username:
        raise CustomException("账号里不能有空格")
    return username


def check_password(password: str | None) -> str:
    """密码格式校验，返回原密码。注册和修改密码共用同一套规则。"""
    if not password:
        raise CustomException("请输入密码")
    # 这里校验的是明文密码的长度；落库前会先转成哈希，哈希串本身长度固定
    if len(password) < PASSWORD_MIN_LENGTH or len(password) > PASSWORD_MAX_LENGTH:
        raise CustomException(f"密码长度需要在 {PASSWORD_MIN_LENGTH} 到 {PASSWORD_MAX_LENGTH} 个字符之间")
    return password


def account_dict(user: User, token: str | None = None) -> dict:
    """账号信息脱敏输出，不返回密码字段。"""
    # 这个字典就是前端 res.data 的内容，也是存进 localStorage 的登录态，
    # 页面右上角的姓名头像、路由守卫判断角色，用的都是这里的字段
    data = {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "avatar": user.avatar,
        "role": user.role,
        "phone": user.phone,
        "email": user.email,
        "status": user.status,
    }
    # 只有登录接口会传 token 进来，其他接口复用这个函数时不带 token
    if token:
        data["token"] = token
    return data


async def login(username: str | None, password: str | None,
                client_ip: str | None = None) -> dict:
    # 先看账号/IP 是否还在锁定期：锁着的时候连密码都不验，直接拒绝
    keys = _login_keys(username, client_ip)
    locked = rate_limit.lock_remaining(keys)
    if locked:
        raise CustomException(_lock_message(locked), "429")
    # 登录不做长度校验，只去掉首尾空格再去查：
    # 老账号的口径可能和新规则不同，这里统一报「账号或密码错误」比报长度不对更合适，
    # 也不会把账号的命名规则透露出去
    user = await User.get_or_none(username=(username or "").strip())
    # 账号不存在时也跑一次哈希校验，让两条分支的耗时落在同一个量级，
    # 不能让人靠响应时间试出哪些账号存在
    stored = user.password if user is not None else _dummy_stored_password()
    password_ok = verify_password(password, stored)
    # 账号不存在和密码错误合并成同一句提示，不告诉对方是哪一步错了。
    # 用 verify_password 校验：库里存的可能是新哈希，也可能是历史数据里的明文，
    # 两种都认，老账号不用改密码就能继续登录
    if user is None or not password_ok:
        rate_limit.record_failure(keys)
        raise CustomException(LOGIN_FAILED_MESSAGE)
    # 密码对了还要看状态，管理员在用户管理里停用的账号不允许登录。
    # 提示和密码错误共用同一句：说清「已被停用」等于告诉对方这个账号存在
    if user.status != "NORMAL":
        rate_limit.record_failure(keys)
        raise CustomException(LOGIN_FAILED_MESSAGE)
    # 旧明文密码（或迭代次数过时的哈希）在这里顺手升级成当前格式，
    # 用户无感，库里的口令也不会一直明文躺着
    if needs_rehash(user.password):
        hashed = hash_password(password)
        await User.filter(id=user.id).update(password=hashed)
        # 同步内存里的对象：下面签发 token 会用到这份存储值算密码指纹
        user.password = hashed
    # 登录成功清掉失败计数，正常用户不会被自己之前的输错连累
    rate_limit.record_success(keys)
    # 校验全通过，签发 token 并连同用户信息一起返回
    return account_dict(user, create_token(user))


async def register(username: str | None, password: str | None, confirm_password: str | None) -> None:
    # 账号和密码的格式校验走公共函数，规则只有一处，改的时候不会漏
    username = check_username(username)
    password = check_password(password)
    # 两次密码一致性后端也要复核，同样是防止绕过页面直接调接口
    if password != confirm_password:
        raise CustomException("两次输入的密码不一致")
    # 账号重复校验，命中就中断，不进入插入逻辑
    if await User.get_or_none(username=username):
        raise CustomException("账号已存在，请换一个账号")
    # 注册入口只能创建普通用户，管理员账号由管理端在用户管理里添加。
    # 库里只存哈希，明文密码不落库
    await User.create(
        username=username,
        password=hash_password(password),
        # 姓名默认填成账号，用户可以在个人资料页再改
        name=username,
        role="USER",
        status="NORMAL",
    )


async def update_password(
    current_user: User,
    password: str | None,
    new_password: str | None,
) -> None:
    if not password:
        raise CustomException("请输入原密码")
    # 原密码必须对得上，防止别人趁着页面没锁屏直接改密码。
    # 老数据里的明文密码同样能用 verify_password 校验通过
    if not verify_password(password, current_user.password):
        raise CustomException("原密码错误")
    if not new_password:
        raise CustomException("请输入新密码")
    # 新密码同样要过格式校验，不能通过改密码这一步绕开注册时的长度要求
    new_password = check_password(new_password)
    # 新旧密码一样等于没改，直接拦下来。
    # 用 verify_password 判断，哈希过的密码也能认出「新密码其实就是原密码」
    if verify_password(new_password, current_user.password):
        raise CustomException("新密码不能与原密码相同")
    # 按当前登录用户的 id 更新，改不到别人头上；新密码同样只存哈希。
    # 存储值一变，token 里的密码指纹就对不上，改密前签发的 token 全部立即失效
    await User.filter(id=current_user.id).update(password=hash_password(new_password))