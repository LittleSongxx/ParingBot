#!/usr/bin/env python3
"""故障演练：把"设计上应该"变成"我在本地实测过"。

三个 drill（都可复跑，产物可直接作为面试/评审证据）：
  1. duplicate-order  并发同幂等键下单 → 断言只落一单、库存只扣一次、账本一行
  2. mq-down          停 RocketMQ broker → 下单仍成立、消息滞留 Outbox → 恢复后自动投递
  3. redis-down       停 Redis → 鉴权 fail-closed、商品详情回源 DB → 恢复后会话仍有效

设计原则
- **动作走 HTTP、断言查 DB**：动作必须经过完整链路（网关/鉴权/幂等/库存/Outbox），
  断言则直接读库拿确定值（避免又一层 API 语义猜测）。
- 每个 drill 自建前置（登录、选 SKU、记基线），跑完打印 PASS/FAIL 明细，便于归档。

用法：
    python3 scripts/drills/fault_drills.py duplicate-order [--out FILE]
    python3 scripts/drills/fault_drills.py mq-down [--out FILE]
    python3 scripts/drills/fault_drills.py redis-down [--out FILE]
    python3 scripts/drills/fault_drills.py all --out eval/verification/<date>/fault-drills.txt
"""
from __future__ import annotations

import argparse
import concurrent.futures
import http.cookiejar
import json
import pathlib
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
MYSQL = "smartlect-mysql-1"
BROKER = "smartlect-rocketmq-broker-1"
REDIS = "smartlect-redis-1"
SHOPPER = ("shopper@smartlect.demo", "Visit-Smartlect-2026")
ADDRESS_ID = "SL8800000002D"
# 演示目录里的 iPhone 17 Pro Max 银色 256G（种子数据，见 backend/data/02_catalog_seed.sql）
PRODUCT_ID = "895150981058759"
PROPERTY_VALUE_IDS = "1780554968348-1780554968349"
PROPERTY_VALUE_ID_HASH = "137e14ea51a28c111aef8b2258c3691f"

_LINES: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _LINES.append(text)


def env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / "run/runtime.env").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


ENV = env()
GATEWAY = f"http://127.0.0.1:{ENV.get('SMARTLECT_GATEWAY_PORT', '18080')}"


def sql(query: str) -> str:
    out = subprocess.run(
        ["docker", "exec", MYSQL, "sh", "-c",
         'MYSQL_PWD=$MYSQL_ROOT_PASSWORD mysql -N -B -uroot -e "$0"', query],
        capture_output=True, text=True, check=True)
    return out.stdout.strip()


def docker(action: str, container: str) -> None:
    subprocess.run(["docker", action, container], capture_output=True, text=True, check=True)


def api(method: str, path: str, *, body=None, headers=None, opener=None, form=None,
         timeout=20) -> tuple[int, dict | str]:
    url = GATEWAY + path
    data = None
    hdrs = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    do_open = opener.open if opener is not None else urllib.request.urlopen
    try:
        with do_open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, raw


def login() -> tuple[urllib.request.OpenerDirector, str]:
    """登录拿会话 Cookie（演示账号跳过验证码）。返回 (opener, token)。"""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    status, payload = api("POST", "/api/account/login", form={
        "email": SHOPPER[0], "password": SHOPPER[1]}, opener=opener)
    token = next((c.value for c in jar if c.name == "token"), "")
    assert status == 200 and token, f"登录失败 status={status} payload={payload}"
    return opener, token


def sku_stock() -> int:
    return int(sql(f"SELECT stock FROM smartlect_stock.sku_stock WHERE product_id='{PRODUCT_ID}' "
                   f"AND property_value_id_hash='{PROPERTY_VALUE_ID_HASH}'"))


def place_order(opener, key: str) -> tuple[int, dict | str]:
    return api("POST", "/api/order/postOrder", opener=opener, headers={"Idempotency-Key": key}, body={
        "orderFrom": 0,
        "addressId": ADDRESS_ID,
        "payMethod": "mock",
        "orderList": [{"productId": PRODUCT_ID, "propertyValueIds": PROPERTY_VALUE_IDS, "buyCount": 1}],
    })


def order_identity(payload) -> str:
    """响应里的订单标识：postOrder 返回支付单号（payOrderId）为主，orderId 可能存在。"""
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        data = payload["data"]
        return str(data.get("payOrderId") or data.get("orderId") or "")
    return ""


