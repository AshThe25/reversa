"""Turning a detected incident into a set of decisions.

Takes the slice and window the detector flagged, finds the payments it actually
put at risk, and attaches everything needed to decide what to do about each one:
estimated counterfactuals, which actions compliance allows, and what the money is
worth.

Two things here are less obvious than they look.

*Cohort membership is a claim, not a lookup.* Not every failure inside an
incident window was caused by the incident - the baseline failure rate keeps
running underneath. So membership carries the incident's excess-failure rate as
an attribution weight, and the exception list records the payments we could not
attribute. Treating every in-window failure as incident-caused is how revenue
exposure gets overstated, which is the number the whole pitch rests on.

*Contact actions are restricted to one payment per customer, chosen here rather
than in the optimiser.* It keeps the optimiser's constraint matrix totally
unimodular, and operationally it is just correct - you message a person about
their largest stuck payment, not four times about four.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reversa.config import Settings, get_settings
from reversa.engines import policy_gates as G
from reversa.engines.counterfactual_engine import (
    CounterfactualModel, Features, features_for,
)
from reversa.engines.incident_engine import DetectedIncident, GLOBAL
from reversa.engines.portfolio_optimizer import CONTACT_ACTIONS, Candidate
from reversa.models import (
    ActionType, Customer, DowntimeRecord, Payment, PaymentStatus,
)

# Actions the system is allowed to consider at all. WAIT and NO_ACTION are not
# in here because they are the absence of an action, not a choice with capacity.
CONSIDERED_ACTIONS: tuple[str, ...] = (
    ActionType.RETRY_NOW,
    ActionType.RETRY_DELAYED,
    ActionType.SWITCH_METHOD,
    ActionType.PAYMENT_LINK,
    ActionType.NUDGE_SMS,
    ActionType.NUDGE_WHATSAPP,
    ActionType.NUDGE_EMAIL,
    ActionType.VOICE_CALL,
)


@dataclass(slots=True)
class Exception_:
    """A payment we could not act on, and why. Surfaced, never swallowed."""

    payment_id: str
    amount_paise: int
    reason: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "payment_id": self.payment_id,
            "amount_paise": self.amount_paise,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(slots=True)
class CohortBuild:
    incident_slice: str
    window_start: datetime
    window_end: datetime
    candidates: list[Candidate] = field(default_factory=list)
    exceptions: list[Exception_] = field(default_factory=list)

    in_window_payments: int = 0
    rail_down_now: bool = False
    attribution_weight: float = 1.0
    """Share of in-window failures the incident is responsible for, from the
    observed rate against the pre-incident baseline."""

    build_ms: float = 0.0

    @property
    def revenue_exposed_paise(self) -> int:
        return sum(c.amount_paise for c in self.candidates)

    @property
    def attributable_exposure_paise(self) -> int:
        """Exposure discounted by how much of it the incident actually caused."""
        return int(round(self.revenue_exposed_paise * self.attribution_weight))

    @property
    def natural_recovery_paise(self) -> int:
        return int(round(sum(c.amount_paise * c.p_natural for c in self.candidates)))

    @property
    def addressable_paise(self) -> int:
        """Exposure minus what arrives on its own. The only part worth spending on."""
        return self.revenue_exposed_paise - self.natural_recovery_paise

    def exceptions_by_reason(self) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for e in self.exceptions:
            out[e.reason] += 1
        return dict(out)

    def as_dict(self) -> dict:
        return {
            "slice": self.incident_slice,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "in_window_payments": self.in_window_payments,
            "member_count": len(self.candidates),
            "attribution_weight": round(self.attribution_weight, 4),
            "rail_down_now": self.rail_down_now,
            "revenue_exposed_paise": self.revenue_exposed_paise,
            "attributable_exposure_paise": self.attributable_exposure_paise,
            "natural_recovery_paise": self.natural_recovery_paise,
            "addressable_paise": self.addressable_paise,
            "exceptions": len(self.exceptions),
            "exceptions_by_reason": self.exceptions_by_reason(),
            "build_ms": round(self.build_ms, 1),
        }


def build_cohort(
    session: Session,
    incident: DetectedIncident,
    model: CounterfactualModel,
    *,
    now: datetime,
    settings: Settings | None = None,
    lookback_pad_minutes: int = 5,
) -> CohortBuild:
    """Assemble the decision set for one detected incident."""
    started = time.perf_counter()
    settings = settings or get_settings()

    worst = incident.worst
    window_start = worst.observation.window_start - timedelta(minutes=lookback_pad_minutes)
    window_end = max(incident.last_seen, worst.observation.window_end)

    build = CohortBuild(
        incident_slice=incident.slice.key,
        window_start=window_start,
        window_end=window_end,
    )


    q = (
        select(Payment, Customer)
        .join(Customer, Customer.id == Payment.customer_id)
        .where(
            Payment.status == PaymentStatus.FAILED,
            Payment.created_at >= window_start,
            Payment.created_at < window_end,
        )
    )
    if incident.slice.method != GLOBAL:
        q = q.where(Payment.method == incident.slice.method)
    if incident.slice.instrument != GLOBAL:
        q = q.where(Payment.instrument == incident.slice.instrument)

    rows = session.execute(q).all()
    build.in_window_payments = len(rows)
    build.attribution_weight = _attribution_weight(
        session, incident, window_start, window_end, len(rows)
    )
    if not rows:
        build.build_ms = (time.perf_counter() - started) * 1000
        return build

    downtimes = session.execute(select(DowntimeRecord)).scalars().all()
    index = G.ComplianceIndex.load(session, [c.id for _, c in rows])

    # one contact per customer: whoever has the largest stuck payment.
    # single pass - the first version re-scanned `rows` inside this loop, which
    # is O(n^2) and cost 2.3s on a 1,800-payment cohort.
    best_payment_for: dict[str, tuple[str, int]] = {}
    for payment, _ in rows:
        cur = best_payment_for.get(payment.customer_id)
        if cur is None or payment.amount_paise > cur[1]:
            best_payment_for[payment.customer_id] = (payment.id, payment.amount_paise)

    # Two different questions, and conflating them silently killed every
    # contact action in the first run.
    #
    #   failed_during_downtime -> was the rail degraded when this payment failed?
    #                             a FEATURE, it tells the estimator why it failed.
    #   rail_down_now          -> is the rail degraded at decision time?
    #                             a GATE input, it decides whether acting is safe.
    #
    # The gate was being fed the first one, so an incident that ended 50 minutes
    # ago still blocked every payment link in the cohort - the system refused to
    # act precisely when acting had become safe again.
    rail_down_now = _rail_down_at(downtimes, incident, now)
    build.rail_down_now = rail_down_now

    for payment, customer in rows:
        # every cohort member failed inside a slice the detector flagged - that
        # IS the in_incident feature, and it is the same label the estimator was
        # fitted on
        feats = features_for(payment, customer, in_incident=True)
        est = model.estimate(feats, actions=CONSIDERED_ACTIONS)

        subject = G.GateSubject(
            payment_id=payment.id,
            customer=customer,
            amount_paise=payment.amount_paise,
            failure_reason=payment.failure_reason,
            failure_class=payment.failure_class or "unknown",
            method=payment.method,
            instrument=payment.instrument,
            failed_at=payment.created_at,
            deadline_at=payment.created_at + timedelta(days=settings.case_ttl_days),
            incident_ended_at=window_end,
            credit_linked=False,
        )
        ctx = G.GateContext(
            subject=subject, now=now, settings=settings,
            index=index, instrument_down=rail_down_now,
        )

        holder = best_payment_for.get(payment.customer_id)
        allows_contact = holder is not None and holder[0] == payment.id
        eligible: list[str] = []
        blocked: dict[str, str] = {}
        for action in CONSIDERED_ACTIONS:
            if action in CONTACT_ACTIONS and not allows_contact:
                blocked[action] = "another payment from this customer holds the contact slot"
                continue
            report = G.evaluate(action, ctx)
            if report.allowed:
                eligible.append(action)
            else:
                blocked[action] = report.reason or "blocked"

        if not eligible:
            build.exceptions.append(Exception_(
                payment_id=payment.id, amount_paise=payment.amount_paise,
                reason=_dominant_block(blocked),
                detail="; ".join(sorted(set(blocked.values())))[:240],
            ))
            continue

        build.candidates.append(Candidate(
            payment_id=payment.id,
            customer_id=payment.customer_id,
            amount_paise=payment.amount_paise,
            failure_class=payment.failure_class or "unknown",
            p_natural=est.p_natural,
            confidence=est.confidence,
            uplift={a: u.delta for a, u in est.uplift.items()},
            uplift_credible={a: u.credible for a, u in est.uplift.items()},
            eligible=tuple(eligible),
            method=payment.method,
            instrument=payment.instrument,
            tier=customer.tier,
        ))

    build.build_ms = (time.perf_counter() - started) * 1000
    return build


def _attribution_weight(
    session: Session,
    incident: DetectedIncident,
    start: datetime,
    end: datetime,
    observed_failures: int,
) -> float:
    """What share of the in-window failures the incident is actually responsible for.

    The baseline failure rate keeps running underneath an incident, so a window
    that is wider than the true degradation picks up ordinary failures too. The
    first version took this from the *peak* signal's rates, which overstated it
    badly whenever the detected span outran the real one - and revenue exposure
    is the number the entire pitch rests on.

    Now: expected baseline failures over the actual cohort window, subtracted
    from what we saw. weight = excess / observed.
    """
    if observed_failures <= 0:
        return 0.0

    q = select(func.count()).select_from(Payment).where(
        Payment.created_at >= start, Payment.created_at < end
    )
    if incident.slice.method != GLOBAL:
        q = q.where(Payment.method == incident.slice.method)
    if incident.slice.instrument != GLOBAL:
        q = q.where(Payment.instrument == incident.slice.instrument)
    total = session.execute(q).scalar() or 0
    if total <= 0:
        return 0.0

    baseline_rate = incident.worst.baseline_rate
    expected_failures = total * (1.0 - baseline_rate)
    excess = observed_failures - expected_failures
    return float(max(0.0, min(1.0, excess / observed_failures)))


def _dominant_block(blocked: dict[str, str]) -> str:
    """The single reason most worth showing an operator."""
    joined = " ".join(blocked.values()).lower()
    for needle, label in (
        ("human review", "requires_human_review"),
        ("complaint", "frozen_complaint"),
        ("opted out", "opted_out"),
        ("consent", "no_consent"),
        ("downtime", "rail_degraded"),
        ("terminal", "instrument_dead"),
        ("deadline", "past_deadline"),
        ("contact", "contact_budget"),
    ):
        if needle in joined:
            return label
    return "all_actions_blocked"


def _rail_down_at(
    downtimes: Sequence[DowntimeRecord],
    incident: DetectedIncident,
    when: datetime,
) -> bool:
    """Is this incident's rail degraded right now?

    Suppression is about whether it is safe to act at this instant, not about
    what happened when the payment failed.
    """
    for d in downtimes:
        if incident.slice.method != GLOBAL and d.method not in (incident.slice.method, "*"):
            continue
        if (incident.slice.instrument != GLOBAL
                and d.instrument not in (incident.slice.instrument, "ALL", "*")):
            continue
        if d.begin <= when and (d.end is None or when <= d.end):
            return True
    return False


def _in_incident(downtimes: Sequence[DowntimeRecord], payment: Payment) -> bool:
    for d in downtimes:
        if d.method not in (payment.method, "*"):
            continue
        if d.instrument not in (payment.instrument, "ALL", "*"):
            continue
        end = d.end or payment.created_at
        if d.begin <= payment.created_at <= end:
            return True
    return False
