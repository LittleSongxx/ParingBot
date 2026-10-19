"""兴趣标签词表业务逻辑。

词表是画像师给租客打标签、筛选官按兴趣检索候选共用的取值来源，模型不许自造
标签，所以这张表只由管理员维护。

词表一改，已经用了标签的租客档案就跟着受影响：删掉一个正在被使用的标签，
租客档案里那个词就成了词表外的取值，画像师和筛选官都认不了它，页面回填时
既选不中又改不掉。所以删除和改名都要先看有没有人在用，有人在用就拦住，
让管理员改成「停用」——停用只影响新档案能不能选到它。
"""

from typing import List

from common.exception_handler import CustomException
from common.result import PageInfo
from common.text import split_values
from common.times import format_datetime
from models import InterestTag, MemberProfile

# 八个类目固定，模型和页面都从这里取
CATEGORIES = ("运动", "影音", "美食", "旅行", "宠物", "阅读", "游戏", "艺术")
ENABLED_OPTIONS = ("是", "否")
MAX_TAG_LENGTH = 50
MAX_SORT = 999


def tag_dict(tag: InterestTag, used_count: int = 0) -> dict:
    """手写转字典，附带有多少位租客在用这个标签。

    使用人数是页面判断「这条能不能删、能不能改名」的依据，
    没有它的管理员只能靠点一下试试看。
    """
    return {
        "id": tag.id,
        "tag_name": tag.tag_name,
        "category": tag.category,
        "enabled": tag.enabled,
        "sort": tag.sort,
        "used_count": used_count,
        "create_time": format_datetime(tag.create_time),
        "update_time": format_datetime(tag.update_time),
    }


async def _usage_map() -> dict:
    """每个标签各被多少位租客的档案用着。

    租客档案的兴趣标签是逗号分隔的一列，这里把整列取回来在内存里数。
    不用 LIKE 拼条件是因为「跑步」和「跑步机」这种前缀相同的标签会互相误伤。
    """
    counts: dict = {}
    values = await MemberProfile.all().values_list("interest_tags", flat=True)
    for value in values:
        for tag_name in split_values(value):
            counts[tag_name] = counts.get(tag_name, 0) + 1
    return counts


async def _used_by_members(tag_name: str) -> int:
    """单个标签的使用人数。先用 LIKE 收窄再从内存里精确比对，避免误伤前缀相同的词。"""
    values = await MemberProfile.filter(
        interest_tags__contains=tag_name).values_list("interest_tags", flat=True)
    return sum(1 for value in values if tag_name in split_values(value))


def _check_tag_name(payload: dict) -> str:
    value = (payload.get("tag_name") or "").strip()
    if not value:
        raise CustomException("请填写标签名")
    if len(value) > MAX_TAG_LENGTH:
        raise CustomException(f"标签名最多 {MAX_TAG_LENGTH} 个字")
    return value


def _check_category(payload: dict) -> str:
    value = (payload.get("category") or "").strip()
    if not value:
        raise CustomException("请选择标签类目")
    if value not in CATEGORIES:
        raise CustomException("标签类目只能在 " + "、".join(CATEGORIES) + " 里选")
    return value


def _check_enabled(payload: dict) -> str:
    value = (payload.get("enabled") or "是").strip()
    if value not in ENABLED_OPTIONS:
        raise CustomException("启用状态只能是是或否")
    return value


def _check_sort(payload: dict) -> int:
    value = payload.get("sort")
    # 排序号可以不填，不填按 0 处理
    if value in (None, ""):
        return 0
    try:
        sort = int(value)
    except (TypeError, ValueError):
        raise CustomException("排序号请填整数")
    if sort < 0 or sort > MAX_SORT:
        raise CustomException(f"排序号请填 0 到 {MAX_SORT} 之间的整数")
    return sort


async def select_page(tag_name: str = "", category: str = "", enabled: str = "",
                      page_num: int = 1, page_size: int = 10) -> PageInfo:
    """管理端的标签分页查询。

    按录入顺序排：词表是一批批加进来的，同类的标签天然挨在一起，
    管理员翻页时看到的就是一份整理好的字典。
    """
    query = InterestTag.all()
    if tag_name:
        query = query.filter(tag_name__contains=tag_name)
    if category:
        query = query.filter(category=category)
    if enabled:
        query = query.filter(enabled=enabled)
    tags = await query.order_by("id").offset((page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    # 使用人数整表数一次就够，不用每条标签再查一遍
    counts = await _usage_map() if tags else {}
    return PageInfo(
        total=total, list=[tag_dict(tag, counts.get(tag.tag_name, 0)) for tag in tags])


async def add(payload: dict) -> None:
    tag_name = _check_tag_name(payload)
    if await InterestTag.get_or_none(tag_name=tag_name):
        raise CustomException(f"标签「{tag_name}」已经在词表里了，直接改那一条就行")
    await InterestTag.create(
        tag_name=tag_name,
        category=_check_category(payload),
        enabled=_check_enabled(payload),
        sort=_check_sort(payload),
    )


async def update(tag_id: int, payload: dict) -> None:
    tag = await InterestTag.get_or_none(id=tag_id)
    if tag is None:
        raise CustomException("未找到这个标签，请刷新列表后重试")
    tag_name = _check_tag_name(payload)
    category = _check_category(payload)
    # 改名和换类目会让已经用了它的租客档案对不上词表，有人在用就先拦住
    if tag_name != tag.tag_name or category != tag.category:
        used = await _used_by_members(tag.tag_name)
        if used:
            raise CustomException(
                f"已有 {used} 位租客的档案用了「{tag.tag_name}」，改名或换类目会让他们的标签对不上词表；"
                f"要调整请新增一个标签，再把这一条停用")
    duplicate = await InterestTag.get_or_none(tag_name=tag_name)
    if duplicate is not None and duplicate.id != tag.id:
        raise CustomException(f"标签「{tag_name}」已经在词表里了")
    await InterestTag.filter(id=tag.id).update(
        tag_name=tag_name,
        category=category,
        enabled=_check_enabled(payload),
        sort=_check_sort(payload),
    )


async def _check_removable(tag: InterestTag) -> None:
    """被租客档案引用的标签不许删，只能停用。"""
    used = await _used_by_members(tag.tag_name)
    if used:
        raise CustomException(
            f"已有 {used} 位租客的档案用了「{tag.tag_name}」，删掉之后他们的标签就不在词表里了；"
            f"请改为停用，停用之后新档案不会再选到它")


async def remove(tag_id: int) -> None:
    tag = await InterestTag.get_or_none(id=tag_id)
    if tag is None:
        raise CustomException("未找到这个标签，请刷新列表后重试")
    await _check_removable(tag)
    await InterestTag.filter(id=tag.id).delete()


async def remove_batch(ids: List[int]) -> None:
    tags = await InterestTag.filter(id__in=ids)
    # 先整批校验、再整批删：删到一半被拦下来会让人看不出这次到底删成功了没有
    for tag in tags:
        await _check_removable(tag)
    await InterestTag.filter(id__in=[tag.id for tag in tags]).delete()


async def update_enabled(tag_id: int, enabled: str) -> None:
    """停用或启用一个标签。停用不影响已经在用的租客档案，只影响新档案能不能选到它。"""
    if enabled not in ENABLED_OPTIONS:
        raise CustomException("启用状态只能是是或否")
    tag = await InterestTag.get_or_none(id=tag_id)
    if tag is None:
        raise CustomException("未找到这个标签，请刷新列表后重试")
    await InterestTag.filter(id=tag.id).update(enabled=enabled)


def list_categories() -> List[str]:
    return list(CATEGORIES)