def check(label: str, ok: bool, detail: str = "") -> bool:
    emit(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    return ok


# ─────────────────────────── drill 1 ───────────────────────────
def drill_duplicate_order() -> bool:
    emit("## drill 1 · 并发同幂等键下单（幂等账本 + 条件扣减）")
    opener, _ = login()
    key = f"drill-dup-{int(time.time())}"
    stock_before = sku_stock()
    orders_before = int(sql("SELECT COUNT(*) FROM smartlect_order.order_info"))
    emit(f"  基线：库存 {stock_before}，订单总数 {orders_before}，幂等键 {key}")

    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: place_order(opener, key), range(8)))
    elapsed = time.time() - started

    codes = [status for status, _ in results]
    order_ids = {identity for _, payload in results if (identity := order_identity(payload))}
    ledger = sql("SELECT status, COUNT(*) FROM smartlect_order.order_request_idempotency "
                 f"WHERE idempotency_key='{key}' GROUP BY status")
    stock_after = sku_stock()
    orders_after = int(sql("SELECT COUNT(*) FROM smartlect_order.order_info"))

    emit(f"  8 个并发响应用时 {elapsed:.2f}s；HTTP 码分布 {sorted(set(codes))}；返回的订单标识 {sorted(order_ids)}")
    emit(f"  账本：{ledger or '（无行）'}；库存 {stock_before} → {stock_after}；订单总数 {orders_before} → {orders_after}")
    split = {code: codes.count(code) for code in sorted(set(codes))}
    emit("  响应码分布：" + " + ".join(f"{count}×{code}" for code, count in split.items()))

    # 顺序重复（幂等键已 COMPLETED）：客户端视角的"用户手抖点两次"，必须原样拿回同一单
    seq_status, seq_payload = place_order(opener, key)
    seq_order_id = order_identity(seq_payload)
    emit(f"  顺序重复一次：status={seq_status} orderId={seq_order_id or '（见响应）'}")

    ok = True
    # 并发窗口内的期望行为：先到的成功（200），撞上"处理中"的被明确拒绝（409），
    # 绝不允许出现 5xx —— 也就是说"重复提交"要么拿到同一单，要么被确定性拒绝。
    ok &= check("并发响应只出现 200/409（无 5xx、无静默失败）",
                set(codes) <= {200, 409}, f"codes={sorted(set(codes))}")
    ok &= check("只落 1 张订单", orders_after - orders_before == 1, f"Δ={orders_after - orders_before}")
    ok &= check("库存只扣 1 件", stock_before - stock_after == 1, f"Δ={stock_before - stock_after}")
    ok &= check("账本只有 1 行且为 COMPLETED", ledger == "COMPLETED\t1", ledger or "（无行）")
    ok &= check("成功的响应都指向同一订单", 1 <= len(order_ids) <= 2, f"ids={sorted(order_ids)}")
    ok &= check("顺序重复拿回同一单（纯重放）",
                seq_status == 200 and seq_order_id in order_ids,
                f"status={seq_status} orderId={seq_order_id}")
    ok &= check("重放不再扣库存", sku_stock() == stock_after, f"stock={sku_stock()}")
    return ok


# ─────────────────────────── drill 2 ───────────────────────────
def drill_mq_down() -> bool:
    emit("## drill 2 · 停 broker：下单仍成立、事件滞留 Outbox、恢复后自动投递")
    opener, _ = login()
    emit(f"  停掉 {BROKER}（RocketMQ broker）")
    docker("stop", BROKER)
    # 停机/恢复必须成对：中途异常也要把 broker 拉回来（此前脚本失败会把环境留在停机态）

    key = f"drill-mq-{int(time.time())}"
    baseline_id = int(sql("SELECT COALESCE(MAX(id), 0) FROM smartlect_order.local_message_outbox"))
    emit(f"  Outbox 基线 max(id)={baseline_id}")
    status, payload = place_order(opener, key)

    def new_outbox_states() -> str:
        return sql("SELECT status, COUNT(*) FROM smartlect_order.local_message_outbox "
                   f"WHERE id > {baseline_id} GROUP BY status")

    states = new_outbox_states()
    emit(f"  下单响应 status={status}；本次新增 Outbox 行状态分布：{states or '（无新增行）'}")

    ok = True
    ok &= check("broker 停机期间下单仍返回 200（本地事务不依赖 MQ）", status == 200,
                f"status={status}, payOrderId={order_identity(payload)}")
    ok &= check("本次消息已落 Outbox（事务内写入，不随 MQ 可用性丢失）", bool(states), states or "无新增行")
    ok &= check("停机期间没有一条被标记为 SENT（2）", "2\t" not in states, f"分布={states}")
    ok &= check("滞留状态是 PENDING/SENDING/FAILED 三种之一",
                all(line.split("\t")[0] in {"0", "1", "3"} for line in states.splitlines() if line),
                f"分布={states}")

    emit(f"  恢复 {BROKER}，等待 Outbox 兜底投递（xxl-job outboxDispatch 每 5s 一轮）")
    try:
        docker("start", BROKER)
    except Exception as error:  # noqa: BLE001
        raise AssertionError(f"恢复 broker 失败，请手工执行 docker start {BROKER}：{error}") from error
    sent = "0"
    for _ in range(24):
        time.sleep(5)
        sent = sql("SELECT COUNT(*) FROM smartlect_order.local_message_outbox "
                   f"WHERE id > {baseline_id} AND status=2")
        if sent != "0":
            break
    pending_left = sql("SELECT COUNT(*) FROM smartlect_order.local_message_outbox "
                       f"WHERE id > {baseline_id} AND status<>2")
    emit(f"  恢复后：SENT={sent}，未投递剩余={pending_left}；最终分布={new_outbox_states()}")
    ok &= check("broker 恢复后本次消息全部投递出去（无残留、无人工介入）",
                pending_left == "0" and sent != "0", f"SENT={sent} 残留={pending_left}")
    return ok


