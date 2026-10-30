"""AI 模型配置业务逻辑。

全项目的大模型都按这张表的配置构建，页面上改完立刻生效，不用重启服务。
这一页管四件事：

1. 用途只有调度、画像、筛选、审核四个，一个用途对应一个 Agent 角色。
2. 一个用途只允许有一条启用中的配置。匹配链路按用途取模型，
   同用途留下两条启用，取到哪一条就成了碰运气。
3. 密钥不明文回到页面上。列表和弹窗里给的都是脱敏串，管理员靠头尾能认出是哪把，
   而整串密钥不会落进浏览器缓存。没重新输入时提交回来的是脱敏串，不能拿它覆盖真密钥。
4. 温度和最大输出 Token 可以留空，留空就用服务端的默认值。
"""

from decimal import ROUND_HALF_UP, Decimal

from ai import model_factory
from common.exception_handler import CustomException
from common.pagination import normalize_page
from common.result import PageInfo
from common.times import format_datetime
from models import AiModelConfig

YES_NO_OPTIONS = ("是", "否")
MAX_NAME_LENGTH = 255
MAX_MODEL_NAME_LENGTH = 255
MAX_URL_LENGTH = 500
MAX_KEY_LENGTH = 500
MAX_REMARK_LENGTH = 500
TEMPERATURE_MAX = 2
MAX_TOKENS_MAX = 32768
# 密钥脱敏：留前 4 位和后 4 位，中间固定八个星号
MASK_HEAD = 4
MASK_TAIL = 4
MASK_STARS = 8


def mask_api_key(api_key: str | None) -> str:
    """把密钥变成可以放到页面上的样子。

    只留前 4 位和后 4 位：管理员靠头尾就能认出这是哪把密钥，
    而完整密钥不出现在接口返回里，也不会被浏览器缓存下来。
    """
    if not api_key:
        return ""
    if len(api_key) <= MASK_HEAD + MASK_TAIL:
        return "*" * len(api_key)
    return api_key[:MASK_HEAD] + "*" * MASK_STARS + api_key[-MASK_TAIL:]


def config_dict(config: AiModelConfig) -> dict:
    return {
        "id": config.id,
        "name": config.name,
        "model_purpose": config.model_purpose,
        "provider": config.provider,
        "base_url": config.base_url,
        # 这里给的是脱敏串，真密钥不出后端
        "api_key": mask_api_key(config.api_key),
        "model_name": config.model_name,
        # 列是 Decimal，直接发到页面上会变成字符串，输入框回填时显示不出来，
        # 所以转成数字再发
        "temperature": float(config.temperature) if config.temperature is not None else None,
        "max_tokens": config.max_tokens,
        "enabled": config.enabled,
        "remark": config.remark,
        "update_time": format_datetime(config.update_time),
    }


def purpose_options() -> list:
    """用途下拉里的选项，一个用途对应一个 Agent 角色。"""
    return list(model_factory.PURPOSES)


