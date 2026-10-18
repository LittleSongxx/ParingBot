"""文本处理小工具。"""

from typing import List


def split_values(value) -> List[str]:
    """把逗号分隔的字段拆成列表。

    页面提交时可能传数组也可能传字符串，两种都收；空值返回空列表；
    同一个取值重复出现只保留第一次，避免「夜猫子,夜猫子」这种重复值一路带到后面。
    """
    if not value:
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).split(",")
    result: List[str] = []
    for item in items:
        one = str(item).strip()
        if one and one not in result:
            result.append(one)
    return result