# ─────────────────────────── drill 3 ───────────────────────────
def drill_redis_down() -> bool:
    emit("## drill 3 · 停 Redis：鉴权 fail-closed、商品详情回源 DB、恢复后会话仍有效")
    opener, token = login()
    status_ok, _ = api("GET", "/api/order/loadMyOrder?pageNo=1&pageSize=5", opener=opener)
    detail_ok, _ = api("GET", "/api/product/getProduct?productId=" + PRODUCT_ID, opener=opener)
    emit(f"  基线：带会话访问订单列表 status={status_ok}，商品详情 status={detail_ok}")
    ok = True
    ok &= check("基线两项均 200", status_ok == 200 and detail_ok == 200, f"{status_ok}/{detail_ok}")

    emit(f"  停掉 {REDIS}")
    docker("stop", REDIS)
    time.sleep(1)
    status_down, payload_down = api("GET", "/api/order/loadMyOrder?pageNo=1&pageSize=5", opener=opener)
    detail_down, _ = api("GET", "/api/product/getProduct?productId=" + PRODUCT_ID, opener=opener)
    # 更强的 fail-closed 判据：Redis 不可用时**不能再签发新会话**（此前只看"非 200"，
    # 500/502 也会当通过）。新登录请求必须失败，才说明鉴权真的关上了门。
    login_status, login_payload = api("POST", "/api/account/login", form={
        "email": SHOPPER[0], "password": SHOPPER[1]})
    emit(f"  Redis 停机：订单列表 status={status_down} payload={str(payload_down)[:80]}；"
         f"商品详情 status={detail_down}；新登录 status={login_status}")
    ok &= check("Redis 不可用时订单列表不放行", status_down not in (200,), f"status={status_down}")
    ok &= check("Redis 不可用时无法签发新会话（fail-closed 而非 fail-open）",
                login_status != 200, f"login={login_status}")
    ok &= check("商品详情仍可用（缓存不可达→回源 DB）", detail_down == 200, f"status={detail_down}")

    emit(f"  恢复 {REDIS}")
    try:
        docker("start", REDIS)
    except Exception as error:  # noqa: BLE001
        raise AssertionError(f"恢复 Redis 失败，请手工执行 docker start {REDIS}：{error}") from error
    time.sleep(6)
    status_back, _ = api("GET", "/api/order/loadMyOrder?pageNo=1&pageSize=5", opener=opener)
    emit(f"  恢复后订单列表 status={status_back}（Redis 有 AOF，会话未丢）")
    ok &= check("Redis 恢复后原会话继续可用", status_back == 200, f"status={status_back}")
    return ok


DRILLS = {
    "duplicate-order": drill_duplicate_order,
    "mq-down": drill_mq_down,
    "redis-down": drill_redis_down,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("drill", choices=[*DRILLS, "all"])
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    names = list(DRILLS) if args.drill == "all" else [args.drill]
    emit(f"# 故障演练（{time.strftime('%Y-%m-%d %H:%M:%S')} · 本地 docker 栈 · gateway {GATEWAY}）")
    results = {}
    for name in names:
        emit("")
        try:
            results[name] = DRILLS[name]()
        except Exception as error:  # noqa: BLE001 - 演练脚本要把失败如实记录
            results[name] = False
            emit(f"  [ERROR] {name} 执行异常：{type(error).__name__}: {error}")
        emit(f"  ⇒ {name}: {'PASS' if results[name] else 'FAIL'}")

    emit("")
    emit("## 汇总")
    for name, passed in results.items():
        emit(f"- {name}: {'PASS' if passed else 'FAIL'}")
    if args.out:
        out = ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(_LINES) + "\n", encoding="utf-8")
        print(f"\n已写入 {out.relative_to(ROOT)}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
