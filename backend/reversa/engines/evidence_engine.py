"""Turning a detected incident into addressable facts.

Every claim the investigator makes has to cite one of these by id. That is the
whole point of the module: a root-cause narrative is only worth reading if each
sentence can be traced to a measurement, and the cheapest way to enforce that is
to make the evidence a first-class object with an identity.

Two kinds of fact matter, and most systems only produce the first:

  *supporting* - the auth rate fell, one reason code dominates, downtime was
    published, the damage stayed inside one instrument;

  *contradicting* - the reason mix is split rather than concentrated, the
    degradation crosses slices with no common parent, no downtime was published
    for a rail that would normally publish it.

Collecting contradicting evidence is what allows the system to conclude nothing.
An investigator that only ever gathers support will always find a root cause,
which is exactly the failure mode that makes automated RCA untrustworthy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from reversa.engines.incident_engine import GLOBAL, DetectedIncident
from reversa.models import DowntimeRecord, Payment, PaymentStatus
from reversa.taxonomy import classify

# A reason code holding this share of the declines is a concentration worth
# reasoning about. Below it, the mix is telling you the cause is not singular.
CONCENTRATION_STRONG = 0.55
CONCENTRATION_WEAK = 0.35

# Error sources that point at infrastructure rather than the payer.
INFRA_SOURCES = {"bank", "gateway", "network", "issuer"}


@dataclass(slots=True)
class Evidence:
    id: str
    kind: str
    label: str
    source: str
    observed: float | None = None
    baseline: float | None = None
    unit: str = "ratio"
    sample_size: int = 0
    confidence: float = 0.0
    supports: str | None = None
    contradicts: str | None = None
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "source": self.source,
            "observed": self.observed,
            "baseline": self.baseline,
            "unit": self.unit,
            "sample_size": self.sample_size,
            "confidence": round(self.confidence, 3),
            "supports": self.supports,
            "contradicts": self.contradicts,
            "detail": self.detail,
        }

    def as_prompt_line(self) -> str:
        """One line for the model. Numbers, not adjectives."""
        parts = [f"[{self.id}] {self.label}"]
        if self.observed is not None and self.baseline is not None:
            parts.append(f"observed={self.observed:.4g} baseline={self.baseline:.4g}")
        elif self.observed is not None:
            parts.append(f"observed={self.observed:.4g}")
        if self.sample_size:
            parts.append(f"n={self.sample_size}")
        parts.append(f"source={self.source}")
        if self.supports:
            parts.append(f"supports={self.supports}")
        if self.contradicts:
            parts.append(f"contradicts={self.contradicts}")
        return " | ".join(parts)


# Root-cause hypotheses the system is willing to name. Anything outside this
# list is not a conclusion, it is a guess with better vocabulary.
HYPOTHESES = {
    "psp_switch_degradation": "PSP or switch degradation affecting a whole method",
    "issuer_authorisation_timeout": "Issuer-side authorisation timeouts",
    "bank_core_outage": "A single bank's core banking or netbanking outage",
    "merchant_side_latency": "Merchant-side latency or checkout fault",
    "INSUFFICIENT_EVIDENCE": "Evidence does not support any single root cause",
}


def collect(
    session: Session, incident: DetectedIncident, *, now: datetime
) -> list[Evidence]:
    """Gather every fact bearing on this incident's cause."""
    worst = incident.worst
    obs = worst.observation
    out: list[Evidence] = []
    n = 0

    def nid() -> str:
        nonlocal n
        n += 1
        return f"ev_{n:03d}"

    # --- the break itself ---------------------------------------------------
    out.append(Evidence(
        id=nid(), kind="auth_rate_drop",
        label=f"Auth rate on {incident.slice.label()} fell over {obs.window_minutes}m",
        source="payment_stream",
        observed=round(obs.success_rate, 4),
        baseline=round(worst.baseline_rate, 4),
        sample_size=obs.n,
        confidence=1.0 - min(worst.q_value, 1.0),
        supports="any",
        detail={"q_value": worst.q_value, "absolute_drop": round(worst.absolute_drop, 4)},
    ))

    # --- reason-code concentration -----------------------------------------
    failures = max(obs.n - obs.successes, 1)
    if obs.failures_by_reason:
        top_reason, top_count = max(obs.failures_by_reason.items(), key=lambda kv: kv[1])
        share = top_count / failures
        mode = classify(top_reason)
        infra = mode.source.value in INFRA_SOURCES

        if share >= CONCENTRATION_STRONG:
            out.append(Evidence(
                id=nid(), kind="error_concentration",
                label=f"{share:.0%} of declines carry a single reason code ({top_reason})",
                source="payment_stream", observed=round(share, 3),
                sample_size=failures, confidence=0.9,
                supports="psp_switch_degradation" if infra else "merchant_side_latency",
                detail={"reason": top_reason, "error_source": mode.source.value},
            ))
        elif share < CONCENTRATION_WEAK:
            out.append(Evidence(
                id=nid(), kind="error_dispersion",
                label=(
                    f"No reason code exceeds {share:.0%} of declines - the mix is "
                    "dispersed rather than concentrated"
                ),
                source="payment_stream", observed=round(share, 3),
                sample_size=failures, confidence=0.85,
                contradicts="any_single_infrastructure_cause",
                detail={"top_reason": top_reason, "distinct_reasons": len(obs.failures_by_reason)},
            ))

        # a split between merchant-side and issuer-side signatures is the
        # specific shape that makes attribution impossible
        by_source: dict[str, int] = {}
        for reason, count in obs.failures_by_reason.items():
            by_source[classify(reason).source.value] = (
                by_source.get(classify(reason).source.value, 0) + count
            )
        infra_share = sum(v for k, v in by_source.items() if k in INFRA_SOURCES) / failures
        if 0.35 <= infra_share <= 0.65:
            out.append(Evidence(
                id=nid(), kind="source_split",
                label=(
                    f"Declines split {infra_share:.0%} infrastructure / "
                    f"{1 - infra_share:.0%} customer-side - no dominant origin"
                ),
                source="payment_stream", observed=round(infra_share, 3),
                sample_size=failures, confidence=0.8,
                contradicts="any_single_infrastructure_cause",
                detail={"by_source": by_source},
            ))

    # --- scope --------------------------------------------------------------
    if incident.is_diffuse:
        out.append(Evidence(
            id=nid(), kind="scope_uncontained",
            label=(
                f"Degradation appears on {len(incident.diffuse_members)} slices with "
                "no common parent"
            ),
            source="incident_engine", observed=float(len(incident.diffuse_members)),
            unit="slices", confidence=0.95,
            contradicts="psp_switch_degradation",
            detail={"members": list(incident.diffuse_members)},
        ))
    elif worst.rolled_up_from:
        out.append(Evidence(
            id=nid(), kind="scope_method_wide",
            label=(
                f"All {len(worst.rolled_up_from)} instruments on "
                f"{incident.slice.method.upper()} degraded together"
            ),
            source="incident_engine", observed=float(len(worst.rolled_up_from)),
            unit="instruments", confidence=0.92,
            supports="psp_switch_degradation",
            detail={"instruments": list(worst.rolled_up_from)},
        ))
    elif incident.slice.instrument != GLOBAL:
        out.append(Evidence(
            id=nid(), kind="scope_contained",
            label=(
                f"Degradation is contained to {incident.slice.instrument}; sibling "
                "instruments on the same method are unaffected"
            ),
            source="incident_engine", confidence=0.9,
            supports="bank_core_outage",
            detail={"instrument": incident.slice.instrument},
        ))

    # --- platform corroboration --------------------------------------------
    downtime = _overlapping_downtime(session, incident)
    if downtime is not None:
        lag = (downtime.begin - incident.first_seen).total_seconds() / 60
        out.append(Evidence(
            id=nid(), kind="downtime_corroboration",
            label=(
                f"Razorpay published downtime for {downtime.method}/{downtime.instrument}"
                f" ({'before' if lag < 0 else 'after'} detection by {abs(lag):.0f}m)"
            ),
            source="razorpay_downtime_api", observed=round(lag, 1), unit="minutes",
            confidence=0.95,
            supports="psp_switch_degradation",
            detail={"severity": downtime.severity, "scheduled": downtime.scheduled},
        ))
    else:
        out.append(Evidence(
            id=nid(), kind="no_downtime_published",
            label=(
                "No platform downtime published for this rail during the window"
            ),
            source="razorpay_downtime_api", confidence=0.7,
            contradicts="psp_switch_degradation",
            detail={},
        ))

    # --- cross-method reach -------------------------------------------------
    reach = _cross_method_reach(session, incident, now=now)
    if reach and len(reach) > 1:
        out.append(Evidence(
            id=nid(), kind="cross_method_reach",
            label=(
                f"Auth rate is depressed on {len(reach)} payment methods "
                "simultaneously, which no single rail explains"
            ),
            source="payment_stream", observed=float(len(reach)), unit="methods",
            confidence=0.85,
            supports="merchant_side_latency",
            contradicts="bank_core_outage",
            detail={"methods": reach},
        ))

    return out


