#!/usr/bin/env python3
"""Smartlect 压测发压器（在发压机上运行，不部署到被测机）。

为什么是自研而不是 k6：被测集群的 QPS 量级在千级，Python asyncio + 多进程完全够用，
且零外部依赖（只需 httpx），省掉在境内机器上拉 k6 二进制的折腾。

用法：
  python3 loadgen.py browse --base http://172.21.131.151 --vus 400 --hold 100
  python3 loadgen.py order  --base http://172.21.131.151 --vus 5 --hold 120 \
      --admin http://172.21.131.151:18101 --product-port 18106 --stock-port 18108 \
      --pay-port 18103 --secrets /root/loadtest/secrets.env

产出一份 JSON 摘要（--json 指定路径）+ 一行人类可读汇总。
"""
import argparse
import asyncio
import fcntl
import hashlib
import hmac
import json
import multiprocessing as mp
import os
import random
import statistics
import sys
import time
from collections import Counter

import httpx

TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=30.0)
PROCESSES = max(1, min(4, os.cpu_count() or 1))
MOCK_PAY_SECRET_DEFAULT = "smartlect-dev-mock-pay-secret"


def mock_pay_headers(secrets, pay_order_id, amount_cents=None):
    """与 Java MockPaymentSignatureVerifier 相同的规范化字符串。"""
    timestamp = str(int(time.time()))
    nonce = os.urandom(12).hex()
    amount = "" if amount_cents is None else str(amount_cents)
    canonical = "\n".join(("POST", "/internal/pay/mock/complete", str(pay_order_id),
                           amount, timestamp, nonce))
    secret = secrets.get("SMARTLECT_MOCK_PAY_SECRET") or MOCK_PAY_SECRET_DEFAULT
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {"X-Mock-Pay-Timestamp": timestamp, "X-Mock-Pay-Nonce": nonce,
            "X-Mock-Pay-Signature": signature}


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[index]


class Recorder:
    """单进程内的延迟/计数采集；子进程结束后回传父进程合并。"""

    def __init__(self):
        self.latency = []
        self.by_name = {}
        self.status = Counter()
        self.errors = Counter()
        self.business_errors = 0

    def record(self, name, elapsed_ms, status, error=None, business_error=False):
        self.latency.append(elapsed_ms)
        bucket = self.by_name.setdefault(name, [])
        bucket.append(elapsed_ms)
        self.status[status] += 1
        if error:
            self.errors[f"{name}:{error}"] += 1
        if business_error:
            self.business_errors += 1
            self.errors[f"{name}:business_error"] += 1

    def merge(self, other):
        self.latency.extend(other.latency)
        for name, values in other.by_name.items():
            self.by_name.setdefault(name, []).extend(values)
        self.status.update(other.status)
        self.errors.update(other.errors)
        self.business_errors += other.business_errors

    def summary(self, elapsed):
        total = len(self.latency)
        ok = sum(count for code, count in self.status.items() if 200 <= code < 400)
        out = {
            "requests": total,
            "duration_s": round(elapsed, 3),
            "qps": round(total / elapsed, 2) if elapsed else 0.0,
            "ok": ok,
            "error_rate": round((total - ok) / total, 4) if total else 0.0,
            "latency_ms": {
                "avg": round(statistics.fmean(self.latency), 2) if self.latency else 0.0,
                "p50": round(percentile(self.latency, 50), 2),
                "p90": round(percentile(self.latency, 90), 2),
                "p95": round(percentile(self.latency, 95), 2),
                "p99": round(percentile(self.latency, 99), 2),
                "max": round(max(self.latency), 2) if self.latency else 0.0,
            },
            "status": {str(code): count for code, count in sorted(self.status.items())},
            "errors": dict(self.errors.most_common(8)),
            "business_errors": self.business_errors,
            "business_error_rate": round(self.business_errors / total, 4) if total else 0.0,
            "by_request": {
                name: {"count": len(values), "p50": round(percentile(values, 50), 2),
                       "p95": round(percentile(values, 95), 2),
                       "p99": round(percentile(values, 99), 2),
                       "avg": round(statistics.fmean(values), 2)}
                for name, values in sorted(self.by_name.items())
            },
        }
        return out


