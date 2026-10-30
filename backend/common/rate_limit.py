"""登录失败限流（进程内存版）。

对「账号」和「来源 IP」两个维度分别记窗口期内的失败次数，任一维度达到上限就
锁定一段时间：这期间即使密码正确也不放行，客户端拿到 429 业务码和一句人话。

这是给单机演示栈用的最小实现：状态在进程内存里，重启清零、多实例不共享。
以后换成多实例部署，把 _failures/_locked_until 换成 Redis 即可，接口不用变。
"""

import os
import threading
import time

# 默认 10 次 / 300 秒窗口 / 锁 300 秒，全部可用环境变量覆盖
MAX_FAILS = int(os.environ.get("LOGIN_MAX_FAILS", "10") or 10)
WINDOW_SECONDS = int(os.environ.get("LOGIN_FAIL_WINDOW_SECONDS", "300") or 300)
LOCK_SECONDS = int(os.environ.get("LOGIN_LOCK_SECONDS", "300") or 300)
# 测试或本机排障可以整体关掉：LOGIN_RATE_LIMIT_ENABLED=false
ENABLED = os.environ.get("LOGIN_RATE_LIMIT_ENABLED", "true").strip().lower() not in (
    "0", "false", "no", "off")

# 进程内状态：key -> 最近失败的时间戳列表 / key -> 锁定截止时间（monotonic 秒）
_failures: dict[str, list[float]] = {}
_locked_until: dict[str, float] = {}
_guard = threading.Lock()


def reset() -> None:
    """清空全部计数。测试夹具用，线上只有进程重启才会走到类似效果。"""
    with _guard:
        _failures.clear()
        _locked_until.clear()


def set_enabled(value: bool) -> None:
    """开/关限流。测试里临时关掉跑与限流无关的登录用例。"""
    global ENABLED
    ENABLED = bool(value)


def _clean(now_ts: float, keys: list[str]) -> None:
    """去掉窗口外的失败记录和已经过期的锁，字典不会越积越大。"""
    for key in keys:
        if not key:
            continue
        until = _locked_until.get(key)
        if until is not None and until <= now_ts:
            _locked_until.pop(key, None)
        history = _failures.get(key)
        if history is not None:
            fresh = [ts for ts in history if now_ts - ts <= WINDOW_SECONDS]
            if fresh:
                _failures[key] = fresh
            else:
                _failures.pop(key, None)


def lock_remaining(keys: list[str]) -> int:
    """这几个维度里最长的剩余锁定时长（秒）。0 表示没被锁。"""
    if not ENABLED:
        return 0
    now_ts = time.monotonic()
    remaining = 0
    with _guard:
        _clean(now_ts, keys)
        for key in keys:
            if not key:
                continue
            until = _locked_until.get(key)
            if until is not None and until > now_ts:
                remaining = max(remaining, int(until - now_ts) + 1)
    return remaining


def record_failure(keys: list[str]) -> int:
    """记一次登录失败。返回记录后这一维度被锁定的剩余秒数（没锁返回 0）。"""
    if not ENABLED:
        return 0
    now_ts = time.monotonic()
    locked = 0
    with _guard:
        _clean(now_ts, keys)
        for key in keys:
            if not key:
                continue
            # 已经锁着的不再继续累加，锁是按第一次达阈值的时间算的
            if _locked_until.get(key, 0) > now_ts:
                continue
            history = _failures.setdefault(key, [])
            history.append(now_ts)
            if len(history) >= MAX_FAILS:
                _locked_until[key] = now_ts + LOCK_SECONDS
                locked = max(locked, LOCK_SECONDS)
    return locked


def record_success(keys: list[str]) -> None:
    """登录成功清掉这两个维度的失败计数，正常用户不会被历史失败连累。"""
    if not ENABLED:
        return
    with _guard:
        for key in keys:
            if not key:
                continue
            _failures.pop(key, None)
            _locked_until.pop(key, None)