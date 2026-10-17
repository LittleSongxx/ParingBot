"""Mock 支付完成请求的签名头。

与 Java 侧 MockPaymentSignatureVerifier 共用一套规范化字符串：
POST\n/internal/pay/mock/complete\n<payOrderId>\n<amountCents>\n<timestamp>\n<nonce>
本地开发密钥由 scripts/dev.sh bootstrap 写入 run/runtime.env；生产必须显式设置。
"""
import hashlib
import hmac
import secrets
import time

DEFAULT_SECRET = "smartlect-dev-mock-pay-secret"
COMPLETE_PATH = "/internal/pay/mock/complete"


def sign_complete(pay_order_id, expected_amount_cents, secret=None, *,
                  timestamp=None, nonce=None):
    secret = secret or DEFAULT_SECRET
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    nonce = nonce or secrets.token_urlsafe(16)
    amount = "" if expected_amount_cents is None else str(expected_amount_cents)
    canonical = "\n".join(("POST", COMPLETE_PATH, str(pay_order_id), amount, timestamp, nonce))
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Mock-Pay-Timestamp": timestamp,
        "X-Mock-Pay-Nonce": nonce,
        "X-Mock-Pay-Signature": signature,
    }


def complete_headers(config, pay_order_id, expected_amount_cents=None):
    return sign_complete(pay_order_id, expected_amount_cents,
                         secret=config.get("SMARTLECT_MOCK_PAY_SECRET") or DEFAULT_SECRET)