async def timed(client, recorder, name, method, url, **kwargs):
    started = time.perf_counter()
    try:
        response = await client.request(method, url, **kwargs)
        recorder.record(name, (time.perf_counter() - started) * 1000, response.status_code,
                        business_error=is_business_error(response, name))
        return response
    except Exception as exc:  # noqa: BLE001 - 压测器要把任何失败都计入错误率
        recorder.record(name, (time.perf_counter() - started) * 1000, 0, type(exc).__name__)
        return None


def is_business_error(response, name):
    """接口用 ResponseVO 包一层：HTTP 200 也可能是业务失败。

    2026-10-05 的教训：只看状态码，把 10 万次参数校验失败（HTTP 200 + status=error）
    当成了"零错误"报出去。
    """
    if name == "home" or len(response.content) > 65536:
        return False
    head = response.content[:1]
    if head != b"{":
        return False
    try:
        parsed = response.json()
    except ValueError:
        return False
    return isinstance(parsed, dict) and parsed.get("status") == "error"


# --------------------------------------------------------------------------- browse

async def browse_vu(client, args, recorder, deadline):
    while time.monotonic() < deadline:
        await timed(client, recorder, "home", "GET", f"{args.base}/")
        await timed(client, recorder, "loadCategory", "GET", f"{args.base}/api/product/loadCategory")
        await timed(client, recorder, "loadProduct", "POST", f"{args.base}/api/product/loadProduct",
                    content="pageNo=1",
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
        await asyncio.sleep(random.uniform(args.think_min, args.think_max))


# --------------------------------------------------------------------------- order

class OrderBudget:
    """跨进程的单量预算：超过上限就让 VU 自行退出。

    背景：demo 夹具的 40 个 SKU 原库存合计只有 580 件，一次 10 并发 × 60s 的交易压测
    就能全部打空；打空之后的所有轮次都会以 no_stock 失败，被误读成"系统在高负载下失败"。
    2026-10-06 就因此误判过一次交易闭环失败率。
    """

    def __init__(self, limit, path):
        self.limit = limit
        self.path = path
        self.granted = 0

    def take(self):
        if self.limit <= 0:
            return True
        with open(self.path, "a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.seek(0)
            used = int(handle.read().strip() or 0)
            if used >= self.limit:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                return False
            handle.seek(0)
            handle.truncate()
            handle.write(str(used + 1))
            handle.flush()
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return True


class OrderSession:
    """每个 VU 一份：夹具登录一次，之后循环下单-支付。"""

    def __init__(self, args, secrets):
        self.args = args
        self.token = secrets["SMARTLECT_INTERNAL_TOKEN"]
        self.demo_password = secrets["SMARTLECT_DEMO_PASSWORD"]
        self.user_index = random.randint(0, 99)
        self.user_id = None
        self.address_id = None
        self.skus = []

    def internal_headers(self):
        """内部接口两个头缺一不可：服务令牌 + 委托用户身份。

        身份必须走请求头而不是请求体——这是刻意的设计（body 里的 userId 可被模型输出
        或提示注入改写，头不能），所以夹具会话建立之后才能补上 X-Smartlect-User-Id。
        """
        headers = {"Content-Type": "application/json", "X-Internal-Token": self.token}
        if self.user_id:
            headers["X-Smartlect-User-Id"] = self.user_id
        return headers

    async def bootstrap(self, client):
        admin = self.args.admin
        await client.post(f"{admin}/internal/demo/seed", json={}, headers=self.internal_headers())
        session = await client.post(
            f"{admin}/internal/demo/session",
            params={"userIndex": self.user_index, "password": self.demo_password},
            headers=self.internal_headers())
        session.raise_for_status()
        payload = session.json()["data"]
        self.user_id = payload["userId"]
        self.address_id = payload["addressId"]
        self.token_user = payload["token"]

        product_ids = await client.post(
            f"{self.args.product}/internal/product/listOnSaleProductIds?productIdPrefix=910000000000",
            json={}, headers=self.internal_headers())
        ids = [pid for pid in (product_ids.json().get("data") or []) if str(pid).startswith("910000000000")]
        snapshot = await client.post(
            f"{self.args.product}/internal/product/snapshotBatch",
            json={"productIds": ids}, headers=self.internal_headers())
        skus = (snapshot.json()["data"] or {}).get("skus", [])

        stock = await client.post(
            f"{self.args.stock}/internal/stock/getBatch",
            json=[{"productId": sku["productId"], "propertyValueIdHash": sku["propertyValueIdHash"]}
                  for sku in skus],
            headers=self.internal_headers())
        # getBatch 按请求顺序返回每个 SKU 的库存对象（不是裸整数列表）
        stocks = [int(entry.get("stock") or 0) for entry in stock.json()["data"]]
        ranked = sorted(zip(stocks, skus), key=lambda pair: -pair[0])
        self.skus = [sku for value, sku in ranked if value > 0]
        return bool(self.skus)

    def web_headers(self, extra=None):
        headers = {"token": self.token_user, "Content-Type": "application/json"}
        if extra:
            headers.update(extra)
        return headers


async def order_vu(client, args, recorder, deadline, secrets, vu_index, budget=None):
    session = OrderSession(args, secrets)
    try:
        if not await session.bootstrap(client):
            recorder.record("bootstrap", 0, 0, "no_stock")
            return
    except Exception as exc:  # noqa: BLE001
        recorder.record("bootstrap", 0, 0, type(exc).__name__)
        print(f"[loadgen] VU {vu_index} bootstrap failed: {type(exc).__name__}: {exc}", flush=True)
        return

    counter = 0
    while time.monotonic() < deadline and session.skus:
        if budget is not None and not budget.take():
            return          # 预算用尽：主动退出，不再制造无意义的失败样本
        counter += 1
        sku = session.skus[(vu_index + counter) % len(session.skus)]
        run_id = f"lt-{os.getpid()}-{vu_index}-{counter}-{int(time.time() * 1000)}"

        # add2Cart 用实体表单绑定（方法签名里没有 @RequestBody），发 JSON 会让所有字段为
        # null → 每个请求都以业务错误返回（实测 167/167 全失败）。必须发 x-www-form-urlencoded。
        await timed(client, recorder, "add2Cart", "POST", f"{args.base}/api/productCart/add2Cart",
                    content="&".join([
                        f"productId={sku['productId']}",
                        f"propertyValueIds={sku['propertyValueIds']}",
                        f"propertyValueIdHash={sku['propertyValueIdHash']}",
                        "buyCount=1",
                    ]),
                    headers={**session.web_headers(),
                             "Content-Type": "application/x-www-form-urlencoded"})

        order = await timed(client, recorder, "postOrder", "POST", f"{args.base}/api/order/postOrder",
                            json={"payMethod": "mock", "addressId": session.address_id, "orderFrom": 0,
                                  "orderList": [{"productId": sku["productId"],
                                                 "propertyValueIds": sku["propertyValueIds"],
                                                 "buyCount": 1}]},
                            headers=session.web_headers({"Idempotency-Key": run_id + "-buy"}))
        pay_order_id = None
        if order is not None and order.status_code == 200:
            try:
                pay_order_id = order.json()["data"]["payOrderId"]
            except Exception:  # noqa: BLE001
                pass
        if not pay_order_id:
            await asyncio.sleep(args.think_min)
            continue

        await timed(client, recorder, "payComplete", "POST",
                    f"{args.pay}/internal/pay/mock/complete",
                    json={"payOrderId": pay_order_id},
                    headers={**session.internal_headers(),
                             **mock_pay_headers(secrets, pay_order_id)})
        await asyncio.sleep(random.uniform(args.think_min, args.think_max))


# --------------------------------------------------------------------------- runner

def worker(kind, args, secrets, vus, hold, queue):
    recorder = Recorder()
    budget = OrderBudget(args.max_orders, f"/tmp/loadgen-budget-{os.getpid()}.txt")

    async def run():
        limits = httpx.Limits(max_connections=vus + 10, max_keepalive_connections=vus + 10,
                              keepalive_expiry=30.0)
        async with httpx.AsyncClient(timeout=TIMEOUT, limits=limits,
                                     follow_redirects=False, verify=False) as client:
            started = time.monotonic()
            deadline = started + hold
            tasks = []
            for index in range(vus):
                if kind == "browse":
                    tasks.append(browse_vu(client, args, recorder, deadline))
                else:
                    tasks.append(order_vu(client, args, recorder, deadline, secrets, index, budget))
                # 错开启动，避免所有 VU 同一瞬间打同一个后端
                if index % 25 == 24:
                    await asyncio.sleep(0.05)
            await asyncio.gather(*tasks)
            return time.monotonic() - started

    elapsed = asyncio.run(run())
    queue.put({"elapsed": elapsed, "latency": recorder.latency, "by_name": recorder.by_name,
               "status": dict(recorder.status), "errors": dict(recorder.errors),
               "business_errors": recorder.business_errors})


def load_secrets(path):
    values = {}
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key] = value
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["browse", "order"])
    parser.add_argument("--base", required=True)
    parser.add_argument("--vus", type=int, default=100)
    parser.add_argument("--hold", type=int, default=100)
    parser.add_argument("--think-min", type=float, default=1.0)
    parser.add_argument("--think-max", type=float, default=3.0)
    parser.add_argument("--admin", default=None)
    parser.add_argument("--product", default=None)
    parser.add_argument("--stock", default=None)
    parser.add_argument("--pay", default=None)
    parser.add_argument("--secrets", default=None)
    parser.add_argument("--max-orders", type=int, default=0,
                        help="交易场景的总单量上限（0=不限）。固定单量才可跨轮次比较，"
                             "同时避免把 demo 夹具的库存打空导致后续轮次全线 no_stock")
    parser.add_argument("--json", default=None)
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    if args.kind == "order":
        for field in ("admin", "product", "stock", "pay", "secrets"):
            if not getattr(args, field):
                parser.error(f"--{field} is required for the order scenario")
    secrets = load_secrets(args.secrets) if args.secrets else {}

    processes = min(PROCESSES, max(1, args.vus // 8)) if args.vus >= 8 else 1
    per_process = args.vus // processes
    remainder = args.vus - per_process * processes

    budget_file = f"/tmp/loadgen-budget-{os.getpid()}.txt"
    if os.path.exists(budget_file):
        os.unlink(budget_file)
    print(f"[loadgen] {args.kind} vus={args.vus} hold={args.hold}s processes={processes} "
          f"base={args.base} max_orders={args.max_orders or '不限'}", flush=True)
    queue = mp.Queue()
    started = time.monotonic()
    procs = []
    for index in range(processes):
        share = per_process + (1 if index < remainder else 0)
        process = mp.Process(target=worker, args=(args.kind, args, secrets, share, args.hold, queue))
        process.start()
        procs.append(process)
    payloads = [queue.get() for _ in procs]
    for process in procs:
        process.join()
    wall = time.monotonic() - started

    merged = Recorder()
    for payload in payloads:
        merged.latency.extend(payload["latency"])
        for name, values in payload["by_name"].items():
            merged.by_name.setdefault(name, []).extend(values)
        merged.status.update({int(code): count for code, count in payload["status"].items()})
        merged.errors.update(payload["errors"])
        merged.business_errors += payload.get("business_errors", 0)

    summary = merged.summary(wall)
    summary["kind"] = args.kind
    summary["vus"] = args.vus
    summary["hold"] = args.hold
    summary["label"] = args.label
    summary["base"] = args.base
    summary["wall_s"] = round(wall, 3)

    latency = summary["latency_ms"]
    print(f"[loadgen] {args.kind} vus={args.vus} -> {summary['qps']} req/s | "
          f"p50={latency['p50']}ms p95={latency['p95']}ms p99={latency['p99']}ms "
          f"max={latency['max']}ms | 传输层错误={summary['error_rate'] * 100:.2f}% "
          f"业务错误={summary.get('business_errors', 0)}({summary.get('business_error_rate', 0) * 100:.2f}%) "
          f"| status={summary['status']}", flush=True)
    if args.json:
        with open(args.json, "w") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
        print(f"[loadgen] summary written to {args.json}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
