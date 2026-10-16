"""检索客户端必须固定在专用事件循环上（跨循环复用会 RuntimeError: Event loop is closed）。

回归背景（2026-10-16 审计）：客户端在 lifespan 主循环里创建、检索却在 to_thread 工作线程的
新循环里使用，实测每次检索都抛 "Event loop is closed" → 两个后端连续失败 → 健康度进入跳过
窗口 → 检索平面永久退化为内存 BM25。修法：所有检索协程经 hybrid_search.run_sync 提交到
一条常驻的检索专用循环。

本用例不需要真 ES/Qdrant：未配置时 es_client()/qdrant_client() 返回 None，
用 runtime.env 里的地址存在性决定是否做"真后端"断言。
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import unittest

from smartlect import hybrid_search


def _load_runtime_env() -> None:
    """把 run/runtime.env 的 SMARTLECT_* 注入环境（本地端口是 6333→16333 这类映射值，
    不能靠 hybrid_search 里的默认端口，否则会连到别的项目上）。"""
    env_file = pathlib.Path(__file__).resolve().parents[2] / "run" / "runtime.env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        if line.startswith("SMARTLECT_") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)


def _es_configured() -> bool:
    _load_runtime_env()
    return bool((os.environ.get("SMARTLECT_ES_URL") or "").strip())


class RetrievalLoopTest(unittest.TestCase):

    def test_run_sync_executes_on_dedicated_loop_reusable_across_callers(self):
        """同一客户端连续被多个调用线程使用都不报错（修复前这里必抛 Event loop is closed）。"""
        async def probe():
            client = hybrid_search.es_client()
            if client is None:
                return "unconfigured"
            return (await client.count(index=hybrid_search.ES_INDEX))["count"] > 0

        # 先在"主循环"里跑一次（模拟 lifespan 的 ensure_schema）；后端不可达时
        # ensure_schema 会抛，应用侧按既有行为记录日志，测试同样容忍
        _load_runtime_env()
        try:
            asyncio.run(hybrid_search.ensure_schema())
        except Exception:
            pass
        first = hybrid_search.run_sync(probe())
        second = hybrid_search.run_sync(probe())   # 复用同一客户端与同一循环
        self.assertEqual(first, second)

    def test_shutdown_is_idempotent(self):
        hybrid_search.shutdown()
        hybrid_search.shutdown()   # 二次调用不应抛错

    def test_configured_environment_actually_uses_es(self):
        if not _es_configured():
            self.skipTest("SMARTLECT_ES_URL 未配置：跳过真后端断言")
        async def count():
            client = hybrid_search.es_client()
            return (await client.count(index=hybrid_search.ES_INDEX))["count"]
        self.assertGreaterEqual(hybrid_search.run_sync(count()), 0)


if __name__ == "__main__":
    unittest.main()
