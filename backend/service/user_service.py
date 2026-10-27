"""用户管理业务逻辑。

管理端的用户管理对 user 表做分页查询、新增、编辑和删除。
租客的从属资料跟着账号走，删账号时一并清掉；已经产生匹配记录的账号
属于业务流水，删不掉，只能把账号停用。
"""

import re
from typing import List

from common.exception_handler import CustomException
from common.result import PageInfo
from common.security import hash_password
from common.times import format_datetime
from models import (
    MatchCandidate,
    MatchTask,
    MemberMoment,
    MemberPortrait,
    MemberProfile,
    RoommatePreference,
    User,
)
from service import file_service
from service.account_service import ROLES, STATUSES, check_password, check_username

# 新增账号时密码框留空用的默认密码，和弹窗里的占位提示一致
DEFAULT_PASSWORD = "123456"

# 电话和邮箱的格式。个人资料页和管理端的用户弹窗走的是同一个更新接口，
# 规则写在这里，两边不用各写一套
PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _check_profile(update_data: dict) -> None:
    """个人资料字段校验，顺手把空字符串统一成空值。

    姓名是列表页和匹配流程里都要用的字段，不允许留空；
    电话和邮箱允许不填，所以先看有没有值，有值才判格式。
    清空之后存空值而不是空字符串，库里「有没有填过」这一判断才准。
    """
    if "name" in update_data:
        name = (update_data["name"] or "").strip()
        if not name:
            raise CustomException("请输入姓名")
        update_data["name"] = name
    if "phone" in update_data:
        phone = (update_data["phone"] or "").strip()
        if phone and not PHONE_PATTERN.fullmatch(phone):
            raise CustomException("电话请填写 11 位手机号")
        update_data["phone"] = phone or None
    if "email" in update_data:
        email = (update_data["email"] or "").strip()
        if email and not EMAIL_PATTERN.fullmatch(email):
            raise CustomException("邮箱格式不正确")
        update_data["email"] = email or None


def user_dict(user: User) -> dict:
    # 列表每一列取的都是这里的字段，密码不放进来，页面上看不到密码
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "avatar": user.avatar,
        "role": user.role,
        "phone": user.phone,
        "email": user.email,
        "status": user.status,
        # 时间统一格式化成字符串再返回，页面直接展示，
        # 不用每个用到账号信息的地方再处理一次时间格式
        "create_time": format_datetime(user.create_time),
        "update_time": format_datetime(user.update_time),
    }


async def add(payload: dict) -> None:
    # 账号和密码的格式规则与自助注册共用同一套，不在这里再写一遍长度判断
    username = check_username(payload.get("username"))
    password = check_password(payload.get("password") or DEFAULT_PASSWORD)
    # 账号唯一，重复就中断，不进入插入逻辑
    if await User.get_or_none(username=username):
        raise CustomException("账号已存在，请换一个账号")
    # 弹窗默认给的是 USER，这里再兜一次底，防止绕过页面直接调接口传乱值
    role = payload.get("role") or "USER"
    if role not in ROLES:
        raise CustomException("角色参数错误")
    # 状态不填默认正常，新建的账号可以直接登录
    status = payload.get("status") or "NORMAL"
    if status not in STATUSES:
        raise CustomException("账号状态参数错误")
    await User.create(
        username=username,
        # 库里只存哈希，明文密码不落库
        password=hash_password(password),
        # 姓名不填就用账号顶上，保证列表页姓名列不为空
        name=payload.get("name") or username,
        avatar=payload.get("avatar"),
        role=role,
        phone=payload.get("phone"),
        email=payload.get("email"),
        status=status,
    )


async def update(current_user: User, user_id: int | None, update_data: dict) -> None:
    if user_id is None:
        raise CustomException("用户ID不能为空")
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise CustomException("未找到用户")
    # 管理员可以改任何人，普通用户只能改自己
    if current_user.role != "ADMIN" and current_user.id != user.id:
        raise CustomException("只能修改自己的账号信息，要改别人的账号请用管理员账号操作", "403")
    # 普通用户不允许给自己改角色和账号状态
    if current_user.role != "ADMIN":
        update_data.pop("role", None)
        update_data.pop("status", None)
    # 传了角色就必须是合法值，没传则跳过校验
    if update_data.get("role") is not None and update_data["role"] not in ROLES:
        raise CustomException("角色参数错误")
    # 传了状态就必须是合法值，没传则跳过校验
    if update_data.get("status") is not None and update_data["status"] not in STATUSES:
        raise CustomException("账号状态参数错误")
    # 给自己降级或停用会立刻丢掉管理端入口，下次登录就回不来了，直接拦住
    if user.id == current_user.id:
        if update_data.get("role") == "USER":
            raise CustomException("不能把自己的角色改成租客")
        if update_data.get("status") == "DISABLED":
            raise CustomException("不能停用当前登录账号")
    _check_profile(update_data)
    old_avatar = user.avatar
    await User.filter(id=user.id).update(**update_data)
    # 换了新头像，旧文件没有别的账号在用就删掉，files 目录不会越堆越多
    new_avatar = update_data.get("avatar")
    if new_avatar and old_avatar and new_avatar != old_avatar:
        if not await User.filter(avatar=old_avatar).exists():
            file_service.remove(old_avatar)


