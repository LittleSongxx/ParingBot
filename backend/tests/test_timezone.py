"""时间口径测试。

页面上所有时间都按东八区显示，这里盯住三件事：
写进去的时刻读回来还是页面上看到的那个点、ORM 自动写入的时间落在东八区的今天、
以及两个取值函数没有跑偏。

涉及数据库的用例直接跑在开发库上，用的就是 settings.py 里的那份配置，
造出来的运行记录编号带「单元测试专用」后缀，跑完由 conftest 的清扫夹具回收。
"""

import unittest
from datetime import datetime

from common.times import LOCAL_TZ, cost_millis, format_datetime, now, precise_now
from models import AgentRun

# 这三条运行记录跑完会被清扫夹具删掉
TEST_MARK = "单元测试专用"
EXPLICIT_NO = f"TZ-EXPLICIT-{TEST_MARK}"
AUTO_NO = f"TZ-AUTO-{TEST_MARK}"
ROUND_TRIP_NO = f"TZ-ROUND-{TEST_MARK}"


class TimezoneFormatTest(unittest.TestCase):
    """不依赖数据库的纯格式化用例。"""

    def test_format_datetime_renders_local_time(self):
        self.assertEqual(format_datetime(datetime(2026, 3, 5, 23, 59, 59, tzinfo=LOCAL_TZ)), "2026-03-05 23:59:59")
        self.assertIsNone(format_datetime(None))

    def test_now_and_cost_millis_use_the_same_clock(self):
        """now() 带东八区偏移，cost_millis 用同一个时钟算差值。"""
        started = now()
        self.assertGreaterEqual(cost_millis(started), 0)
        self.assertEqual(started.utcoffset(), LOCAL_TZ.utcoffset(None))

    def test_now_keeps_whole_seconds(self):
        """now() 只到秒。

        库里的时间列是秒精度，带微秒的值写进去会被四舍五入，
        内存里的时刻和取出来的时刻就差一秒。
        """
        self.assertEqual(now().microsecond, 0)
        self.assertGreaterEqual(precise_now().microsecond, 0)


async def test_explicit_time_reads_back_as_the_moment_it_was_written(db):
    """写进去的时刻读回来还是那个点。"""
    await AgentRun.create(run_no=EXPLICIT_NO, start_time=datetime(2026, 3, 5, 18, 30, 0, tzinfo=LOCAL_TZ))
    run = await AgentRun.get(run_no=EXPLICIT_NO)
    assert format_datetime(run.start_time) == "2026-03-05 18:30:00"


async def test_orm_generated_time_is_local_today(db):
    """ORM 自动写入的时间落在东八区的今天，不是早八个小时的昨天。"""
    await AgentRun.create(run_no=AUTO_NO)
    run = await AgentRun.get(run_no=AUTO_NO)
    assert format_datetime(run.create_time)[:10] == now().strftime("%Y-%m-%d")


async def test_now_reads_back_as_the_moment_it_was_written(db):
    """用 now() 落的时间，读回来和写进去的一模一样。"""
    written = now()
    await AgentRun.create(run_no=ROUND_TRIP_NO, start_time=written)
    run = await AgentRun.get(run_no=ROUND_TRIP_NO)
    assert format_datetime(run.start_time) == format_datetime(written)
