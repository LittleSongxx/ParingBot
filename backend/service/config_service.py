"""系统参数业务逻辑。

调度轮数上限、单角色工具调用上限、放宽次数上限、单次交付人数这些闸门全部是
这里的参数，管理员在页面上改完立刻生效，调参数不用改代码也不用重启。

参数由代码按参数编码读取，所以这一页只让改参数值和启用状态，不让增删参数：
新增一个参数没有代码读它，删掉一个参数会在读它的地方变成空值，两种都比不改更糟。
参数值一律按值类型校验——整数型参数填成一句话，读取处只会当成没配，
配置就这么悄悄失效了，所以宁可在这里拦住并说清该填什么。
"""

from tortoise.expressions import Q

from common.exception_handler import CustomException
from common.pagination import normalize_page
from common.result import PageInfo
from common.times import format_datetime
from models import SysConfig

YES_NO_OPTIONS = ("是", "否")
MAX_VALUE_LENGTH = 500
# 整数型参数的上限。这些参数是轮数、次数、条数一类的小数字，
# 填成六位数以上基本是敲错了，拦住让他确认
MAX_INT_VALUE = 1000000


def config_dict(config: SysConfig) -> dict:
    return {
        "id": config.id,
        "config_key": config.config_key,
        "config_name": config.config_name,
        "config_value": config.config_value,
        "value_type": config.value_type,
        "remark": config.remark,
        "enabled": config.enabled,
        "update_time": format_datetime(config.update_time),
    }


def _check_enabled(enabled: str) -> str:
    if enabled not in YES_NO_OPTIONS:
        raise CustomException("启用状态只能是是或否")
    return enabled


def _check_value(config: SysConfig, raw) -> str:
    """按值类型校验参数值，通过之后返回归一化后的字符串。"""
    if raw is None or str(raw).strip() == "":
        raise CustomException(f"请填写「{config.config_name}」的参数值")
    value = str(raw).strip()
    if len(value) > MAX_VALUE_LENGTH:
        raise CustomException(f"参数值最多 {MAX_VALUE_LENGTH} 个字符")
    if config.value_type == "整数":
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise CustomException(
                f"「{config.config_name}」是整数型参数，参数值请填整数")
        if number < 0 or number > MAX_INT_VALUE:
            raise CustomException(
                f"「{config.config_name}」请填 0 到 {MAX_INT_VALUE} 之间的整数")
        # 存归一化之后的写法，免得「008」这种值后面按字符串比较时对不上
        return str(number)
    if config.value_type == "小数":
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise CustomException(
                f"「{config.config_name}」是小数型参数，参数值请填数字")
        if number < 0:
            raise CustomException(f"「{config.config_name}」请填不小于 0 的数字")
        return str(number)
    return value


async def get_value(config_key: str, default: str = "") -> str:
    """按参数编码读参数值，给其它模块用。

    参数被停用、值被清空、库里根本没有这条参数时，都返回调用方给的默认值：
    读参数的代码不该因为一个参数没配就整条链路出错，
    而管理员停用参数本来就是想让它退回默认值。
    """
    config = await SysConfig.get_or_none(config_key=config_key, enabled="是")
    value = (config.config_value or "").strip() if config else ""
    return value or default


async def get_int(config_key: str, default: int) -> int:
    """按参数编码读一个整数型参数，给其它模块算闸门用。

    轮数上限、次数上限、条数上限这一类参数都走这里。管理员把值填成一句话、
    或者把参数停用了，读它的功能就退回程序里的默认值继续跑，
    不会把读出来的字符串当成数字用——那种错误要到算轮数的时候才炸，离现场已经很远。
    填 0 或负数一律按没填处理，这些参数是「最多几次」，0 次不是一个有意义的配置。
    """
    raw = await get_value(config_key, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


async def select_page(keyword: str = "", enabled: str = "",
                      page_num: int = 1, page_size: int = 10) -> PageInfo:
    """管理端的参数分页查询。

    关键词同时匹参数编码和参数名称：管理员记得住名字还是编码不一定，
    只按一个查会让他先自己确认到底记住的是哪个。
    """
    page_num, page_size = normalize_page(page_num, page_size)
    query = SysConfig.all()
    if keyword:
        query = query.filter(
            Q(config_key__contains=keyword) | Q(config_name__contains=keyword))
    if enabled:
        query = query.filter(enabled=enabled)
    configs = await query.order_by("id").offset(
        (page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(total=total, list=[config_dict(config) for config in configs])


async def update(config_id: int | None, payload: dict) -> None:
    """改参数值和启用状态。参数编码、名称、值类型由代码和初始化数据固定，改不了。"""
    config = await SysConfig.get_or_none(id=config_id)
    if config is None:
        raise CustomException("未找到这个参数，请刷新列表后重试")
    values = {}
    if "config_value" in payload:
        values["config_value"] = _check_value(config, payload.get("config_value"))
    if payload.get("enabled") is not None:
        values["enabled"] = _check_enabled(str(payload.get("enabled")))
    if not values:
        raise CustomException("没有要改的内容")
    await SysConfig.filter(id=config.id).update(**values)


async def update_enabled(config_id: int, enabled: str) -> None:
    """停用或启用一个参数。

    停用之后这个参数不生效，用它的功能会退回程序里的默认值，
    这样调参出问题时有一个「先关掉」的回退手段，不用把值改回去。
    """
    value = _check_enabled(enabled)
    config = await SysConfig.get_or_none(id=config_id)
    if config is None:
        raise CustomException("未找到这个参数，请刷新列表后重试")
    await SysConfig.filter(id=config.id).update(enabled=value)
