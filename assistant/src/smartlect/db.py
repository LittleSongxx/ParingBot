"""MySQL 连接与 JSON 规范化：assistant 进程内的共享基础件。

2026-10 收敛重构：随 commerce ledger/worker 退役，从 events.py 中拆出这两
个被广泛使用的符号；库与环境变量名沿用历史 growth 命名。
"""

import json
import os
import threading
from decimal import Decimal

import pymysql

_local = threading.local()


def required_env(name):
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is required for assistant database access")
    return value


def _new_connection():
    database = required_env("SMARTLECT_ASSISTANT_MYSQL_DATABASE")
    user = required_env("SMARTLECT_ASSISTANT_MYSQL_USER")
    if database != "smartlect_growth" or user != "smartlect_growth":
        raise ValueError("Assistant must use its dedicated smartlect_growth database and identity")
    return pymysql.connect(host=required_env("SMARTLECT_MYSQL_HOST"),
                           port=int(required_env("SMARTLECT_MYSQL_PORT")), user=user,
                           password=required_env("SMARTLECT_ASSISTANT_MYSQL_PASSWORD"), database=database,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
                           autocommit=False, connect_timeout=5, read_timeout=10, write_timeout=10,
                           # MySQL is loopback-only for the assistant. pymysql's PREFERRED mode would
                           # build a fresh TLS context (full system CA load) per connection —
                           # hundreds of ms CPU each — which flattened concurrency to ~3 rps.
                           ssl_disabled=os.getenv("SMARTLECT_ASSISTANT_MYSQL_SSL", "0") != "1",
                           init_command="SET time_zone = '+00:00'")


def connect_from_env():
    """One long-lived connection per worker thread instead of one per transaction.

    Every db() hop runs on asyncio.to_thread's small persistent pool, so thread-local
    reuse caps connections at ~12 per process while removing the per-transaction TCP +
    auth handshake. pymysql's ``with conn:`` still commits/rolls back per transaction;
    ping(reconnect=True) heals idle drops (wait_timeout)."""
    connection = getattr(_local, "connection", None)
    if connection is not None:
        try:
            connection.ping(reconnect=True)
            return connection
        except Exception:
            try:
                connection.close()
            except Exception:
                pass
            _local.connection = None
    connection = _new_connection()
    _local.connection = connection
    return connection


def canonical(value):
    def decimal_json(item):
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError("unsupported JSON value")
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      default=decimal_json)
