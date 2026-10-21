"""模型工厂。

四个 Agent 角色用的对话模型都从这里构造，配置一律从 ai_model_config 表里读，
改密钥、换模型在【AI模型配置】页面上点一下立刻生效，代码里不写死地址和密钥。

取配置有两条规矩：

    按用途取   一条用途只允许有一条启用中的配置，链路每次调用都按用途现取，
               管理员停用或换模型都不用重启服务
    取不到就拦  用途下没有启用中的配置、配置里缺密钥或模型名称，
               在请求发出去之前就报出来并说清去哪补，
               不让它跑到接口那里变成一句看不懂的英文报错
"""

from langchain_openai import ChatOpenAI

from common.exception_handler import CustomException
from models import AiModelConfig

# ai_model_config.model_purpose 的取值，一个用途对应一个 Agent 角色。
# 按用途取模型时用这几个常量，页面上「模型用途」下拉里能选的也是它们
PURPOSE_SCHEDULE = "调度"
PURPOSE_PORTRAIT = "画像"
PURPOSE_SCREEN = "筛选"
PURPOSE_AUDIT = "审核"
PURPOSES = (PURPOSE_SCHEDULE, PURPOSE_PORTRAIT, PURPOSE_SCREEN, PURPOSE_AUDIT)

# 单次请求的超时与重试次数：偶发一次网络抖动不该让整条链路当场失败
REQUEST_TIMEOUT = 60
MAX_RETRIES = 2


async def load_for_purpose(purpose: str) -> AiModelConfig:
    """按用途取那条启用中的配置。

    同一个用途可能存过好几条，只允许一条启用，所以这里取到的一定是管理员
    当前打算用的那条；没有启用的、或者配置里缺必填项，都在这里拦下来。
    """
    config = await AiModelConfig.filter(
        model_purpose=purpose, enabled="是").order_by("-id").first()
    if config is None:
        raise CustomException(
            f"平台还没有启用「{purpose}」用途的模型配置，请先到【AI模型配置】为它启用一条")
    if not config.api_key:
        raise CustomException(
            f"「{config.name}」还没有填写 API Key，请先到【AI模型配置】补上")
    if not config.model_name:
        raise CustomException(
            f"「{config.name}」还没有填写模型名称，请先到【AI模型配置】补上")
    return config


def build_chat_model(config: AiModelConfig, temperature: float = 0.0) -> ChatOpenAI:
    """构造对话模型。

    温度默认给 0：主管派单、筛选、审核这些活都要求同一个输入给出一致的结论，
    重复跑两次不该给出两套结果。页面上给这条配置单独填过温度和最大输出 Token 时
    以页面填的为准，页面上留空才落到这里的默认值。
    """
    return ChatOpenAI(
        model=config.model_name,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=float(config.temperature) if config.temperature is not None else temperature,
        # 最大输出 Token 要真下发给模型，页面上填的数才有意义；
        # 输出被截断时 check_truncated 提示的就是去改这一项
        max_tokens=config.max_tokens or None,
        timeout=REQUEST_TIMEOUT,
        max_retries=MAX_RETRIES,
    )


def check_truncated(response) -> None:
    """输出被最大长度截断时直接报出来。

    模型写到一个上限就被砍断，半截 JSON 解析出来的结论不能用。
    与其等解析失败报一句看不懂的错，不如在这里说清该去哪把上限调大。
    """
    metadata = getattr(response, "response_metadata", None) or {}
    if metadata.get("finish_reason") == "length":
        raise CustomException(
            "模型输出超过了最大长度被截断。请到【AI模型配置】调大最大输出 Token，"
            "或者缩短输入内容后重试"
        )


def translate_exception(exc: Exception) -> str:
    """把 SDK 抛出的异常翻译成人话，并说清该去哪处理。

    各家服务商的报错都是自己的英文原文，直接显示到页面上用户看不懂，
    也看不出下一步该做什么，所以这里按关键词分成几类，每类给一句能照做的提示。
    认不出类别的也给一句统一的处理办法，不把原文甩到页面上。
    """
    lowered = str(exc).lower()
    if ("insufficient" in lowered or "quota" in lowered
            or "balance" in lowered or "402" in lowered):
        return "模型服务的余额或额度不足，请到【AI模型配置】确认这个用途用的模型账户还能不能调用"
    if "rate limit" in lowered or "429" in lowered:
        return "模型服务提示请求过于频繁被限流，请稍后重试；持续出现请到【AI模型配置】换一个模型"
    if "api key" in lowered or "401" in lowered or "invalid_api_key" in lowered:
        return "API Key 无效或已过期，请到【AI模型配置】重新填写并保存"
    if "not found" in lowered or "404" in lowered:
        return "模型名称或接口地址不存在，请到【AI模型配置】检查配置"
    if "timeout" in lowered or "timed out" in lowered:
        return "模型服务响应超时，请检查网络后重试；持续超时请到【AI模型配置】换一个模型"
    if "connect" in lowered:
        return "连不上接口地址，请到【AI模型配置】检查接口地址和本机网络"
    # 认不出具体类别时给一句统一的处理办法：先核配置，再看模型服务本身是否可用，
    # 最后才让人把这次操作交给管理员
    return ("模型调用没有成功，请先到【AI模型配置】核对接入地址、API Key 和模型名称，"
            "确认模型服务本身可用后重试；如果一直失败，请把这次操作告诉管理员")


async def test_connection(config: AiModelConfig) -> str:
    """连通性测试。

    发一次最小请求，能拿到正常响应就说明地址、密钥、模型名都对。
    """
    if not config.api_key:
        raise CustomException("请先填写 API Key")
    if not config.model_name:
        raise CustomException("请先填写模型名称")
    try:
        model = build_chat_model(config)
        # 只让模型回一个字，把这次测试的成本压到最低
        reply = await model.ainvoke("回复一个字：好")
        return f"模型连通正常，返回：{str(reply.content)[:50]}"
    except CustomException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CustomException(translate_exception(exc))
