"""Live queries the investigation agent can run, with arguments it chooses.

The first version of the agent picked a name from a menu of six pre-computed
evidence slices. That is a decision, but it is a small one: the questions were
already answered before it was asked which one to read.

These are real queries. The agent supplies the arguments - which slice, which
window, which issuer, how far back - and the query runs against the payment
stream when it is asked. It can narrow a window it finds interesting, compare a
bank against its own history rather than against the global rate, and ask a
follow-up whose parameters depend on what the last answer said. That is the
difference between choosing a reading order and actually investigating.

Two constraints shape every probe here.

  A probe returns evidence with an id, and the groundedness check still runs
  against ids the agent actually received. Live queries do not loosen that -
  they widen what can be asked, not what can be claimed.

  Every probe is bounded. Windows are clamped, lookbacks are capped, and result
  sets are limited, because an agent that can write arbitrary parameters can
  also write a query that scans the table. The caps are not tuning knobs; they
  are the reason it is safe to let a model choose the numbers at all.

Nothing here can reach GroundTruth. These read the same columns any Razorpay
integration exposes - status, method, instrument, failure reason, timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from reversa.engines.evidence_engine import Evidence
from reversa.models import Payment, PaymentStatus

# Bounds. An agent choosing its own parameters needs a cage, not trust.
MAX_WINDOW_MINUTES = 240
MAX_LOOKBACK_DAYS = 14
MAX_GROUPS = 12

# Hard ceiling on queries per investigation, whatever the loop above asks for.
# compare_to_own_history costs two, so this is roughly eight questions.
MAX_PROBES_PER_INVESTIGATION = 10


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(int(value), hi))


def _slice_filter(stmt, method: str | None, instrument: str | None):
    """`*` and None both mean "do not constrain this dimension"."""
    if method and method != "*":
        stmt = stmt.where(Payment.method == method)
    if instrument and instrument != "*":
        stmt = stmt.where(Payment.instrument == instrument)
    return stmt


@dataclass(slots=True)
class ProbeResult:
    evidence: list[Evidence]
    summary: str

    def as_dict(self) -> dict:
        return {
            "summary": self.summary,
            "evidence": [e.as_dict() for e in self.evidence],
        }


class ProbeBudgetExceeded(RuntimeError):
    """The agent asked for more queries than one investigation is allowed."""


class Probes:
    """Bound to one incident's session and clock. Ids are unique per run.

    Clamping each parameter is not sufficient on its own: a hundred individually
    well-formed queries is still a hundred queries, and the caller deciding how
    many to run is a language model. The budget is the second half of the cage,
    and it is enforced here rather than in the loop above so that no future
    caller can forget it.
    """

    def __init__(
        self,
        session: Session,
        *,
        now: datetime,
        prefix: str = "pb",
        budget: int = MAX_PROBES_PER_INVESTIGATION,
    ) -> None:
        self.session = session
        self.now = now
        self._n = 0
        self._prefix = prefix
        self._budget = _clamp(budget, 1, MAX_PROBES_PER_INVESTIGATION)
        self.calls = 0

    @property
    def remaining(self) -> int:
        return max(0, self._budget - self.calls)

    def _spend(self, name: str) -> None:
        if self.calls >= self._budget:
            raise ProbeBudgetExceeded(
                f"{name} refused: {self.calls} probes already run, budget is "
                f"{self._budget}"
            )
        self.calls += 1

    def _id(self) -> str:
        self._n += 1
        return f"{self._prefix}_{self._n:03d}"

    # -- the probes ---------------------------------------------------------

    def auth_rate(
        self,
        *,
        method: str = "*",
        instrument: str = "*",
        window_minutes: int = 15,
        ends_at: datetime | None = None,
    ) -> ProbeResult:
        """Success rate for a slice over a window the agent picks.

        This is the probe that makes narrowing possible: having seen a method
        break, the agent can ask the same question of one instrument, or of a
        tighter window, and get a real answer rather than a pre-computed one.
        """
        self._spend("auth_rate")
        window = _clamp(window_minutes, 1, MAX_WINDOW_MINUTES)
        end = ends_at or self.now
        start = end - timedelta(minutes=window)

        stmt = select(
            func.count(Payment.id),
            func.sum(case((Payment.status == PaymentStatus.CAPTURED, 1), else_=0)),
        ).where(Payment.created_at >= start, Payment.created_at < end)
        n, ok = self.session.execute(_slice_filter(stmt, method, instrument)).one()
        n, ok = int(n or 0), int(ok or 0)

        label = f"{method}/{instrument} over {window}m to {end:%H:%M}"
        if n == 0:
            return ProbeResult([], f"no payments on {label}")

        rate = ok / n
        return ProbeResult(
            [Evidence(
                id=self._id(), kind="probe_auth_rate",
                label=f"Auth rate on {label}",
                source="payment_stream", observed=round(rate, 4),
                sample_size=n, confidence=1.0,
                detail={"method": method, "instrument": instrument,
                        "window_minutes": window, "successes": ok},
            )],
            f"{rate:.1%} of {n} payments captured on {label}",
        )

    def compare_to_own_history(
        self,
        *,
        method: str = "*",
        instrument: str = "*",
        window_minutes: int = 15,
        lookback_days: int = 7,
    ) -> ProbeResult:
        """This slice now, against the same slice over recent days.

        A rate means nothing without the slice's own normal. Comparing a
        netbanking handle to the global average says almost nothing; comparing
        it to what it did for the last week says whether today is unusual.
        """
        # Two queries run here - the nested auth_rate charges itself, and this
        # charges for the historical half. Billing one would understate what the
        # database actually did.
        self._spend("compare_to_own_history")
        window = _clamp(window_minutes, 1, MAX_WINDOW_MINUTES)
        days = _clamp(lookback_days, 1, MAX_LOOKBACK_DAYS)

        now_res = self.auth_rate(
            method=method, instrument=instrument, window_minutes=window,
        )
        if not now_res.evidence:
            return ProbeResult([], now_res.summary)
        current = now_res.evidence[0].observed or 0.0

        hist_start = self.now - timedelta(days=days)
        hist_end = self.now - timedelta(minutes=window)
        stmt = select(
            func.count(Payment.id),
            func.sum(case((Payment.status == PaymentStatus.CAPTURED, 1), else_=0)),
        ).where(Payment.created_at >= hist_start, Payment.created_at < hist_end)
        hn, hok = self.session.execute(_slice_filter(stmt, method, instrument)).one()
        hn, hok = int(hn or 0), int(hok or 0)

        if hn == 0:
            return ProbeResult([], f"{method}/{instrument} has no history in {days}d")

        baseline = hok / hn
        delta = current - baseline
        return ProbeResult(
            [Evidence(
                id=self._id(), kind="probe_vs_own_history",
                label=(f"{method}/{instrument} is at {current:.1%} against its own "
                       f"{days}-day norm of {baseline:.1%}"),
                source="payment_stream", observed=round(current, 4),
                baseline=round(baseline, 4), sample_size=hn, confidence=0.9,
                detail={"delta": round(delta, 4), "lookback_days": days},
            )],
            f"{current:.1%} now against {baseline:.1%} normally "
            f"({delta:+.1%}, n={hn} historical)",
        )

    def decline_reasons(
        self, *, method: str = "*", instrument: str = "*", window_minutes: int = 15,
    ) -> ProbeResult:
        """Which reason codes the declines carry, most common first."""
        self._spend("decline_reasons")
        window = _clamp(window_minutes, 1, MAX_WINDOW_MINUTES)
        start = self.now - timedelta(minutes=window)

        stmt = (
            select(Payment.failure_reason, func.count(Payment.id))
            .where(
                Payment.created_at >= start,
                Payment.created_at < self.now,
                Payment.failure_reason.is_not(None),
            )
            .group_by(Payment.failure_reason)
            .order_by(func.count(Payment.id).desc())
            .limit(MAX_GROUPS)
        )
        rows = self.session.execute(_slice_filter(stmt, method, instrument)).all()
        if not rows:
            return ProbeResult([], f"no declines on {method}/{instrument} in {window}m")

        total = sum(int(c) for _, c in rows)
        top_reason, top_count = rows[0][0], int(rows[0][1])
        share = top_count / total

        return ProbeResult(
            [Evidence(
                id=self._id(), kind="probe_reason_mix",
                label=(f"{share:.0%} of {total} declines on {method}/{instrument} "
                       f"are {top_reason}"),
                source="payment_stream", observed=round(share, 3),
                sample_size=total, confidence=0.9,
                detail={"reasons": {r: int(c) for r, c in rows}},
            )],
            "; ".join(f"{r} {int(c)}" for r, c in rows[:5]),
        )

    def sibling_instruments(
        self, *, method: str, window_minutes: int = 15,
    ) -> ProbeResult:
        """Every instrument on a method, ranked by how badly it is doing.

        This is what separates a rail fault from one issuer having a bad
        afternoon, and the agent has to ask it with a method in hand - which
        means it has to have decided which method matters first.
        """
        self._spend("sibling_instruments")
        window = _clamp(window_minutes, 1, MAX_WINDOW_MINUTES)
        start = self.now - timedelta(minutes=window)

        rows = self.session.execute(
            select(
                Payment.instrument,
                func.count(Payment.id),
                func.sum(case((Payment.status == PaymentStatus.CAPTURED, 1), else_=0)),
            )
            .where(
                Payment.method == method,
                Payment.created_at >= start,
                Payment.created_at < self.now,
            )
            .group_by(Payment.instrument)
            .order_by(func.count(Payment.id).desc())
            .limit(MAX_GROUPS)
        ).all()

        scored = [
            (inst, int(n), int(ok or 0), (int(ok or 0) / int(n)))
            for inst, n, ok in rows if int(n) >= 5
        ]
        if not scored:
            return ProbeResult([], f"not enough traffic on {method} in {window}m")

        scored.sort(key=lambda r: r[3])
        worst, best = scored[0], scored[-1]
        spread = best[3] - worst[3]
        affected = sum(1 for *_, rate in scored if rate < 0.6)

        return ProbeResult(
            [Evidence(
                id=self._id(), kind="probe_instrument_spread",
                label=(f"{affected} of {len(scored)} instruments on {method} are below "
                       f"60% (worst {worst[0]} at {worst[3]:.0%}, best {best[0]} "
                       f"at {best[3]:.0%})"),
                source="payment_stream", observed=float(affected),
                sample_size=sum(r[1] for r in scored), confidence=0.9,
                detail={"spread": round(spread, 3),
                        "per_instrument": {i: round(r, 4) for i, _, _, r in scored}},
            )],
            "; ".join(f"{i} {r:.0%} (n={n})" for i, n, _, r in scored[:6]),
        )


# What the model is shown. Parameters are described because it has to choose
# them, and the bounds are stated because a refused query wastes a step.
CATALOGUE: dict[str, dict[str, Any]] = {
    "auth_rate": {
        "asks": "Success rate for a slice over a window you choose.",
        "params": {
            "method": "payment method, or * for all",
            "instrument": "instrument within that method, or * for all",
            "window_minutes": f"1-{MAX_WINDOW_MINUTES}",
        },
    },
    "compare_to_own_history": {
        "asks": "That slice now, against what the same slice normally does.",
        "params": {
            "method": "payment method, or *",
            "instrument": "instrument, or *",
            "window_minutes": f"1-{MAX_WINDOW_MINUTES}",
            "lookback_days": f"1-{MAX_LOOKBACK_DAYS}",
        },
    },
    "decline_reasons": {
        "asks": "Which reason codes the declines carry, most common first.",
        "params": {
            "method": "payment method, or *",
            "instrument": "instrument, or *",
            "window_minutes": f"1-{MAX_WINDOW_MINUTES}",
        },
    },
    "sibling_instruments": {
        "asks": "Every instrument on one method, ranked worst first. Needs a method.",
        "params": {
            "method": "required - the method to break down",
            "window_minutes": f"1-{MAX_WINDOW_MINUTES}",
        },
    },
}
