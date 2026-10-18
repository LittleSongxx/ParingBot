"""时间工具。

全项目只在这一处取当前时间：写业务时间列、算耗时都走这里，
不要在业务代码里直接 datetime.now()——那样拿到的是不带时区的裸时间，
写进 DatetimeField 会和 settings.py 里配的时区对不上。
"""

from datetime import datetime, timedelta, timezone

# 东八区。和 settings.py 里 TORTOISE_ORM 的 timezone 保持一致
LOCAL_TZ = timezone(timedelta(hours=8))


def now() -> datetime:
    """带时区的当前时间，精确到秒，可直接写进 DatetimeField。

    库里的时间列都是秒精度，带微秒的值写进去会被四舍五入，
    于是内存里的值和取出来的值能差一秒。这里直接取整到秒，
    写进去的和读出来的就完全一致。
    """
    return datetime.now(LOCAL_TZ).replace(microsecond=0)


def precise_now() -> datetime:
    """带时区的当前时间，保留微秒。

    只用来给测耗时打起点，不要写进时间列——写进去会被取整。
    """
    return datetime.now(LOCAL_TZ)


def cost_millis(started: datetime) -> int:
    """从 started 到现在经过的毫秒数，写进各类记录表的 cost_millis 列。

    起点要用 precise_now() 打；拿秒精度的时间当起点会多算最多一秒。
    """
    return int((precise_now() - started).total_seconds() * 1000)


def to_local(value: datetime) -> datetime:
    """把取出来的时间统一换算到东八区。

    ORM 取回来的值可能带时区（存的时候带了）也可能不带（SQLite 等场景），
    这里统一处理，页面格式化时不用再判断。
    """
    return value.replace(tzinfo=LOCAL_TZ) if value.tzinfo is None else value.astimezone(LOCAL_TZ)


def format_datetime(value: datetime | None) -> str | None:
    """格式化给前端展示的时间字符串，空值原样返回空。"""
    return to_local(value).strftime("%Y-%m-%d %H:%M:%S") if value else None
