"""Prompt 加载。

所有发给模型的提示词都从 prompt_template 表读，代码里不写死任何提示词。
取模板时做三项校验：存在、启用、内容非空，任一不满足就报出明确的提示，
不用兜底的硬编码提示词——那会让管理员以为改了模板生效了，实际用的还是代码里那份。

变量填值只替换模板里真正声明过的变量，不做整段字符串格式化：模板里经常带
JSON 示例，那些花括号会被当成占位符，一填就报错。
"""

import re

from common.exception_handler import CustomException
from models import PromptTemplate

# 模板里的占位变量写法是 {变量名}
VARIABLE_PATTERN = re.compile(r"\{(\w+)\}")
# 变量清单要存进 variables 列，列长 500，超了说明这个模板该拆成两个
VARIABLES_MAX_LENGTH = 500


def list_variables(content: str | None) -> list[str]:
    """按出现顺序列出模板里的变量名，重复的只留第一次。

    保存时的变量清单、预览弹窗的输入框都从这里取，两处口径保持一致。
    """
    if not content:
        return []
    # dict.fromkeys 去重的同时保留出现顺序，页面上看到的顺序和模板里一致
    return list(dict.fromkeys(VARIABLE_PATTERN.findall(content)))


def extract_variables(content: str | None) -> str:
    """把变量清单拼成存库的样子，例如「{a} {b}」。

    变量清单由内容自动识别、自动回填，不让管理员手工维护：
    手工维护的清单迟早会和模板内容对不上，而填值时认的是内容。
    """
    return " ".join("{" + name + "}" for name in list_variables(content))


def fill(content: str, values: dict) -> str:
    """把变量值填进模板内容。

    只替换模板里真正声明过的变量，多传的值忽略。模板里有变量没拿到值时拦住：
    模型收到 {context} 这种占位符不会报错，只会照着它编，
    问题要到结果里才看得出来，不如在这里就说清缺哪个变量。
    """
    names = list_variables(content)
    missing = [name for name in names if name not in values]
    if missing:
        raise CustomException(f"模板里这些变量还没有填值：{'、'.join(missing)}")
    result = content
    for name in names:
        value = values[name]
        result = result.replace("{" + name + "}", "" if value is None else str(value))
    return result


async def load(code: str) -> str:
    """按编码取模板内容，做三项校验。"""
    template = await PromptTemplate.get_or_none(code=code)
    if template is None:
        raise CustomException(f"没有找到编码为 {code} 的 Prompt 模板，请先在【Prompt模板】添加")
    if template.enabled != "是":
        raise CustomException(f"Prompt 模板 {code} 已被停用，请先启用")
    if not template.content or not template.content.strip():
        raise CustomException(f"Prompt 模板 {code} 的内容是空的，请先补充内容")
    return template.content


async def render(code: str, **values) -> str:
    """取模板并把变量填进去。

    业务代码要发 Prompt 时走这里：取模板的三项校验和填值一次做完。
    """
    return fill(await load(code), values)
