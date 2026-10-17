import hashlib
import hmac

from smartlect.pay_signature import sign_complete


def test_signature_matches_java_canonical_string():
    secret = "0123456789abcdef0123456789abcdef"
    headers = sign_complete("pay-1", 9000, secret, timestamp=1700000000, nonce="nonce-1234")
    canonical = "POST\n/internal/pay/mock/complete\npay-1\n9000\n1700000000\nnonce-1234"
    expected = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    assert headers["X-Mock-Pay-Signature"] == expected
    assert headers["X-Mock-Pay-Timestamp"] == "1700000000"
    assert headers["X-Mock-Pay-Nonce"] == "nonce-1234"


def test_empty_amount_is_signed_as_empty_field():
    headers = sign_complete("pay-1", None, "s" * 32, timestamp=1700000000, nonce="nonce-5678")
    canonical = "POST\n/internal/pay/mock/complete\npay-1\n\n1700000000\nnonce-5678"
    expected = hmac.new(("s" * 32).encode(), canonical.encode(), hashlib.sha256).hexdigest()
    assert headers["X-Mock-Pay-Signature"] == expected
