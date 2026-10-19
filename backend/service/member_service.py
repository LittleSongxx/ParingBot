"""租客档案业务逻辑。

租客在用户端填自己的档案、传生活照，提交后进入待审核；管理员在管理端逐条审核，
审核通过的档案才会进入匹配候选池。档案改动过就会退回待审核，
审核结论以最后一次为准，避免审核通过之后换个内容继续用同一个结论。
"""

from datetime import datetime
from typing import List

from common.exception_handler import CustomException
from common.result import PageInfo
from common.text import split_values
from common.times import LOCAL_TZ, format_datetime, now, to_local
from models import InterestTag, MemberProfile, User
from service import file_service

# 各维度的可选值。页面下拉框和后面的匹配筛选都按这几份清单取值，
# 模型和接口层不许自造取值
GENDERS = ("男", "女")
# 整洁度和租期都是有序档位，前面的档低、后面的档高，偏好里的「最低档」按这个顺序比
TIDINESS_LEVELS = ("随意", "一般", "整洁", "洁癖")
LEASE_TERMS = ("3个月以下", "3-6个月", "6-12个月", "1-2年", "2年以上")
SCHEDULE_TYPES = ("早睡早起", "正常作息", "夜猫子")
HAS_PET_OPTIONS = ("有", "无")
SMOKING_OPTIONS = ("不吸烟", "偶尔", "经常")
AUDIT_STATUSES = ("待审核", "已通过", "已驳回")
# 管理员能给出的审核结论，待审核是租客提交后的初始状态，不由管理员选
AUDIT_RESULTS = ("已通过", "已驳回")
ENABLED_OPTIONS = ("是", "否")

# 出生日期对应的年龄范围，超出范围基本是选错了年份
MIN_AGE = 18
MAX_AGE = 80
# 月租预算可填范围，单位元。档案里的预算和合住偏好里的预算区间用同一套口径，写在一处
MIN_BUDGET = 800
MAX_BUDGET = 20000
# 生活照最多放几张、兴趣标签最多选几个
MAX_PHOTO_COUNT = 9
MAX_TAG_COUNT = 8
# 自我介绍与室友期望的字数上限
MAX_INTRO_LENGTH = 1000
MAX_EXPECTATION_LENGTH = 500

# 固定的 20 家门店清单，编码就是它在清单里的位置。租客档案和候选检索按同一份清单取门店，
# 不单独建门店表——这张表只有 20 行，业务上又很少改动
STORE_LIST = (
    (1, "张江店"), (2, "金桥店"), (3, "唐镇店"), (4, "川沙店"),
    (5, "漕河泾店"), (6, "徐家汇店"), (7, "龙华店"), (8, "田林店"),
    (9, "五角场店"), (10, "新江湾店"), (11, "控江店"), (12, "大桥店"),
    (13, "莘庄店"), (14, "七宝店"), (15, "虹桥枢纽店"), (16, "紫竹店"),
    (17, "长风店"), (18, "真如店"), (19, "桃浦店"), (20, "中山北路店"),
)
STORE_MAP = dict(STORE_LIST)

# 门店所属片区。按门店范围检索候选时要判断「是不是同一个片区」，
# 片区写在一处，租客档案和匹配检索共用同一份口径
STORE_AREA = {
    1: "浦东", 2: "浦东", 3: "浦东", 4: "浦东",
    5: "徐汇", 6: "徐汇", 7: "徐汇", 8: "徐汇",
    9: "杨浦", 10: "杨浦", 11: "杨浦", 12: "杨浦",
    13: "闵行", 14: "闵行", 15: "闵行", 16: "闵行",
    17: "普陀", 18: "普陀", 19: "普陀", 20: "普陀",
}


def store_name(store_id: int | None) -> str | None:
    """按编码取门店名，编码对不上时返回空，页面不会展示出一个数字编码。"""
    return STORE_MAP.get(store_id)


def area_name(store_id: int | None) -> str | None:
    """按门店编码取片区，编码对不上时返回空。"""
    return STORE_AREA.get(store_id)


