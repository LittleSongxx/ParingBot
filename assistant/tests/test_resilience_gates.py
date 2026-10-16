"""Run-admission gates and the knowledge search cache; no MySQL, no live keys."""

import asyncio
import itertools
import threading
from unittest.mock import MagicMock, Mock, patch
import unittest

import httpx

from smartlect.app import create_app
from smartlect.auth import ActorContext
from smartlect.cache import TtlCache
from smartlect.config import Settings
from smartlect.db import canonical
from smartlect.knowledge import KnowledgeStore


def actor_of(actor_id="u1", kind="user", permissions=("shopping:read",)):
    return ActorContext(subject_type=kind, actor_id=actor_id, session_id="synthetic",
                        permissions=permissions, execution_scope_id="scope")


class TtlCacheTests(unittest.TestCase):
    def test_expires_and_bounds(self):
        cache = TtlCache(2, 0.02)
        cache.put("a", 1)
        self.assertEqual(cache.get("a"), 1)
        import time
        time.sleep(0.03)
        self.assertIsNone(cache.get("a"))
        cache.put("b", 1)
        cache.put("c", 2)  # at capacity: the earliest deadline is evicted, never over-grow
        cache.put("d", 3)
        self.assertEqual(len(cache._entries), 2)
        self.assertIsNone(cache.get("a"))


class KnowledgeSearchCacheTests(unittest.TestCase):
    def test_second_identical_search_skips_the_scan_pair(self):
        connection, cursor = MagicMock(), MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchall.return_value = []
        cursor.fetchone.return_value = {"revision": 7}
        store = KnowledgeStore(Mock(return_value=connection))
        actor = actor_of()
        first = store.search(actor, "退款政策")
        second = store.search(actor, "退款政策")
        scans = [c for c in cursor.execute.call_args_list if "FROM knowledge_document" in c.args[0]]
        self.assertEqual(len(scans), 2)  # only the first call ran the visible/hidden scan pair
        self.assertEqual(canonical(first), canonical(second))
        store.search(actor, "另一个问题")  # a different query misses the cache
        scans = [c for c in cursor.execute.call_args_list if "FROM knowledge_document" in c.args[0]]
        self.assertEqual(len(scans), 4)


def message_app(actors, *, per_actor, total):
    class Identity:
        def __init__(self, actors):
            self.actors = list(actors)
        async def authenticate(self, *args, **kwargs):
            return self.actors[0] if len(self.actors) == 1 else self.actors.pop(0)
        def require_csrf(self, *args):
            pass
    counter = itertools.count(1)
    store = MagicMock()
    store.create_run.side_effect = lambda *a, **k: {"agent_run_id": f"run-{next(counter)}",
                                                    "state": "CREATED", "context": {}}
    store.claim_run.side_effect = lambda actor, run_id, **k: {"agent_run_id": run_id, "token": "t", "epoch": 1}
    store.get_run.side_effect = lambda actor, run_id: {"agent_run_id": run_id, "state": "RUNNING", "context": {}}
    memory = MagicMock()
    memory.recover_handoff_run.return_value = None
    return create_app(Settings(model_mode="mock"),
                      config={"SMARTLECT_ASSISTANT_RUNS_PER_ACTOR": str(per_actor),
                              "SMARTLECT_ASSISTANT_RUNS_GLOBAL": str(total)},
                      store=store, memory=memory, identity=Identity(actors), provider=MagicMock())


class SimpleNamespaceProxy(MagicMock):
    def resolve_actor(self, actor):
        return actor
    def assert_scope_writable(self, actor):
        return None


async def hold_run(**kwargs):
    """Stand-in for run_shopping: keeps the executor task alive long enough to be counted."""
    await asyncio.sleep(0.5)


class ConnectionReuseTests(unittest.TestCase):
    def test_thread_local_reuse_and_dead_connection_fallback(self):
        import smartlect.db as events

        class FakeConn:
            def __init__(self):
                self.fail_ping = False
                self.closed = False

            def ping(self, reconnect=True):
                if self.fail_ping:
                    raise RuntimeError("server has gone away")

            def close(self):
                self.closed = True

        built = []
        original_new, original_local = events._new_connection, events._local
        events._local = threading.local()  # isolate from other tests' thread state
        try:
            first = FakeConn()
            events._new_connection = lambda: (built.append(1), first)[1]
            self.assertIs(events.connect_from_env(), first)
            self.assertIs(events.connect_from_env(), first)  # same thread, one connection
            self.assertEqual(len(built), 1)
            first.fail_ping = True
            second = FakeConn()
            events._new_connection = lambda: (built.append(1), second)[1]
            self.assertIs(events.connect_from_env(), second)  # dead conn replaced, not reused
            self.assertTrue(first.closed)
            self.assertEqual(len(built), 2)
        finally:
            events._new_connection, events._local = original_new, original_local


class RunAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def send(self, app, message_id):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as client:
            return await client.post("/api/assistant/conversations/c1/messages",
                                     json={"message_id": message_id, "text": "你好"})

    async def test_per_actor_limit_returns_429_while_a_run_is_live(self):
        app = message_app([actor_of("u1")], per_actor=1, total=8)
        with patch("smartlect.app.run_shopping", new=hold_run):
            first = await self.send(app, "m1")
            second = await self.send(app, "m2")
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 429)
            self.assertEqual(second.json()["error"], "actor_run_limit")
            from prometheus_client import REGISTRY
            self.assertGreaterEqual(REGISTRY.get_sample_value(
                "assistant_run_admission_rejections_total", {"gate": "actor"}), 1.0)
            await asyncio.sleep(0.6)  # drain the held executor task

    async def test_global_limit_admits_a_second_actor_only_after_a_slot_frees(self):
        app = message_app([actor_of("u1"), actor_of("u2")], per_actor=4, total=1)
        with patch("smartlect.app.run_shopping", new=hold_run):
            first = await self.send(app, "m1")
            second = await self.send(app, "m2")
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 429)
            self.assertEqual(second.json()["error"], "assistant_busy")
            await asyncio.sleep(0.6)


if __name__ == "__main__":
    unittest.main()
