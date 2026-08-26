"""Webhook intake.

Razorpay signs webhooks with HMAC-SHA256 over the raw request body, sent in
`X-Razorpay-Signature`. Three things have to be right or the endpoint is a
liability:

Signature. Compared with `hmac.compare_digest`, never `==`. Byte-by-byte string
comparison leaks the position of the first mismatch through timing, which is
enough to forge a signature given patience.

Raw bytes. The HMAC is over exactly what was sent. Parsing JSON and re-encoding
it changes key order and whitespace, and the signature stops matching for a
reason that takes an afternoon to find. The verifier only ever takes bytes.

Replay. A valid signature stays valid forever. Without a freshness window and a
seen-event store, anyone who captures one payment.captured webhook can replay it
until the money is refunded twice. Event ids are stored and re-delivery is
acknowledged as a no-op, because Razorpay retries on non-2xx and a duplicate
must be cheap, not fatal.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

# How stale a signed payload may be. Razorpay retries for a while, so this is
# generous enough to survive a redeploy but short enough that a captured request
# is not useful tomorrow.
MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_AGE = timedelta(minutes=30)
MAX_BODY_BYTES = 1_000_000


class WebhookRejected(Exception):
    """Verification failed. The reason is logged but never returned to the caller.

    Telling an attacker whether they got the signature wrong, the timestamp
    wrong, or the event id wrong hands them an oracle. Callers get 400.
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class VerifiedEvent:
    event_id: str
    event_type: str
    created_at: datetime
    payload: dict[str, Any]
    replayed: bool = False


class SeenEvents:
    """Idempotency store for delivered event ids.

    In-memory with a TTL, which is correct for one process and wrong for a fleet
    - a real deployment backs this with Redis SETNX or a unique index on
    (event_id) in Postgres. The interface is the same either way; only `_store`
    changes. Calling that out because an in-memory idempotency check that silently
    does nothing behind a load balancer is worse than none at all.
    """

    def __init__(self, ttl: timedelta = timedelta(hours=24), max_entries: int = 100_000):
        self.ttl = ttl
        self.max_entries = max_entries
        self._store: dict[str, float] = {}
        self._lock = threading.Lock()

    def seen(self, event_id: str) -> bool:
        """Record the id. True if we had already seen it."""
        now = time.monotonic()
        cutoff = now - self.ttl.total_seconds()
        with self._lock:
            if len(self._store) > self.max_entries:
                self._store = {k: v for k, v in self._store.items() if v > cutoff}
            previous = self._store.get(event_id)
            self._store[event_id] = now
            return previous is not None and previous > cutoff


def _expected_signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify(
    body: bytes,
    signature: str | None,
    secret: str | None,
    *,
    seen: SeenEvents | None = None,
    now: datetime | None = None,
) -> VerifiedEvent:
    """Verify one webhook delivery, or raise WebhookRejected."""
    if not secret:
        raise WebhookRejected("no webhook secret configured; refusing to accept")
    if not signature:
        raise WebhookRejected("missing signature header")
    if len(body) > MAX_BODY_BYTES:
        raise WebhookRejected(f"body exceeds {MAX_BODY_BYTES} bytes")

    expected = _expected_signature(body, secret)
    if not hmac.compare_digest(expected, signature.strip()):
        raise WebhookRejected("signature mismatch")

    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise WebhookRejected(f"body is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise WebhookRejected("body is not a JSON object")

    event_type = payload.get("event")
    if not isinstance(event_type, str) or not event_type:
        raise WebhookRejected("missing event type")

    created_raw = payload.get("created_at")
    if not isinstance(created_raw, (int, float)):
        raise WebhookRejected("missing or malformed created_at")
    created = datetime.fromtimestamp(float(created_raw), tz=timezone.utc)

    now = now or datetime.now(timezone.utc)
    if created - now > MAX_CLOCK_SKEW:
        raise WebhookRejected("created_at is in the future beyond allowed skew")
    if now - created > MAX_AGE:
        raise WebhookRejected("payload is older than the replay window")

    # Razorpay does not guarantee a top-level event id on every event, so fall
    # back to a digest of the signed body. Same delivery -> same digest, which is
    # exactly the idempotency key we want.
    event_id = payload.get("id") or f"sha256:{hashlib.sha256(body).hexdigest()[:32]}"

    replayed = bool(seen and seen.seen(str(event_id)))
    if replayed:
        log.info("webhook %s (%s) already processed, acknowledging as no-op",
                 event_id, event_type)

    return VerifiedEvent(
        event_id=str(event_id),
        event_type=event_type,
        created_at=created,
        payload=payload,
        replayed=replayed,
    )


def sign(body: bytes, secret: str) -> str:
    """Produce a valid signature. Tests and the simulation adapter only."""
    return _expected_signature(body, secret)
