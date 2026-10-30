"""租客动态业务逻辑。

动态是平台了解租客的主要来源：画像师从动态正文里提取生活方式标签，
发起匹配前也会先看这位租客有没有发过动态。所以这里除了让租客发布、修改、
删除自己的动态，还要保证每条动态都能当画像的原始材料用——正文不能空，
删掉配图时磁盘上的文件也要跟着清，不然 files 目录只涨不消。

动态属于租客本人，改和删都按租客编号收窄，拿别人的动态编号来查就是查不到。
"""

from typing import List

from common.exception_handler import CustomException
from common.pagination import normalize_page
from common.result import PageInfo
from common.text import split_values
from common.times import format_datetime, now
from models import MemberMoment, MemberProfile, User
from service import file_service, member_service

# 可见范围。公开的动态会被画像师当作画像材料读取；仅匹配室友可见的只在本人的动态页显示，不进画像材料
VISIBLE_OPTIONS = ("公开", "仅匹配室友可见")
MAX_CONTENT_LENGTH = 500
MAX_IMAGE_COUNT = 9


def moment_dict(moment: MemberMoment) -> dict:
    """手写转字典：配图拆成数组，时间格式化成页面直接能显示的字符串。"""
    return {
        "id": moment.id,
        "member_id": moment.member_id,
        "content": moment.content,
        "image_paths": split_values(moment.image_paths),
        "visible": moment.visible,
        "publish_time": format_datetime(moment.publish_time),
        "create_time": format_datetime(moment.create_time),
        "update_time": format_datetime(moment.update_time),
    }


def _check_content(payload: dict) -> str:
    content = (payload.get("content") or "").strip()
    if not content:
        raise CustomException("请填写动态内容")
    if len(content) > MAX_CONTENT_LENGTH:
        raise CustomException(f"动态内容最多 {MAX_CONTENT_LENGTH} 个字")
    return content


def _check_visible(payload: dict) -> str:
    value = (payload.get("visible") or "公开").strip()
    if value not in VISIBLE_OPTIONS:
        raise CustomException("可见范围只能在 " + "、".join(VISIBLE_OPTIONS) + " 里选")
    return value


def _check_images(payload: dict) -> str | None:
    images = split_values(payload.get("image_paths"))
    if len(images) > MAX_IMAGE_COUNT:
        raise CustomException(f"一条动态最多配 {MAX_IMAGE_COUNT} 张图")
    # 允许只发文字，没有配图时存空值而不是空字符串
    return ",".join(images) or None


def _check_payload(payload: dict) -> dict:
    return {
        "content": _check_content(payload),
        "visible": _check_visible(payload),
        "image_paths": _check_images(payload),
    }


async def _my_moment(member: MemberProfile, moment_id: int) -> MemberMoment:
    """按编号取自己的动态。

    查询条件里带上 member_id，别人的动态编号拿来也查不到，
    不会出现「改地址栏的编号改到别人动态」的情况。
    """
    moment = await MemberMoment.get_or_none(id=moment_id, member_id=member.id)
    if moment is None:
        raise CustomException("未找到这条动态，请刷新列表后重试")
    return moment


async def select_my_page(current_user: User, page_num: int = 1,
                         page_size: int = 10) -> PageInfo:
    """当前租客的动态分页，按发布时间倒序，最新的排在最前面。"""
    member = await member_service.get_my_member(current_user, "查看我的动态")
    page_num, page_size = normalize_page(page_num, page_size)
    query = MemberMoment.filter(member_id=member.id)
    # 同一秒内连着发的两条按编号倒序兜底，顺序才是稳定的
    moments = await query.order_by("-publish_time", "-id").offset(
        (page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(total=total, list=[moment_dict(moment) for moment in moments])


async def publish(current_user: User, payload: dict) -> dict:
    """发布一条动态。"""
    member = await member_service.get_my_member(current_user, "发布动态")
    values = _check_payload(payload)
    moment = await MemberMoment.create(
        member_id=member.id,
        # 发布时间由服务端落，租客不用填；画像按发布时间倒序读动态就是按它排的
        publish_time=now(),
        **values,
    )
    return moment_dict(moment)


async def update(current_user: User, moment_id: int, payload: dict) -> dict:
    """修改自己的一条动态。"""
    member = await member_service.get_my_member(current_user, "修改动态")
    moment = await _my_moment(member, moment_id)
    old_images = split_values(moment.image_paths)
    values = _check_payload(payload)
    # 只改正文、配图和可见范围，发布时间不动：改一下错别字不该把动态挪到今天
    await MemberMoment.filter(id=moment.id).update(**values)
    # 这次删掉的配图已经没有记录引用，磁盘文件跟着清
    removed = [url for url in old_images if url not in split_values(values.get("image_paths"))]
    file_service.remove(",".join(removed))
    return moment_dict(await MemberMoment.get(id=moment.id))


async def remove(current_user: User, moment_id: int) -> None:
    """删除自己的一条动态，配图一并从磁盘上清掉。"""
    member = await member_service.get_my_member(current_user, "删除动态")
    moment = await _my_moment(member, moment_id)
    await MemberMoment.filter(id=moment.id).delete()
    file_service.remove(moment.image_paths)


def list_visible_options() -> List[str]:
    return list(VISIBLE_OPTIONS)
