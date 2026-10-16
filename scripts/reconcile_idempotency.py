#!/usr/bin/env python3
"""驱动幂等账本的出口：对「核对中 / 待人工」的幂等键做一次业务侧复核。

背景（为什么需要这个脚本）
- 幂等账本只存 userId + commandType + 幂等键，**不存业务参数**，服务端无法独自证明
  "原请求到底成交没有"——所以 `INCONCLUSIVE` / `MANUAL_REVIEW` 不会被自动改判
  （把 UNKNOWN 猜成 FAILED 会让"没成交"与"成交了但响应丢了"再也分不开）。
- 出口是既有的 `CommerceActionStatusService`：调用方带着业务参数来问"效果发生了吗"，
  它去业务表核实（订单是否存在/是否已取消/退款单是否存在…），
  发生了 → markReconciled(COMPLETED)；没发生 → 累计核对次数，达到上限转人工复核。

谁在什么时候用
- `orderIdempotencyReconcile` 任务（xxl-job）每 5 分钟把待核对行打 WARN 日志并计数
  （指标 `smartlect_idempotent_stuck_total{status}`）；
- 运维按日志里的键，带上业务参数执行本脚本一次。

用法
    python3 scripts/reconcile_idempotency.py \
        --user-id 8800000002 --command COMMERCE_CANCEL_ORDER \
        --key <幂等键> --param orderId=2026...--param actionType=CANCEL_ORDER

参数说明
- `--command` 取 OrderRequestIdempotencyService 里的常量：POST_ORDER / COMMERCE_CANCEL_ORDER /
  COMMERCE_REFUND / COMMERCE_CONFIRM_RECEIPT 等；
- `--param` 是动作的业务参数（actionStatus 按 actionType + params 判断效果），可重复传；
- 需要 run/runtime.env 里的内部令牌与订单服务端口（默认从该文件读取）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent


def env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = ROOT / "run/runtime.env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="幂等账本核对（驱动 INCONCLUSIVE/MANUAL_REVIEW 出口）")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--command", required=True, help="幂等命令类型，如 COMMERCE_CANCEL_ORDER")
    parser.add_argument("--key", required=True, help="幂等键（日志里的 key）")
    parser.add_argument("--param", action="append", default=[], metavar="K=V",
                        help="业务参数，可重复：--param orderId=xxx --param actionType=CANCEL_ORDER")
    parser.add_argument("--port", default="", help="订单服务端口，默认取 runtime.env 的 SMARTLECT_ORDER_PORT")
    args = parser.parse_args()

    values = env()
    port = args.port or values.get("SMARTLECT_ORDER_PORT", "18104")
    token = values.get("SMARTLECT_INTERNAL_TOKEN", "")
    if not token:
        print("缺少 SMARTLECT_INTERNAL_TOKEN（先 ./scripts/dev.sh bootstrap）")
        return 2

    params: dict[str, str] = {}
    for item in args.param:
        if "=" not in item:
            print(f"--param 需要 K=V 形式：{item}")
            return 2
        key, value = item.split("=", 1)
        params[key] = value

    body = json.dumps({
        "userId": args.user_id,
        "commandType": args.command,
        "idempotencyKey": args.key,
        "params": params,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/internal/order/commerce/actionStatus",
        data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Internal-Token": token,
            # 核对也属于"用户数据操作"：服务端要求委托身份与 body 里的 userId 一致
            "X-Smartlect-User-Id": args.user_id,
        })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        print(f"核对失败 HTTP {error.code}: {error.read().decode()[:400]}")
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    status = (payload.get("data") or {}).get("status")
    print(f"\n结论：{status}")
    if status == "SUCCESS":
        print("业务效果已确认存在 → 账本已 markReconciled(COMPLETED)，同键重放会返回同一结果。")
    elif status == "FAILED":
        print("可判定为未成交 → 客户端可用同一幂等键重试，或换新键重发。")
    else:
        print("仍未定论：核对次数已累计；若日志显示 attempts 触顶，请人工复核后按需在管理端/脚本处置。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