def calc_age(birth_date: datetime | None) -> int | None:
    """按出生日期现算年龄。

    年龄不落库，页面上展示、候选筛选时比较都用这个函数算出来的值，
    这样生日过了年龄自己就变了，不会出现库里存着 30、实际已经 31 的情况。
    """
    if not birth_date:
        return None
    birth = to_local(birth_date).date()
    today = now().date()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def _age_on(birth: datetime) -> int:
    """算某个生日到今天为止的年龄，校验年龄范围时用。"""
    today = now().date()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def _format_date(value: datetime | None) -> str | None:
    """出生日期只用到日期部分，按日期格式返回，日期选择器才能直接回填。"""
    return to_local(value).strftime("%Y-%m-%d") if value else None


def _required_text(payload: dict, key: str, label: str, max_length: int) -> str:
    value = (payload.get(key) or "").strip()
    if not value:
        raise CustomException(f"请填写{label}")
    if len(value) > max_length:
        raise CustomException(f"{label}最多 {max_length} 个字")
    return value


def _optional_text(payload: dict, key: str, label: str, max_length: int) -> str | None:
    value = (payload.get(key) or "").strip()
    if not value:
        return None
    if len(value) > max_length:
        raise CustomException(f"{label}最多 {max_length} 个字")
    return value


def _required_option(payload: dict, key: str, label: str, options: tuple) -> str:
    value = (payload.get(key) or "").strip()
    if not value:
        raise CustomException(f"请选择{label}")
    if value not in options:
        raise CustomException(f"{label}只能在 " + "、".join(options) + " 里选")
    return value


def _optional_option(payload: dict, key: str, label: str, options: tuple) -> str | None:
    value = (payload.get(key) or "").strip()
    if not value:
        return None
    if value not in options:
        raise CustomException(f"{label}只能在 " + "、".join(options) + " 里选")
    return value


def _check_birth_date(payload: dict) -> datetime:
    value = (payload.get("birth_date") or "").strip()
    if not value:
        raise CustomException("请选择出生日期")
    try:
        birth = datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        raise CustomException("出生日期格式不对，请在日期选择器里重新选一次")
    age = _age_on(birth)
    if age < MIN_AGE or age > MAX_AGE:
        raise CustomException(f"年龄需要在 {MIN_AGE} 到 {MAX_AGE} 岁之间，请检查出生日期")
    return birth.replace(tzinfo=LOCAL_TZ)


def _check_budget(payload: dict) -> int:
    try:
        budget = int(payload.get("rent_budget"))
    except (TypeError, ValueError):
        raise CustomException("请填写月租预算")
    if budget < MIN_BUDGET or budget > MAX_BUDGET:
        raise CustomException(f"月租预算请填 {MIN_BUDGET} 到 {MAX_BUDGET} 之间的元数")
    return budget


def _check_store(payload: dict) -> int:
    try:
        store_id = int(payload.get("store_id"))
    except (TypeError, ValueError):
        raise CustomException("请选择意向门店")
    if store_id not in STORE_MAP:
        raise CustomException("意向门店不在可选清单里，请从下拉列表里重新选择")
    return store_id


async def _check_interest_tags(payload: dict, keep: List[str] | None = None) -> str | None:
    """兴趣标签只认词表里启用的词。

    词表是画像师打标签和筛选官按兴趣检索共用的取值来源，
    这里放行了没登记的词，后面的画像和匹配就会对不上。

    keep 是这位租客档案里已经在用的标签：管理员把某个标签停用之后，老档案里
    那个词还在，租客再保存档案时不该因为一个早就选好的标签被卡住。
    """
    tags = split_values(payload.get("interest_tags"))
    if not tags:
        return None
    if len(tags) > MAX_TAG_COUNT:
        raise CustomException(f"兴趣标签最多选 {MAX_TAG_COUNT} 个")
    valid = await InterestTag.filter(tag_name__in=tags, enabled="是").values_list("tag_name", flat=True)
    allowed = set(valid) | set(keep or [])
    unknown = [tag for tag in tags if tag not in allowed]
    if unknown:
        raise CustomException("兴趣标签「" + "、".join(unknown) + "」不在可选清单里，请从下拉列表里重新选择")
    return ",".join(tags)


def _check_photos(payload: dict) -> str | None:
    photos = split_values(payload.get("photo_paths"))
    if len(photos) > MAX_PHOTO_COUNT:
        raise CustomException(f"生活照最多放 {MAX_PHOTO_COUNT} 张")
    # 生活照允许留空，没有照片时存空值而不是空字符串
    return ",".join(photos) or None


