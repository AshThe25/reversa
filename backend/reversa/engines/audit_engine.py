"""Append-only audit log, hash chained.

The agent moves money without a human in the loop, so "we logged it" isn't
enough — logs are editable. Each entry commits to the one before it, so if
anyone edits or reorders the trail, verification breaks at that row and stays
broken for everything after.

Hashing is over canonical JSON so you don't need this database (or Python) to
check it. Export the rows and recompute.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reversa.models import AuditEvent

log = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64


def _as_utc(value: datetime) -> datetime:
    """Normalise a timestamp for hashing.

    SQLite has no native timestamp type, so a `DateTime(timezone=True)` column
    round-trips as a *naive* datetime. Hashing the raw value would therefore
    make a freshly-written entry and the same entry read back produce different
    digests, and the chain would appear broken on every restart. Naive values
    are UTC by construction here, so we say so explicitly.
    """
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _canonical(payload: Any) -> str:
    """Deterministic JSON: sorted keys, no incidental whitespace, ASCII-safe."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _digest(
    entry_id: str,
    occurred_at: datetime,
    actor: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: dict,
    prev_hash: str,
) -> str:
    material = _canonical(
        {
            "id": entry_id,
            "occurred_at": _as_utc(occurred_at).isoformat(),
            "actor": actor,
            "event_type": event_type,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "payload": payload,
            "prev_hash": prev_hash,
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _head_hash(session: Session) -> str:
    row = session.execute(
        select(AuditEvent.entry_hash).order_by(AuditEvent.seq.desc()).limit(1)
    ).scalar_one_or_none()
    return row or GENESIS_HASH


MAX_APPEND_ATTEMPTS = 5


def record(
    session: Session,
    *,
    actor: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: dict | None = None,
    occurred_at: datetime | None = None,
) -> AuditEvent:
    """Append one entry, retrying if another writer got the head first.

    `actor` is the component that made the call - `policy`, `executor`,
    `sentinel`, `llm`, `human`. Attributing an action to the LLM when a
    deterministic rule actually made the call would defeat the point.

    Reading the head and inserting is not atomic, so two writers can read the
    same head and both link to it. `prev_hash` is unique, which turns that into
    an IntegrityError on the loser rather than a chain that silently forks into
    two branches each of which verifies on its own. We re-read and try again.
    """
    payload = payload or {}
    occurred_at = occurred_at or datetime.now(timezone.utc)

    for attempt in range(MAX_APPEND_ATTEMPTS):
        prev = _head_hash(session)
        entry_id = f"aud_{uuid.uuid4().hex[:20]}"
        entry = AuditEvent(
            id=entry_id,
            occurred_at=occurred_at,
            actor=actor,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
            prev_hash=prev,
            entry_hash=_digest(
                entry_id, occurred_at, actor, event_type,
                subject_type, subject_id, payload, prev,
            ),
        )
        savepoint = session.begin_nested()
        try:
            session.add(entry)
            session.flush()
            savepoint.commit()
            return entry
        except IntegrityError:
            savepoint.rollback()
            if attempt + 1 >= MAX_APPEND_ATTEMPTS:
                raise
            log.warning("audit append lost a race on the chain head, retrying")

    raise RuntimeError("unreachable")


@dataclass(slots=True)
class ChainVerdict:
    valid: bool
    entries_checked: int
    head_hash: str
    broken_at_seq: int | None = None
    reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "entries_checked": self.entries_checked,
            "head_hash": self.head_hash,
            "broken_at_seq": self.broken_at_seq,
            "reason": self.reason,
        }


def verify_chain(session: Session) -> ChainVerdict:
    """Recompute the whole chain and report the first divergence, if any."""
    rows = session.execute(
        select(AuditEvent).order_by(AuditEvent.seq.asc())
    ).scalars().all()

    expected_prev = GENESIS_HASH
    for row in rows:
        if row.prev_hash != expected_prev:
            return ChainVerdict(
                valid=False,
                entries_checked=len(rows),
                head_hash=expected_prev,
                broken_at_seq=row.seq,
                reason="prev_hash does not match the preceding entry's hash",
            )
        recomputed = _digest(
            row.id, row.occurred_at, row.actor, row.event_type,
            row.subject_type, row.subject_id, row.payload, row.prev_hash,
        )
        if recomputed != row.entry_hash:
            return ChainVerdict(
                valid=False,
                entries_checked=len(rows),
                head_hash=expected_prev,
                broken_at_seq=row.seq,
                reason="entry contents do not hash to the stored entry_hash",
            )
        expected_prev = row.entry_hash

    return ChainVerdict(
        valid=True, entries_checked=len(rows), head_hash=expected_prev
    )
