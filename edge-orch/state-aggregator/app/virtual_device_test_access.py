"""Expiring capabilities for this one test device; never valid as an operator token."""
import hashlib
import hmac
import secrets
import time

MAX_AGE = 86400
SCOPE = "virtual-device-test/vd-demo-001:start,infer,stop:"


def issue(secret: str, now: int | None = None) -> str:
    if not secret:
        raise ValueError("operator_key_required")
    expires = int(time.time() if now is None else now) + MAX_AGE
    head = f"vdtest.{expires}.{secrets.token_hex(16)}"
    signature = hmac.new(secret.encode(), (SCOPE + head).encode(), hashlib.sha256).hexdigest()
    return head + "." + signature


def verify(value: str | None, secret: str | None, now: int | None = None) -> bool:
    if not value or not secret or len(value) > 180:
        return False
    try:
        prefix, expiry, nonce, signature = value.split(".")
        expires = int(expiry)
    except (ValueError, TypeError):
        return False
    current = int(time.time() if now is None else now)
    if (prefix != "vdtest" or len(nonce) != 32 or len(signature) != 64
            or any(c not in "0123456789abcdef" for c in nonce + signature)
            or not current < expires <= current + MAX_AGE):
        return False
    head = f"{prefix}.{expiry}.{nonce}"
    expected = hmac.new(secret.encode(), (SCOPE + head).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
