"""分页参数归一化。

页码和每页条数来自查询字符串，用户/脚本可能传负数、0、超大值或乱七八糟的值。
统一在这里夹到安全范围再拼 offset / limit：

- 负数、0、非数字：页面号退回 1，每页条数退回默认值；
- 超大每页条数：夹到上限（默认 100 条），单请求不能把整表拖走；
- 超大页码：offset = (page_num - 1) * page_size 会超过 MySQL 的 BIGINT 范围，
  接口会落进全局 500，所以页码本身也要设上限。
"""

DEFAULT_PAGE_NUM = 1
DEFAULT_PAGE_SIZE = 10
# 单页最多返回多少条，和前端分页组件的可选值保持一致
MAX_PAGE_SIZE = 100
# 页码上限：offset 最大约 1e8，远小于 BIGINT 上限，不会把 SQL 打成非法值
MAX_PAGE_NUM = 1_000_000


def _to_int(value, fallback: int) -> int:
    """把任意输入转成整数，转不了就用兜底值。"""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def normalize_page(page_num=1, page_size=10, default: int = DEFAULT_PAGE_SIZE,
                   max_size: int = MAX_PAGE_SIZE) -> tuple[int, int]:
    """把页码和每页条数夹到合法范围，返回 (page_num, page_size)。

    default 是每页条数的兜底值，max_size 是这一页最多返回多少条；
    各个列表接口按自己页面上的默认值调用即可，规则只有这一份。
    """
    page_num = _to_int(page_num, DEFAULT_PAGE_NUM)
    page_size = _to_int(page_size, default)
    page_num = max(1, min(page_num, MAX_PAGE_NUM))
    page_size = max(1, min(page_size, max(1, max_size)))
    return page_num, page_size