async def _member_of(user: User) -> MemberProfile | None:
    """取账号名下的租客档案。管理员账号没有档案，返回 None。"""
    return await MemberProfile.get_or_none(user_id=user.id)


async def _check_deletable(user: User) -> None:
    """删除前的校验：被业务流水引用的账号不能删，只能停用。

    候选池、运行记录都挂在匹配任务上，
    所以查一次匹配任务就能知道这个租客自己有没有留下流水。
    """
    profile = await _member_of(user)
    if profile is None:
        return
    task_count = await MatchTask.filter(member_id=profile.id).count()
    if task_count:
        raise CustomException(f"「{user.name}」已有 {task_count} 次匹配记录，账号不能删除，请改为停用")
    # 别的租客已经把他筛进候选池，删掉之后那些记录会指向一个不存在的租客，同样拦住
    candidate_count = await MatchCandidate.filter(candidate_member_id=profile.id).count()
    if candidate_count:
        raise CustomException(f"「{user.name}」已被其他租客的匹配流程引用，账号不能删除，请改为停用")


async def _delete_one(user: User) -> None:
    """删掉一个账号，并清掉挂在它名下的租客从属数据。"""
    profile = await _member_of(user)
    if profile is not None:
        # 生活照和动态配图都是上传下来的磁盘文件，记录删完就没有地方引用它们了。
        # 地址先收齐，记录删完再一起清，files 目录不会只涨不消
        files = [profile.photo_paths]
        files += [row.image_paths
                  for row in await MemberMoment.filter(member_id=profile.id)]
        # 从属数据按依赖倒序删：画像、偏好、动态都挂在租客档案上，
        # 最后才删档案本身
        await MemberPortrait.filter(member_id=profile.id).delete()
        await RoommatePreference.filter(member_id=profile.id).delete()
        await MemberMoment.filter(member_id=profile.id).delete()
        await MemberProfile.filter(id=profile.id).delete()
        # 这些文件已经没有记录再引用，跟着一起清掉
        file_service.remove(",".join(item for item in files if item))
    avatar = user.avatar
    await User.filter(id=user.id).delete()
    # 头像文件可能还被别的账号用着（初始化数据里有几个账号共用同一张占位图），
    # 确认没有其他账号引用之后再删
    if avatar and not await User.filter(avatar=avatar).exists():
        file_service.remove(avatar)


async def delete(current_user: User, user_id: int) -> None:
    # 删掉自己会导致当前会话立刻失效，页面停在一个无效登录态上，直接拦住
    if current_user.id == user_id:
        raise CustomException("不能删除当前登录账号")
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise CustomException("未找到用户")
    await _check_deletable(user)
    await _delete_one(user)


async def delete_batch(current_user: User, ids: List[int]) -> None:
    # 勾选里包含自己就整批拦下，不做「跳过自己删其他人」的处理，
    # 避免用户以为全删了、实际漏了一条
    if current_user.id in ids:
        raise CustomException("不能删除当前登录账号")
    users = await User.filter(id__in=ids)
    # 先整批校验、再整批删：删到一半被拦下来会让人看不出这次到底删成功了没有
    for user in users:
        await _check_deletable(user)
    # 批量删除复用单条删除的整套逻辑，两边不会走岔
    for user in users:
        await _delete_one(user)


async def select_by_id(current_user: User, user_id: int) -> dict:
    # 普通用户只能查自己那条，防止改地址栏 id 看别人的账号信息
    if current_user.role != "ADMIN" and current_user.id != user_id:
        raise CustomException("只能查看自己的账号信息", "403")
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise CustomException("未找到用户")
    return user_dict(user)


async def select_all(name: str = "") -> List[dict]:
    users = await User.filter(name__contains=name).order_by("-id")
    return [user_dict(user) for user in users]


async def select_page(name: str = "", role: str = "", page_num: int = 1, page_size: int = 10) -> PageInfo:
    # name 来自页面顶部姓名输入框，contains 是模糊匹配；
    # 空字符串时匹配所有记录，等于不加这个条件
    query = User.filter(name__contains=name)
    # role 来自角色下拉框，只有选了角色才追加精确匹配条件
    if role:
        query = query.filter(role=role)
    # 按 id 倒序排，新建的账号排在最前面；
    # offset 跳过前面几页的数据，limit 取当前页的条数
    users = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    # 总条数要用不带分页的同一个 query 去数，分页条靠它算出总页数
    total = await query.count()
    return PageInfo(total=total, list=[user_dict(user) for user in users])
