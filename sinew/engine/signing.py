"""Signed ingest: the sender signs `timestamp.body` with the shared key; we reject bad or old signatures."""

import hashlib
import hmac
import time

from sinew import config

MAX_SKEW_SECONDS = 300


def _key() -> bytes:
    key = config.env("INGEST_SIGNING_KEY")
    if not key:
        raise RuntimeError("INGEST_SIGNING_KEY is not set")
    return key.encode()


def sign(body: bytes, timestamp: int) -> str:
    return hmac.new(_key(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def verify(body: bytes, timestamp: str | None, signature: str | None) -> bool:
    if not timestamp or not signature or not timestamp.isdigit():
        return False
    if abs(time.time() - int(timestamp)) > MAX_SKEW_SECONDS:
        return False
    return hmac.compare_digest(sign(body, int(timestamp)), signature)
