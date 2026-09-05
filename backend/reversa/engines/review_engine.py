"""Human review, for the actions that warrant one.

The obvious way to build a review queue is to put every proposed action in it.
That produces a queue of several hundred rows before lunch, which a human
clears by clicking approve until their hand hurts. A rubber stamp is worse than
no gate at all: it adds latency, and it launders an automated decision as a
human one in the audit trail.

So the queue is a judgement about which decisions actually need a person, and
the judgement is deterministic and stated:

  Anything the customer sees needs a human. A gateway retry is invisible and
  reversible - the payer never knows it happened. A payment link, an SMS, a
  WhatsApp message or a call arrives in someone's life, cannot be recalled, and
  spends a budget that is capped for a reason.

  Anything unusually large needs a human, contacting or not, because the cost of
  being wrong scales with the amount and a review is cheap against it.

  Anything resting on an unresolved cause needs a human. If the investigation
  returned INSUFFICIENT_EVIDENCE, the plan built on it is a guess with good
  arithmetic, and a person should see the guess before it is acted on.

Everything else is auto-approved, and the reason is recorded as explicitly as a
human decision would be. "Nobody looked at this" and "this did not require
looking at" are different claims, and the audit trail should be able to tell
them apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Sequence

from reversa.engines.policy_gates import PAYER_CONTACTING
from reversa.models import ActionType

if TYPE_CHECKING:
    from reversa.engines.portfolio_optimizer import Assignment, Candidate

# Above this, a human sees it whatever the channel. Two lakh is not a universal
# threshold - it is this merchant's, roughly the 99th percentile of their order
# value, and it belongs in configuration the day a second merchant exists.
HIGH_VALUE_PAISE = 20_000_00


class ReviewReason(StrEnum):
    """Why this decision did or did not reach a person."""

    CUSTOMER_CONTACT = "customer_contact"
    HIGH_VALUE = "high_value"
    UNRESOLVED_CAUSE = "unresolved_cause"
    # ...and the auto-approval reasons, which are recorded rather than implied.
    SILENT_AND_REVERSIBLE = "silent_and_reversible"
    NO_ACTION = "no_action"


REQUIRES_HUMAN = frozenset({
    ReviewReason.CUSTOMER_CONTACT,
    ReviewReason.HIGH_VALUE,
    ReviewReason.UNRESOLVED_CAUSE,
})

REASON_TEXT: dict[str, str] = {
    ReviewReason.CUSTOMER_CONTACT:
        "Reaches the customer directly and cannot be recalled once sent.",
    ReviewReason.HIGH_VALUE:
        f"Above the ₹{HIGH_VALUE_PAISE // 100:,} review threshold for this merchant.",
    ReviewReason.UNRESOLVED_CAUSE:
        "The investigation could not attribute a cause, so this plan rests on an "
        "unexplained break.",
    ReviewReason.SILENT_AND_REVERSIBLE:
        "A gateway retry. The payer never sees it and nothing is spent.",
    ReviewReason.NO_ACTION:
        "No treatment proposed.",
}


class Decision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"


@dataclass(frozen=True, slots=True)
class Triage:
    reason: ReviewReason
    needs_human: bool

    @property
    def explanation(self) -> str:
        return REASON_TEXT[self.reason]

    def as_dict(self) -> dict:
        return {
            "reason": str(self.reason),
            "needs_human": self.needs_human,
            "explanation": self.explanation,
        }


def triage(
    action: str,
    *,
    amount_paise: int,
    cause_resolved: bool = True,
) -> Triage:
    """Decide whether a person must see this action before it happens.

    Order matters: the reason recorded should be the most serious one that
    applies, because that is the one a reviewer needs to read first.
    """
    if action in (ActionType.NO_ACTION, ActionType.WAIT):
        return Triage(ReviewReason.NO_ACTION, needs_human=False)

    if action in PAYER_CONTACTING:
        return Triage(ReviewReason.CUSTOMER_CONTACT, needs_human=True)

    if amount_paise >= HIGH_VALUE_PAISE:
        return Triage(ReviewReason.HIGH_VALUE, needs_human=True)

    if not cause_resolved:
        return Triage(ReviewReason.UNRESOLVED_CAUSE, needs_human=True)

    return Triage(ReviewReason.SILENT_AND_REVERSIBLE, needs_human=False)


@dataclass(slots=True)
class ReviewCase:
    """One proposed action, and what a reviewer needs in order to judge it."""

    payment_id: str
    customer_id: str
    action: str
    amount_paise: int
    expected_incremental_paise: int
    baseline_recovery_probability: float
    triage: Triage
    decision: str = Decision.PENDING
    decided_by: str | None = None
    note: str | None = None

    def as_dict(self) -> dict:
        return {
            "payment_id": self.payment_id,
            "customer_id": self.customer_id,
            "action": str(self.action),
            "amount_paise": self.amount_paise,
            "expected_incremental_paise": self.expected_incremental_paise,
            "baseline_recovery_probability": round(self.baseline_recovery_probability, 4),
            "decision": str(self.decision),
            "decided_by": self.decided_by,
            "note": self.note,
            **self.triage.as_dict(),
        }


def build_queue(
    assignments: "Sequence[Assignment]",
    candidates: "Sequence[Candidate]",
    *,
    cause_resolved: bool = True,
    limit: int = 40,
) -> list[ReviewCase]:
    """Turn a plan into a review queue, worst-first.

    Sorted by expected incremental value rather than by amount: the review that
    matters most is the one where the most is riding on the decision, and that
    is not the same as the biggest payment. A large payment that was going to
    recover on its own carries almost no incremental value, and putting it at
    the top of a reviewer's queue spends the scarcest thing in the loop, which
    is their attention.

    The amount lives on the candidate and the action lives on the assignment, so
    both are needed. An assignment with no matching candidate is a bug rather
    than a case to skip quietly, and it raises.
    """
    by_id = {c.payment_id: c for c in candidates}
    cases: list[ReviewCase] = []

    for a in assignments:
        cand = by_id.get(a.payment_id)
        if cand is None:
            raise KeyError(
                f"assignment {a.payment_id} has no candidate; the plan and the "
                "cohort have diverged"
            )
        t = triage(
            str(a.action),
            amount_paise=cand.amount_paise,
            cause_resolved=cause_resolved,
        )
        cases.append(ReviewCase(
            payment_id=a.payment_id,
            customer_id=a.customer_id,
            action=str(a.action),
            amount_paise=cand.amount_paise,
            expected_incremental_paise=a.expected_incremental_paise,
            baseline_recovery_probability=a.p_natural,
            triage=t,
            decision=Decision.PENDING if t.needs_human else Decision.AUTO_APPROVED,
        ))

    cases.sort(key=lambda x: -x.expected_incremental_paise)
    return cases[:limit]


def summarise(cases: list[ReviewCase]) -> dict:
    """Counts a reviewer wants before they start clicking."""
    pending = [c for c in cases if c.decision == Decision.PENDING]
    auto = [c for c in cases if c.decision == Decision.AUTO_APPROVED]
    by_reason: dict[str, int] = {}
    for c in pending:
        by_reason[str(c.triage.reason)] = by_reason.get(str(c.triage.reason), 0) + 1
    return {
        "total": len(cases),
        "pending": len(pending),
        "auto_approved": len(auto),
        "pending_value_paise": sum(c.expected_incremental_paise for c in pending),
        "auto_value_paise": sum(c.expected_incremental_paise for c in auto),
        "by_reason": by_reason,
    }

