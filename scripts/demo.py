"""Exercise actual Smartlect HTTP transactions and reconcile Java money/stock."""
import argparse
import sys
import json
from pathlib import Path
import time
import uuid

from smartlect.commerce import CommerceClient, CommerceError
from smartlect.money import to_cents
from runtime import ROOT, ENV_FILE, parse_env


def cents(value):
    return to_cents(str(value))


def wait_for(read, predicate, label, timeout=40):
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if predicate(value):
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f"Timed out waiting for {label}: {value}")
        time.sleep(0.2)


def transaction_scenario(seed):
    config = parse_env(ENV_FILE)
    client = CommerceClient(config)
    run_id = "smartlect-" + uuid.uuid4().hex[:24]
    print(f"RUN {run_id} seed={seed}", flush=True)
    checks = []

    def passed(label):
        checks.append(label)
        print(f"PASS {label}", flush=True)

    def rejected(action, label):
        try:
            action()
        except CommerceError:
            passed(label)
        else:
            raise AssertionError(f"Expected rejection: {label}")

    untrusted = CommerceClient({**config, "SMARTLECT_INTERNAL_TOKEN": "invalid"})
    rejected(lambda: untrusted.request("admin", "/internal/demo/seed"), "Internal fixture API requires Smartlect token")
    client.request("admin", "/internal/demo/seed")
    session = client.request("admin", "/internal/demo/session", form={
        "userIndex": seed % 100, "password": config["SMARTLECT_DEMO_PASSWORD"]})
    ids = client.request("product", "/internal/product/listOnSaleProductIds")
    ids = sorted(product for product in ids if product.startswith("910000000000"))
    snapshot = client.request("product", "/internal/product/snapshotBatch", data={"productIds": ids})
    assert len(snapshot["products"]) == 20 and len(snapshot["skus"]) == 40
    skus = sorted(snapshot["skus"], key=lambda sku: (sku["productId"], sku["propertyValueIds"]))

    def stock(sku):
        return client.request("stock", "/internal/stock/getBatch", data=[{
            "productId": sku["productId"], "propertyValueIdHash": sku["propertyValueIdHash"]}])[0]["stock"]

    selected = [sku for sku in skus if stock(sku) >= 1][:3]
    if len(selected) != 3:
        # 刻意不静默补货（补货会掩盖真实库存行为），但要让失败"可判定"：
        # 退出码 2 = 环境需要重置，而不是断言失败（2026-10-16 审计：此前被当回归门禁时产生假红）。
        print("demo: 演示库存已被此前的运行消费，请先重置环境再跑：\n"
              "  ./scripts/dev.sh seed-store      # 重新铺演示货架\n"
              "  python3 scripts/reset_demo.py    # 退役旧 demo run", file=sys.stderr)
        raise SystemExit(2)
    before = [stock(sku) for sku in selected]
    passed("Java fixtures and authoritative catalogue/SKU lookup")

    def order_payload(items):
        return {"payMethod": "mock", "addressId": session["addressId"], "orderFrom": 0,
                "orderList": [{"productId": sku["productId"], "propertyValueIds": sku["propertyValueIds"],
                               "buyCount": 1} for sku in items]}

    payload = order_payload(selected)
    payload["orderList"][0].update(recommendationRequestId="unverified-touchpoint", recommendationPosition=1)
    pay = client.request("gateway", "/api/order/postOrder", data=payload, session=session, key=run_id + "-buy")
    pay_id = pay["payOrderId"]
    expected_cents = sum(cents(sku["price"]) for sku in selected)
    assert cents(pay["amount"]) == expected_cents, pay
    after_order = [stock(sku) for sku in selected]
    assert after_order == [amount - 1 for amount in before], (before, after_order)
    passed("Checkout drops unverified attribution, charges Java price and deducts stock once")
    replay = client.request("gateway", "/api/order/postOrder", data=payload, session=session, key=run_id + "-buy")
    assert replay["payOrderId"] == pay_id and [stock(sku) for sku in selected] == after_order
    changed = order_payload(selected)
    changed["orderList"][0]["buyCount"] = 2
    rejected(lambda: client.request("gateway", "/api/order/postOrder", data=changed,
                                   session=session, key=run_id + "-buy"), "Changed purchase rejected under same idempotency key")

    settled = client.request("pay", "/internal/pay/mock/complete", data={"payOrderId": pay_id})
    duplicate = client.request("pay", "/internal/pay/mock/complete", data={"payOrderId": pay_id})
    assert cents(settled["amount"]) == expected_cents and duplicate["channelOrderId"] == settled["channelOrderId"]
    assert [stock(sku) for sku in selected] == after_order

    def orders():
        all_orders = client.request("order", "/internal/order/commerce/listOrders",
                                    data={"limit": 100}, session=session)
        return [order for order in all_orders if order["payOrderId"] == pay_id]

    paid_orders = wait_for(orders, lambda values: values and all(
        item["paidAmount"] is not None for order in values for item in order["items"]), "paid items")
    items = [item for order in paid_orders for item in order["items"]]
    assert sum(cents(item["paidAmount"]) for item in items) == expected_cents
    passed("Persisted item payments reconcile and duplicate settlement does not deduct stock")

    item = next(item for item in items if item["propertyValueIdHash"] == selected[0]["propertyValueIdHash"])
    refund_form = {"orderItemId": item["orderItemId"]}
    client.request("gateway", "/api/order/refundOrder", form=refund_form, session=session, key=run_id + "-refund")
    refunds = wait_for(lambda: client.request("order", "/internal/order/commerce/refundStatus",
                      data=refund_form, session=session),
                      lambda values: values and values[0]["status"] == "COMPLETED", "refund completion")
    assert cents(refunds[0]["refundAmount"]) == cents(item["paidAmount"])
    wait_for(lambda: stock(selected[0]), lambda value: value == before[0], "refund stock restoration")
    client.request("gateway", "/api/order/refundOrder", form=refund_form, session=session, key=run_id + "-refund")
    assert stock(selected[0]) == before[0]
    passed("Confirmed refund equals item cash paid; repeated refund restores stock once")

    cancel_sku = selected[0]
    cancel_before = stock(cancel_sku)
    cancel_payload = order_payload([cancel_sku])
    cancel_payload["orderList"][0]["buyCount"] = cancel_before
    cancel_pay = client.request("gateway", "/api/order/postOrder", data=cancel_payload,
                                session=session, key=run_id + "-cancel-buy")
    assert stock(cancel_sku) == 0
    rejected(lambda: client.request("gateway", "/api/order/postOrder", data=order_payload([cancel_sku]),
             session=session, key=run_id + "-stockout"), "Sold-out SKU rejects another purchase")
    cancel_form = {"orderId": cancel_pay["orderId"]}
    client.request("gateway", "/api/order/cancelOrder", form=cancel_form, session=session, key=run_id + "-cancel")
    wait_for(lambda: stock(cancel_sku), lambda value: value == cancel_before, "cancel stock restoration")
    client.request("gateway", "/api/order/cancelOrder", form=cancel_form, session=session, key=run_id + "-cancel")
    assert stock(cancel_sku) == cancel_before
    rejected(lambda: client.request("pay", "/internal/pay/mock/complete", data={"payOrderId": cancel_pay["payOrderId"]}),
             "Cancelled payment intent rejects settlement")
    passed("Cancellation and replay restore stock exactly once")

    client.request("admin", "/internal/demo/seed")
    assert [stock(sku) for sku in selected] == [before[0], before[1] - 1, before[2] - 1]
    passed("Repeated fixture initialization never refills consumed inventory")
    result = {"run_id": run_id, "scenario": "purchase_stockout", "seed": seed, "checks": checks,
            "pay_order_id": pay_id, "paid_cents": expected_cents,
            "refunded_cents": cents(refunds[0]["refundAmount"]), "initial_stock": before,
            "final_stock": [stock(sku) for sku in selected], "model_mode": "mock"}
    # ADR-0008 退役 growth 事件消费线：原 SMARTLECT_ASSISTANT_EVENTS_ENABLED 分支调用
    # 已删除的 /internal/ledger/summary 对账（demo 必失败），随退役一并移除。
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smartlect transaction regression demo")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("output already exists; preserve previous evidence")
    result = transaction_scenario(args.seed)
    destination = args.output or ROOT / "artifacts" / f"{result['run_id']}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"Transaction checks passed: {destination}")
