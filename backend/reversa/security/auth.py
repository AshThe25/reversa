"""Session tokens.

HMAC-signed, stateless, short-lived. Not JWT - this needs one algorithm, one
key, and no negotiation, and JWT's flexibility is mostly a source of CVEs
(`alg: none`, algorithm confusion, unverified `kid` lookups). A fixed
`v1.<payload>.<mac>` format has no room for a caller to choose the algorithm.

Verification is constant-time. String equality on a MAC leaks the position of
the first differing byte through timing, which is enough to forge one given
patience and a loop.

Scopes exist because reading the incident list and running the optimiser are not
the same privilege. A read token cannot execute a strategy, so an XSS that lifts
one from a viewer's browser still cannot move money.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from enum import StrEnum

TOKEN_VERSION = "v1"
DEFAULT_TTL_SECONDS = 8 * 3600


class Scope(StrEnum):
    READ = "read"
    """Look at incidents, cohorts, audit trail."""

    SIMULATE = "simulate"
    """Run the wind tunnel. Compute-heavy but touches nothing."""

    EXECUTE = "execute"
    """Deploy a strategy and move money. Never granted to a demo session."""

    ADMIN = "admin"


READ_ONLY = (Scope.READ,)
OPERATOR = (Scope.READ, Scope.SIMULATE, Scope.EXECUTE)
DEMO = (Scope.READ, Scope.SIMULATE)
"""What a walk-up visitor gets. Deliberately excludes EXECUTE: the demo can
explore every future it likes without being able to commit one."""


class AuthError(Exception):
    """Rejected. The reason is logged, never returned - telling a caller whether
    the signature or the expiry failed hands them an oracle."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Session:
    subject: str
    scopes: tuple[str, ...]
    issued_at: int
    expires_at: int
    session_id: str

    def has(self, scope: str) -> bool:
        return scope in self.scopes or Scope.ADMIN in self.scopes

    @property
    def expires_in(self) -> int:
        return max(0, self.expires_at - int(time.time()))

    def as_dict(self) -> dict:
        return {
            "subject": self.subject,
            "scopes": list(self.scopes),
            "session_id": self.session_id,
            "expires_at": self.expires_at,
            "expires_in": self.expires_in,
        }


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(payload: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def issue(
    subject: str,
    scopes: tuple[str, ...],
    secret: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: int | None = None,
) -> tuple[str, Session]:
    if not secret or len(secret) < 16:
        raise AuthError("session secret is missing or too short")

    now = now or int(time.time())
    session = Session(
        subject=subject,
        scopes=tuple(str(s) for s in scopes),
        issued_at=now,
        expires_at=now + ttl_seconds,
        session_id=secrets.token_urlsafe(12),
    )
    body = _b64(json.dumps({
        "sub": session.subject, "scp": list(session.scopes),
        "iat": session.issued_at, "exp": session.expires_at,
        "sid": session.session_id,
    }, separators=(",", ":"), sort_keys=True).encode())
    payload = f"{TOKEN_VERSION}.{body}"
    return f"{payload}.{_mac(payload, secret)}", session


def verify(token: str | None, secret: str, *, now: int | None = None) -> Session:
    if not token:
        raise AuthError("missing token")
    if not secret:
        raise AuthError("no session secret configured; refusing to authenticate")

    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_VERSION:
        raise AuthError("malformed token")

    version, body, mac = parts
    payload = f"{version}.{body}"
    if not hmac.compare_digest(_mac(payload, secret), mac):
        raise AuthError("bad signature")

    try:
        claims = json.loads(_unb64(body))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AuthError(f"unreadable claims: {exc}") from exc

    now = now or int(time.time())
    exp = int(claims.get("exp", 0))
    if now >= exp:
        raise AuthError("expired")
    if int(claims.get("iat", 0)) > now + 60:
        raise AuthError("issued in the future")

    return Session(
        subject=str(claims.get("sub", "")),
        scopes=tuple(claims.get("scp", ())),
        issued_at=int(claims.get("iat", 0)),
        expires_at=exp,
        session_id=str(claims.get("sid", "")),
    )


def require(session: Session, scope: str) -> None:
    if not session.has(scope):
        raise AuthError(f"session lacks scope {scope}")


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
