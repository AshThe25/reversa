"""Scores Reversa against the world's hidden answer key.

This is the ONLY module allowed to read GroundTruth. tests/test_ground_truth_
isolation.py enforces that by walking the AST of everything else under reversa/.

Everything here answers one question: was the system right? Not "does the system
report a nice number" - the system reporting its own number is exactly what this
is meant to check.

Filled in during the evaluation phase; the loader below is what the isolation
test pins.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from reversa.models import GroundTruth


@dataclass(slots=True)
class TruthRow:
    payment_id: str
    incident_id: str | None
    root_cause: str
    p_natural: float
    best_action: str
    recovers_naturally: bool
    resolve: float
    p_by_action: dict


def load_truth(session: Session, payment_ids: list[str]) -> dict[str, TruthRow]:
    """Pull the answer key for a set of payments. Evaluation only."""
    if not payment_ids:
        return {}
    rows = session.execute(
        select(GroundTruth).where(GroundTruth.payment_id.in_(payment_ids))
    ).scalars().all()
    return {
        r.payment_id: TruthRow(
            payment_id=r.payment_id,
            incident_id=r.true_incident_id,
            root_cause=r.true_root_cause,
            p_natural=r.true_p_natural,
            best_action=r.true_best_action,
            recovers_naturally=r.recovers_naturally,
            resolve=r.resolve_u,
            p_by_action=r.true_p_by_action or {},
        )
        for r in rows
    }