async def _check_payload(payload: dict, keep_tags: List[str] | None = None) -> dict:
    """把页面提交的字段校验一遍，并整理成可以直接写库的字典。"""
    values = {
        "nickname": _required_text(payload, "nickname", "昵称", 100),
        "gender": _required_option(payload, "gender", "性别", GENDERS),
        "birth_date": _check_birth_date(payload),
        "rent_budget": _check_budget(payload),
        "tidiness": _required_option(payload, "tidiness", "整洁度", TIDINESS_LEVELS),
        "occupation": _required_text(payload, "occupation", "职业", 100),
        "lease_term": _required_option(payload, "lease_term", "计划租期", LEASE_TERMS),
        "store_id": _check_store(payload),
        "schedule_type": _required_option(payload, "schedule_type", "作息", SCHEDULE_TYPES),
        "has_pet": _optional_option(payload, "has_pet", "是否养宠", HAS_PET_OPTIONS),
        "smoking": _optional_option(payload, "smoking", "是否吸烟", SMOKING_OPTIONS),
        "self_intro": _required_text(payload, "self_intro", "自我介绍", MAX_INTRO_LENGTH),
        "roommate_expectation": _optional_text(
            payload, "roommate_expectation", "室友期望", MAX_EXPECTATION_LENGTH),
        "interest_tags": await _check_interest_tags(payload, keep_tags),
        "photo_paths": _check_photos(payload),
    }
    return values


def member_dict(member: MemberProfile, user: User | None = None) -> dict:
    """手写转字典：挑字段、格式化时间、按编码拼出门店名和片区。

    年龄是现算的，兴趣标签和生活照拆成数组返回，
    页面拿到就能直接渲染，不用自己再切一次字符串。
    """
    data = {
        "id": member.id,
        "user_id": member.user_id,
        "nickname": member.nickname,
        "gender": member.gender,
        "birth_date": _format_date(member.birth_date),
        "age": calc_age(member.birth_date),
        "rent_budget": member.rent_budget,
        "tidiness": member.tidiness,
        "occupation": member.occupation,
        "lease_term": member.lease_term,
        "store_id": member.store_id,
        "store_name": store_name(member.store_id),
        "area_name": area_name(member.store_id),
        "schedule_type": member.schedule_type,
        "has_pet": member.has_pet,
        "smoking": member.smoking,
        "self_intro": member.self_intro,
        "roommate_expectation": member.roommate_expectation,
        "interest_tags": split_values(member.interest_tags),
        "photo_paths": split_values(member.photo_paths),
        "audit_status": member.audit_status,
        "audit_remark": member.audit_remark,
        "audit_time": format_datetime(member.audit_time),
        "enabled": member.enabled,
        "create_time": format_datetime(member.create_time),
        "update_time": format_datetime(member.update_time),
    }
    if user is not None:
        # 管理端要在列表里同时看到账号和档案，把账号上的几个字段并进来
        data["username"] = user.username
        data["name"] = user.name
        data["avatar"] = user.avatar
    return data


def check_member_role(current_user: User) -> None:
    """确定当前账号是租客身份。

    管理员账号不参与合租匹配，租客档案、动态、合住偏好这些挂在租客身上的东西
    都没有，也不允许凭空造一份出来。
    """
    if current_user.role != "USER":
        raise CustomException("管理员账号不参与合租匹配，请用租客账号登录后再操作", "403")


async def get_my_member(current_user: User, action: str) -> MemberProfile:
    """取当前登录租客的档案。

    action 是这次操作的名称，拼进提示里告诉租客该按什么顺序做：档案是动态、
    偏好这些记录的挂靠点，没有档案就没有地方存。
    """
    check_member_role(current_user)
    member = await MemberProfile.get_or_none(user_id=current_user.id)
    if member is None:
        raise CustomException(f"请先填写并保存租客档案，再来{action}")
    return member


async def get_my_profile(current_user: User) -> dict | None:
    """取当前登录租客的档案，还没填过时返回空，由页面提示去填写。"""
    check_member_role(current_user)
    member = await MemberProfile.get_or_none(user_id=current_user.id)
    return member_dict(member, current_user) if member else None


