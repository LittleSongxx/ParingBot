"""Tiny in-process TTL caches. One uvicorn process serves all traffic, so plain
dicts with a monotonic deadline are enough; no cross-process coherence required.

线程安全：检索路径跑在 `asyncio.to_thread` 工作线程里（可能并发），此前无锁的实现
在容量满时 `min(self._entries, ...)` 迭代字典，与另一线程的写入相撞会抛
`RuntimeError: dictionary changed size during iteration`（2026-10-16 审计）。
单实例的键空间很小，一把普通锁的代价可忽略。"""

import threading
import time


class TtlCache:
    """Bounded key->value store; entries expire lazily and the earliest deadline is evicted first."""

    def __init__(self, maxsize, ttl_seconds):
        if maxsize < 1 or ttl_seconds <= 0:
            raise ValueError("invalid_cache_bounds")
        self.maxsize, self.ttl = maxsize, ttl_seconds
        self._entries = {}  # key -> (expires_at, value)
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if time.monotonic() >= entry[0]:
                self._entries.pop(key, None)
                return None
            return entry[1]

    def put(self, key, value):
        with self._lock:
            if len(self._entries) >= self.maxsize:
                oldest = min(self._entries, key=lambda k: self._entries[k][0])
                self._entries.pop(oldest, None)
            self._entries[key] = (time.monotonic() + self.ttl, value)
