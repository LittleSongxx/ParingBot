"""日志脱敏。

工具调用日志和步骤记录里会带租客原文，里面可能混着手机号、邮箱、身份证号这类
个人信息。写库前统一过这一遍，把 PII 打码：排查问题时仍然看得出「这里有值、格式
是手机号」，但翻日志或拖库不会把原文直接带出去。
"""

import re

# 打码后保留的位数：手机号留前 3 后 4，身份证留前 3 后 4，邮箱只留首字符
_MASK = "****"

# 身份证号（18 位，末位可能是 X）和手机号都要求前后不是数字，
# 否则订单号、时间戳里恰好凑出的 11/18 位数字会被误伤
_ID_PATTERN = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
_PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_EMAIL_PATTERN = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def _mask_id(match: re.Match) -> str:
    value = match.group(1)
    return value[:3] + "*" * 11 + value[-4:]


def _mask_phone(match: re.Match) -> str:
    value = match.group(1)
    return value[:3] + _MASK + value[-4:]


def _mask_email(match: re.Match) -> str:
    name, domain = match.group(1), match.group(2)
    return (name[0] if name else "*") + "***@" + domain


def redact_text(value: str | None) -> str | None:
    """把文本里的手机号/邮箱/身份证号打码；None 原样返回，其它类型转成字符串。"""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    if not value:
        return value
    # 先处理身份证：它的位数更长，先打码不会留下能被手机号规则命中的数字段
    text = _ID_PATTERN.sub(_mask_id, value)
    text = _PHONE_PATTERN.sub(_mask_phone, text)
    return _EMAIL_PATTERN.sub(_mask_email, text)