async def save_my_profile(current_user: User, payload: dict) -> dict:
    """保存当前登录租客的档案，第一次提交就是新建。"""
    check_member_role(current_user)
    member = await MemberProfile.get_or_none(user_id=current_user.id)
    # 已经在用的兴趣标签在管理员把它停用之后仍然允许保留，见 _check_interest_tags
    keep_tags = split_values(member.interest_tags) if member is not None else None
    values = await _check_payload(payload, keep_tags)
    if member is None:
        member = await MemberProfile.create(
            user_id=current_user.id,
            # 新档案一律从待审核开始，管理员审核通过之后才进候选池
            audit_status="待审核",
            **values,
        )
    else:
        old_photos = split_values(member.photo_paths)
        await MemberProfile.filter(id=member.id).update(
            # 档案改动过就退回待审核，上一轮的审核结论和备注不再适用；
            # 审核通过之后换一套内容继续沿用旧结论，等于绕过了审核
            audit_status="待审核",
            audit_remark=None,
            audit_time=None,
            **values,
        )
        # 生活照里被删掉的那几张已经没有记录引用，磁盘文件跟着清，
        # files 目录不会只涨不消
        removed = [url for url in old_photos if url not in split_values(values.get("photo_paths"))]
        file_service.remove(",".join(removed))
        member = await MemberProfile.get(id=member.id)
    return member_dict(member, current_user)


async def audit_member(member_id: int, audit_status: str, audit_remark: str | None) -> None:
    """管理员给出审核结论，写状态、备注和审核时间。"""
    member = await MemberProfile.get_or_none(id=member_id)
    if member is None:
        raise CustomException("未找到这位租客的档案，请刷新列表后重试")
    if audit_status not in AUDIT_RESULTS:
        raise CustomException("审核结论只能在 " + "、".join(AUDIT_RESULTS) + " 里选")
    remark = (audit_remark or "").strip()
    if len(remark) > 500:
        raise CustomException("审核备注最多 500 个字")
    # 驳回必须写原因，租客要照着这条说明改档案；
    # 通过时备注可以留空，也可以写一句说明
    if audit_status == "已驳回" and not remark:
        raise CustomException("驳回时请填写原因，租客要照着这条说明修改档案")
    await MemberProfile.filter(id=member.id).update(
        audit_status=audit_status,
        audit_remark=remark or None,
        audit_time=now(),
    )


async def update_enabled(member_id: int, enabled: str) -> None:
    """启用或停用一份已经审核过的档案。"""
    if enabled not in ENABLED_OPTIONS:
        raise CustomException("启用状态只能是是或否")
    member = await MemberProfile.get_or_none(id=member_id)
    if member is None:
        raise CustomException("未找到这位租客的档案，请刷新列表后重试")
    await MemberProfile.filter(id=member.id).update(enabled=enabled)


async def select_by_id(member_id: int) -> dict:
    member = await MemberProfile.get_or_none(id=member_id)
    if member is None:
        raise CustomException("未找到这位租客的档案，请刷新列表后重试")
    user = await User.get_or_none(id=member.user_id)
    return member_dict(member, user)


async def select_page(nickname: str = "", gender: str = "", store_id: int | None = None,
                      audit_status: str = "", enabled: str = "",
                      page_num: int = 1, page_size: int = 10) -> PageInfo:
    """管理端的租客档案分页查询。"""
    query = MemberProfile.all()
    # 空值时等于不加这个筛选条件
    if nickname:
        query = query.filter(nickname__contains=nickname)
    if gender:
        query = query.filter(gender=gender)
    if store_id:
        query = query.filter(store_id=store_id)
    if audit_status:
        query = query.filter(audit_status=audit_status)
    if enabled:
        query = query.filter(enabled=enabled)
    members = await query.order_by("-id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    # 账号信息一次查回来，列表里不用每条再去查一次
    users = {}
    if members:
        users = {user.id: user for user in await User.filter(id__in=[member.user_id for member in members])}
    return PageInfo(total=total, list=[member_dict(member, users.get(member.user_id)) for member in members])


def list_stores() -> List[dict]:
    """门店下拉框用的清单，带上片区，页面可以按片区分组展示。"""
    return [{"id": store_id, "name": name, "area": STORE_AREA[store_id]}
            for store_id, name in STORE_LIST]


async def list_interest_tags() -> List[dict]:
    """给页面下拉框用的兴趣标签，只返回启用中的，按类目和排序号排列。"""
    tags = await InterestTag.filter(enabled="是").order_by("category", "sort")
    return [
        {"id": tag.id, "name": tag.tag_name, "category": tag.category}
        for tag in tags
    ]
