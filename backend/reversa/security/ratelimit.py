"""Rate limiting.

Token bucket per (identity, route class). Buckets over fixed windows because a
fixed window lets a caller fire 2x the limit across a window boundary, and the
expensive endpoints here - a wind tunnel run is a linear program over thousands
of candidates - are exactly where that burst hurts.

Route classes rather than one global limit: reading the incident list is cheap
and should be generous, running an optimisation is not. A single number for both
is either too tight to use or too loose to protect anything.

In-memory, which is right for one process and wrong for a fleet. A real
deployment swaps `_buckets` for Redis; the interface does not change. Saying so
because a limiter that silently resets per replica is security theatre.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Limit:
    capacity: int      # burst
    refill_per_second: float
    label: str

    @property
    def per_minute(self) -> float:
        return self.refill_per_second * 60


# Tuned for one operator driving a dashboard, not for a crawler.
LIMITS: dict[str, Limit] = {
    "read":    Limit(capacity=120, refill_per_second=2.0,  label="120 burst, 120/min"),
    "compute": Limit(capacity=8,   refill_per_second=0.15, label="8 burst, 9/min"),
    "write":   Limit(capacity=20,  refill_per_second=0.5,  label="20 burst, 30/min"),
    "ai":      Limit(capacity=6,   refill_per_second=0.1,  label="6 burst, 6/min"),
    "webhook": Limit(capacity=200, refill_per_second=20.0, label="200 burst, 1200/min"),
}
DEFAULT_CLASS = "read"


@dataclass(slots=True)
class Decision:
    allowed: bool
    remaining: int
    retry_after: float
    limit: Limit


class RateLimiter:
    def __init__(self, limits: dict[str, Limit] | None = None, max_keys: int = 50_000):
        self.limits = limits or LIMITS
        self.max_keys = max_keys
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}
        self._lock = threading.Lock()

    def check(self, identity: str, route_class: str = DEFAULT_CLASS, *, cost: float = 1.0) -> Decision:
        limit = self.limits.get(route_class, self.limits[DEFAULT_CLASS])
        key = (identity, route_class)
        now = time.monotonic()

        with self._lock:
            if len(self._buckets) > self.max_keys:
                # bounded memory: an attacker rotating identities must not be
                # able to grow this without limit
                self._evict(now)

            tokens, last = self._buckets.get(key, (float(limit.capacity), now))
            tokens = min(limit.capacity, tokens + (now - last) * limit.refill_per_second)

            if tokens >= cost:
                self._buckets[key] = (tokens - cost, now)
                return Decision(True, int(tokens - cost), 0.0, limit)

            self._buckets[key] = (tokens, now)
            deficit = cost - tokens
            return Decision(
                False, 0, round(deficit / limit.refill_per_second, 2), limit
            )

    def _evict(self, now: float) -> None:
        """Drop buckets that have refilled to capacity - they carry no state."""
        keep: dict[tuple[str, str], tuple[float, float]] = {}
        for key, (tokens, last) in self._buckets.items():
            limit = self.limits.get(key[1], self.limits[DEFAULT_CLASS])
            refilled = min(limit.capacity, tokens + (now - last) * limit.refill_per_second)
            if refilled < limit.capacity:
                keep[key] = (tokens, last)
        self._buckets = keep

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