def _overlapping_downtime(
    session: Session, incident: DetectedIncident
) -> DowntimeRecord | None:
    rows = session.execute(select(DowntimeRecord)).scalars().all()
    for d in rows:
        if d.scheduled:
            continue
        if incident.slice.method != GLOBAL and d.method not in (incident.slice.method, "*"):
            continue
        if (
            incident.slice.instrument != GLOBAL
            and d.instrument not in (incident.slice.instrument, "ALL", "*")
        ):
            continue
        end = d.end or incident.last_seen
        if d.begin <= incident.last_seen and end >= incident.first_seen:
            return d
    return None


# A method has to fall this far below its OWN norm to count as depressed.
CROSS_METHOD_DROP = 0.08
CROSS_METHOD_MIN_VOLUME = 60


def _cross_method_reach(
    session: Session, incident: DetectedIncident, *, now: datetime
) -> list[str]:
    """Which methods were depressed during the window, against their own norm.

    Against their own norm, not a fixed threshold. The first version compared
    every method to a flat 0.80 and, since baseline auth rates sit at 85-88%,
    almost any busy window dipped one or more methods under it - so this
    evidence fired on nearly every incident and pushed otherwise-attributable
    ones toward INSUFFICIENT_EVIDENCE. A signal that is always on is not a
    signal.
    """
    start, end = incident.first_seen - timedelta(minutes=10), incident.last_seen

    def rates(lo: datetime, hi: datetime) -> dict[str, tuple[int, float]]:
        rows = session.execute(
            select(
                Payment.method,
                func.count(),
                func.sum(case((Payment.status == PaymentStatus.CAPTURED, 1), else_=0)),
            )
            .where(Payment.created_at >= lo, Payment.created_at < hi)
            .group_by(Payment.method)
        ).all()
        return {
            m: (int(n), (float(ok or 0) / float(n)) if n else 0.0) for m, n, ok in rows
        }

    window = rates(start, end)
    # the rest of the live day is the comparison, so seasonality is roughly
    # shared and we are not comparing a peak window to an overnight baseline
    day_start = end.replace(hour=0, minute=0, second=0, microsecond=0)
    reference = rates(day_start, now)

    depressed = []
    for method, (n, rate) in window.items():
        if n < CROSS_METHOD_MIN_VOLUME:
            continue
        ref_n, ref_rate = reference.get(method, (0, 0.0))
        if ref_n < CROSS_METHOD_MIN_VOLUME:
            continue
        if ref_rate - rate >= CROSS_METHOD_DROP:
            depressed.append(method)
    return depressed