def _check_text(raw, field_name: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise CustomException(f"请填写{field_name}")
    return value


def _check_purpose(raw) -> str:
    purpose = str(raw or "").strip()
    if purpose not in model_factory.PURPOSES:
        raise CustomException(f"模型用途请选：{'、'.join(model_factory.PURPOSES)}")
    return purpose


def _check_enabled(raw) -> str:
    enabled = str(raw or "").strip()
    if enabled not in YES_NO_OPTIONS:
        raise CustomException("启用状态只能是是或否")
    return enabled


def _check_base_url(raw) -> str:
    base_url = _check_text(raw, "接口地址")
    if len(base_url) > MAX_URL_LENGTH:
        raise CustomException(f"接口地址最多 {MAX_URL_LENGTH} 个字符")
    # 少写协议头是最常见的一种填错，模型 SDK 拿到之后报的错看不出来是这里的问题
    if not base_url.startswith(("http://", "https://")):
        raise CustomException(
            "接口地址要以 http:// 或 https:// 开头，例如 https://api.deepseek.com/v1")
    return base_url


def _check_temperature(raw) -> Decimal | None:
    """温度可以留空，留空就用服务端的默认值。"""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        raise CustomException("温度请填 0 到 2 之间的数字，留空表示用服务端默认值")
    if number < 0 or number > TEMPERATURE_MAX:
        raise CustomException("温度请填 0 到 2 之间的数字，留空表示用服务端默认值")
    # 列是 decimal(4,2)，这里先按两位小数收一下，免得存进去被数据库悄悄截断
    return Decimal(str(number)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _check_max_tokens(raw) -> int | None:
    """最大输出 Token 可以留空，留空就用服务端的默认值。"""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        raise CustomException(
            f"最大输出 Token 请填 1 到 {MAX_TOKENS_MAX} 之间的整数，留空表示用服务端默认值")
    if number < 1 or number > MAX_TOKENS_MAX:
        raise CustomException(
            f"最大输出 Token 请填 1 到 {MAX_TOKENS_MAX} 之间的整数，留空表示用服务端默认值")
    return number


async def _validate(payload: dict, config_id: int | None) -> tuple[dict, str]:
    """校验一份模型配置，返回可以写库的字段和用户填的密钥。

    密钥单独返回：新增时用它写库，修改时还要判断页面上交回来的是不是一个脱敏串。
    """
    purpose = _check_purpose(payload.get("model_purpose"))
    name = _check_text(payload.get("name"), "配置名称")
    if len(name) > MAX_NAME_LENGTH:
        raise CustomException(f"配置名称最多 {MAX_NAME_LENGTH} 个字符")
    duplicate = AiModelConfig.filter(name=name)
    if config_id is not None:
        duplicate = duplicate.exclude(id=config_id)
    if await duplicate.exists():
        raise CustomException(f"已经有一条叫「{name}」的配置了，配置名称不能重复")
    model_name = _check_text(payload.get("model_name"), "模型名称")
    if len(model_name) > MAX_MODEL_NAME_LENGTH:
        raise CustomException(f"模型名称最多 {MAX_MODEL_NAME_LENGTH} 个字符")
    api_key = str(payload.get("api_key") or "").strip()
    if len(api_key) > MAX_KEY_LENGTH:
        raise CustomException(f"API Key 最多 {MAX_KEY_LENGTH} 个字符")
    remark = str(payload.get("remark") or "").strip()
    if len(remark) > MAX_REMARK_LENGTH:
        raise CustomException(f"备注最多 {MAX_REMARK_LENGTH} 个字符")
    values = {
        "name": name,
        "model_purpose": purpose,
        "provider": str(payload.get("provider") or "").strip() or None,
        "base_url": _check_base_url(payload.get("base_url")),
        "model_name": model_name,
        "enabled": _check_enabled(payload.get("enabled")),
        "remark": remark or None,
        "temperature": _check_temperature(payload.get("temperature")),
        "max_tokens": _check_max_tokens(payload.get("max_tokens")),
    }
    return values, api_key


async def _get(config_id: int | None) -> AiModelConfig:
    config = await AiModelConfig.get_or_none(id=config_id)
    if config is None:
        raise CustomException("未找到这条模型配置，请刷新列表后重试")
    return config


async def _clear_other_enabled(purpose: str, keep_id: int | None = None) -> None:
    """一个用途只留一条启用中的配置。

    启用一条时把同用途的其它条停掉，「画像用哪条模型」在页面上就永远只有一个答案，
    取配置的代码也不会取到一条管理员没打算用的。
    """
    query = AiModelConfig.filter(model_purpose=purpose, enabled="是")
    if keep_id is not None:
        query = query.exclude(id=keep_id)
    await query.update(enabled="否")


async def select_page(name: str = "", model_purpose: str = "",
                      enabled: str = "", page_num: int = 1, page_size: int = 10) -> PageInfo:
    """管理端的配置分页查询。"""
    page_num, page_size = normalize_page(page_num, page_size)
    query = AiModelConfig.all()
    if name:
        query = query.filter(name__contains=name)
    if model_purpose:
        query = query.filter(model_purpose=model_purpose)
    if enabled:
        query = query.filter(enabled=enabled)
    configs = await query.order_by("id").offset(
        (page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    return PageInfo(total=total, list=[config_dict(item) for item in configs])


async def add(payload: dict) -> None:
    """新增一条配置。

    新增的配置默认是停用的：启用会顶掉同用途原来那条，得让管理员确认之后再点启用。
    """
    values, api_key = await _validate(payload, None)
    if values["enabled"] == "是":
        await _clear_other_enabled(values["model_purpose"])
    await AiModelConfig.create(api_key=api_key or None, **values)


async def update(config_id: int | None, payload: dict) -> None:
    config = await _get(config_id)
    values, api_key = await _validate(payload, config.id)
    # 弹窗里回填的是脱敏串，没重新输入密钥时提交回来的还是这串星号，
    # 拿它覆盖会把真密钥冲掉，所以只有填了新值才更新密钥列
    if api_key and "*" not in api_key:
        values["api_key"] = api_key
    if values["enabled"] == "是":
        await _clear_other_enabled(values["model_purpose"], keep_id=config.id)
    await AiModelConfig.filter(id=config.id).update(**values)


async def update_enabled(config_id: int, enabled: str) -> None:
    """启用或停用一条配置。启用时同用途原来那条自动停用。"""
    config = await _get(config_id)
    value = _check_enabled(enabled)
    if value == "是":
        await _clear_other_enabled(config.model_purpose, keep_id=config.id)
    await AiModelConfig.filter(id=config.id).update(enabled=value)


async def remove(config_id: int) -> None:
    """删除一条配置。

    启用中的配置正被链路使用，直接删掉会让那个用途当场没有可用模型，
    而且报错的地方离这儿很远。所以先让管理员停用，或者先把别的配置启用到这个用途上。
    """
    config = await _get(config_id)
    if config.enabled == "是":
        raise CustomException(
            f"「{config.name}」正在被「{config.model_purpose}」用途使用，删掉之后这一步就没有可用模型了。"
            f"请先停用它，或者先把别的配置启用到这个用途上，再回来删除")
    await AiModelConfig.filter(id=config.id).delete()


async def test_connection(config_id: int) -> str:
    """连通性测试，用库里保存的配置真实调一次模型。

    让模型回一个字，能拿到正常响应就说明地址、密钥、模型名都对。
    """
    config = await _get(config_id)
    return await model_factory.test_connection(config)
