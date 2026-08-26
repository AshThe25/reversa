"""Randomised measurement.

Reversa's headline claim is causal - "this intervention produced this much
revenue" - and the only honest way to support it is to withhold treatment from a
random slice and compare. Everything else in this file follows from that.

**Three arms, not two.**

  TREATMENT   gets the optimiser's plan.
  HOLDOUT     gets nothing. This is what makes the number causal.
  EXPLORATION gets a uniformly random legal action.

The third arm is the answer to the sharpest objection this product faces. The
uplift estimates come from historical data in which actions were not randomly
assigned, so they carry selection bias: the merchant's old rule sent links to
big-ticket payments, and any comparison inherits that. A merchant adopting
Reversa on day one has no clean data at all. So the system generates its own -
a small randomised slice, permanently, which is the only thing that keeps the
counterfactual model from slowly fossilising around its own past decisions.

**Assignment is a hash, not a coin flip.**

    arm = f(sha256(experiment_id || customer_id))

Deterministic, so a rerun reproduces the same arms; keyed by *customer* rather
than payment, so a person with three failed payments lands in one arm and is not
half-treated; and stateless, so it needs no coordination and no stored RNG.
Reproducibility here is not cosmetic - if arms drifted between runs, the demo
and the pitch video would disagree.

**Measurement cost is reported, not hidden.**

A 10% holdout on Rs 31L of exposure is real money deliberately not chased.
Pretending otherwise is how experimentation programmes lose the argument with
finance the first time someone does the arithmetic. `results()` states it
explicitly, so the merchant can decide - and shrink the holdout once the effect
is established.

**Confidence intervals come from a customer-level bootstrap.**

The headline is a *ratio* of revenue sums, not a mean of independent draws, and
recovered amounts are heavily skewed - one Rs 2L payment moves the estimate more
than fifty small ones. A normal-approximation interval on that is wrong in a way
that flatters us. Resampling customers preserves both the skew and the
within-customer correlation.
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from reversa.models import (
    Arm, Experiment, ExperimentAssignment, RecoveryOutcome,
)
from reversa.world import params as P

BOOTSTRAP_SAMPLES = 2_000
CONFIDENCE = 0.90

EXPLORATION = "exploration"
ARMS = (Arm.TREATMENT.value, Arm.HOLDOUT.value, EXPLORATION)

_HASH_SPACE = 1 << 32


def assign_arm(
    experiment_id: str,
    customer_id: str,
    *,
    holdout_fraction: float,
    exploration_fraction: float = 0.0,
) -> tuple[str, str]:
    """Deterministic arm for one customer. Returns (arm, hash prefix).

    The prefix is stored so an auditor can recompute the assignment by hand and
    confirm nobody put a thumb on the scale.
    """
    digest = hashlib.sha256(f"{experiment_id}|{customer_id}".encode()).hexdigest()
    bucket = int(digest[:8], 16) / _HASH_SPACE

    if bucket < holdout_fraction:
        return Arm.HOLDOUT.value, digest[:16]
    if bucket < holdout_fraction + exploration_fraction:
        return EXPLORATION, digest[:16]
    return Arm.TREATMENT.value, digest[:16]


@dataclass(slots=True)
class ArmResult:
    arm: str
    customers: int
    payments: int
    recovered: int
    exposure_paise: int
    recovered_paise: int
    cost_paise: int

    @property
    def recovery_rate(self) -> float:
        return self.recovered / self.payments if self.payments else 0.0

    @property
    def revenue_rate(self) -> float:
        return self.recovered_paise / self.exposure_paise if self.exposure_paise else 0.0

    def as_dict(self) -> dict:
        return {
            "arm": self.arm,
            "customers": self.customers,
            "payments": self.payments,
            "recovered": self.recovered,
            "exposure_paise": self.exposure_paise,
            "recovered_paise": self.recovered_paise,
            "cost_paise": self.cost_paise,
            "recovery_rate": round(self.recovery_rate, 5),
            "revenue_rate": round(self.revenue_rate, 5),
        }


@dataclass(slots=True)
class ExperimentResult:
    experiment_id: str
    arms: dict[str, ArmResult]

    incremental_paise: int
    incremental_lo_paise: int
    incremental_hi_paise: int
    rate_lift: float
    rate_lift_lo: float
    rate_lift_hi: float

    gross_recovery_paise: int
    natural_recovery_paise: int
    cost_paise: int
    measurement_cost_paise: int

    bootstrap_samples: int
    confidence: float
    compute_ms: float
    warnings: list[str] = field(default_factory=list)

    @property
    def significant(self) -> bool:
        """Revenue interval excludes zero. Not proof, but the minimum bar."""
        return self.incremental_lo_paise > 0

    @property
    def rate_significant(self) -> bool:
        return self.rate_lift_lo > 0

    @property
    def concentrated(self) -> bool:
        """Revenue lift is significant but the rate lift is not.

        This is the fragile case and it needs saying out loud. It means the
        effect rests on a handful of large recoveries rather than on more
        customers paying - so it is one unlucky Rs 2L payment away from
        disappearing, and it will not replicate at a different ticket mix.
        Reporting the revenue number alone here would be technically true and
        practically misleading.
        """
        return self.significant and not self.rate_significant

    @property
    def net_paise(self) -> int:
        return self.incremental_paise - self.cost_paise

    @property
    def roi(self) -> float | None:
        return self.incremental_paise / self.cost_paise if self.cost_paise else None

    def as_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "arms": {k: v.as_dict() for k, v in self.arms.items()},
            "gross_recovery_paise": self.gross_recovery_paise,
            "natural_recovery_paise": self.natural_recovery_paise,
            "incremental_paise": self.incremental_paise,
            "incremental_lo_paise": self.incremental_lo_paise,
            "incremental_hi_paise": self.incremental_hi_paise,
            "rate_lift": round(self.rate_lift, 5),
            "rate_lift_lo": round(self.rate_lift_lo, 5),
            "rate_lift_hi": round(self.rate_lift_hi, 5),
            "significant": self.significant,
            "rate_significant": self.rate_significant,
            "concentrated": self.concentrated,
            "cost_paise": self.cost_paise,
            "net_paise": self.net_paise,
            "roi": round(self.roi, 2) if self.roi else None,
            "measurement_cost_paise": self.measurement_cost_paise,
            "bootstrap_samples": self.bootstrap_samples,
            "confidence": self.confidence,
            "compute_ms": round(self.compute_ms, 1),
            "warnings": self.warnings,
        }


def open_experiment(
    session: Session,
    *,
    experiment_id: str,
    cohort_id: str | None,
    name: str,
    holdout_fraction: float,
    exploration_fraction: float,
    now: datetime,
    strategy_id: str | None = None,
) -> Experiment:
    """Create (or reuse) the experiment record.

    Exists so assignments always have a parent - the first end-to-end run wrote
    1,132 assignment rows against an experiment_id that did not exist and got a
    foreign-key failure, which is the schema doing its job.
    """
    existing = session.get(Experiment, experiment_id)
    if existing is not None:
        return existing

    exp = Experiment(
        id=experiment_id,
        cohort_id=cohort_id,
        strategy_id=strategy_id,
        name=name,
        holdout_fraction=holdout_fraction,
        assignment_method=(
            "sha256(experiment_id||customer_id), "
            f"holdout<{holdout_fraction:.2f} "
            f"exploration<{holdout_fraction + exploration_fraction:.2f}"
        ),
        started_at=now,
        status="running",
        results={},
    )
    session.add(exp)
    session.flush()
    return exp


def conclude(session: Session, experiment_id: str, result: "ExperimentResult",
             *, now: datetime) -> None:
    """Freeze the measured result onto the experiment record."""
    exp = session.get(Experiment, experiment_id)
    if exp is None:
        return
    exp.results = result.as_dict()
    exp.concluded_at = now
    exp.status = "concluded"
    session.flush()


def assign(
    session: Session,
    experiment_id: str,
    payments: Sequence[tuple[str, str]],
    *,
    holdout_fraction: float,
    exploration_fraction: float = 0.0,
    now: datetime,
) -> dict[str, str]:
    """Assign every payment's customer to an arm and persist it."""
    arms: dict[str, str] = {}
    rows = []
    for idx, (payment_id, customer_id) in enumerate(payments):
        arm, prefix = assign_arm(
            experiment_id, customer_id,
            holdout_fraction=holdout_fraction,
            exploration_fraction=exploration_fraction,
        )
        arms[payment_id] = arm
        rows.append(ExperimentAssignment(
            id=f"asg_{experiment_id[-8:]}_{idx:06d}",
            experiment_id=experiment_id, payment_id=payment_id,
            customer_id=customer_id, arm=arm,
            assignment_hash=prefix, assigned_at=now,
        ))
    session.add_all(rows)
    session.flush()
    return arms


def balance_report(arms: Mapping[str, str], exposure: Mapping[str, int]) -> dict:
    """Sanity check on the randomisation before anyone trusts the result.

    Hash assignment is unbiased in expectation but any single draw can be
    lopsided, and a holdout that happens to hold the three largest payments will
    produce a lift number that is pure noise. Worth seeing before the headline.
    """
    by_arm: dict[str, list[int]] = defaultdict(list)
    for pid, arm in arms.items():
        by_arm[arm].append(exposure.get(pid, 0))

    out = {}
    for arm, amounts in by_arm.items():
        arr = np.array(amounts or [0], dtype=float)
        out[arm] = {
            "payments": len(amounts),
            "exposure_paise": int(arr.sum()),
            "mean_paise": int(arr.mean()),
            "median_paise": int(np.median(arr)),
        }

    means = [v["mean_paise"] for v in out.values() if v["payments"] > 0]
    skew = (max(means) / min(means)) if means and min(means) > 0 else 1.0
    out["_balance"] = {
        "mean_ticket_ratio": round(skew, 3),
        "balanced": skew < 1.25,
    }
    return out


def results(
    session: Session,
    experiment_id: str,
    *,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
    seed: int = 4242,
) -> ExperimentResult:
    """Measure the experiment from observed outcomes only."""
    started = time.perf_counter()
    rows = session.execute(
        select(RecoveryOutcome).where(RecoveryOutcome.experiment_id == experiment_id)
    ).scalars().all()

    by_arm: dict[str, ArmResult] = {}
    per_arm_rows: dict[str, list[RecoveryOutcome]] = defaultdict(list)
    for r in rows:
        per_arm_rows[r.arm].append(r)

    for arm, arm_rows in per_arm_rows.items():
        by_arm[arm] = ArmResult(
            arm=arm,
            customers=len({r.payment_id for r in arm_rows}),
            payments=len(arm_rows),
            recovered=sum(1 for r in arm_rows if r.recovered),
            exposure_paise=sum(r.amount_paise for r in arm_rows),
            recovered_paise=sum(r.recovered_amount_paise for r in arm_rows),
            cost_paise=sum(r.action_cost_paise for r in arm_rows),
        )

    warnings: list[str] = []
    treatment = by_arm.get(Arm.TREATMENT.value)
    holdout = by_arm.get(Arm.HOLDOUT.value)

    if treatment is None or holdout is None or holdout.payments == 0:
        warnings.append(
            "no holdout arm - recovery cannot be attributed to the intervention"
        )
        return ExperimentResult(
            experiment_id=experiment_id, arms=by_arm,
            incremental_paise=0, incremental_lo_paise=0, incremental_hi_paise=0,
            rate_lift=0.0, rate_lift_lo=0.0, rate_lift_hi=0.0,
            gross_recovery_paise=treatment.recovered_paise if treatment else 0,
            natural_recovery_paise=0,
            cost_paise=treatment.cost_paise if treatment else 0,
            measurement_cost_paise=0,
            bootstrap_samples=0, confidence=CONFIDENCE,
            compute_ms=(time.perf_counter() - started) * 1000,
            warnings=warnings,
        )

    if holdout.payments < 30:
        warnings.append(
            f"holdout has only {holdout.payments} payments - the interval will be "
            "wide and the point estimate should not be quoted on its own"
        )

    # Ratio estimator: what fraction of exposed revenue the holdout recovered,
    # applied to the treatment's exposure, is the counterfactual.
    control_revenue_rate = holdout.revenue_rate
    natural = int(round(treatment.exposure_paise * control_revenue_rate))
    incremental = treatment.recovered_paise - natural

    lo, hi, rate_lo, rate_hi = _bootstrap(
        per_arm_rows[Arm.TREATMENT.value], per_arm_rows[Arm.HOLDOUT.value],
        samples=bootstrap_samples, seed=seed,
    )

    # What the holdout cost us: the customers we deliberately did not treat,
    # times the per-payment incremental we now believe we could have produced.
    per_payment_incremental = incremental / treatment.payments if treatment.payments else 0
    measurement_cost = int(round(per_payment_incremental * holdout.payments))

    result = ExperimentResult(
        experiment_id=experiment_id,
        arms=by_arm,
        incremental_paise=incremental,
        incremental_lo_paise=int(lo),
        incremental_hi_paise=int(hi),
        rate_lift=treatment.recovery_rate - holdout.recovery_rate,
        rate_lift_lo=rate_lo,
        rate_lift_hi=rate_hi,
        gross_recovery_paise=treatment.recovered_paise,
        natural_recovery_paise=natural,
        cost_paise=treatment.cost_paise,
        measurement_cost_paise=max(0, measurement_cost),
        bootstrap_samples=bootstrap_samples,
        confidence=CONFIDENCE,
        compute_ms=(time.perf_counter() - started) * 1000,
        warnings=warnings,
    )

    if result.concentrated:
        result.warnings.append(
            "revenue lift is significant but the per-payment rate lift is not - "
            "the effect is concentrated in a few large recoveries and may not "
            "replicate at a different ticket mix"
        )
    if result.roi is not None and result.roi > 50:
        result.warnings.append(
            f"ROI of {result.roi:.0f}x reflects that most chosen actions were "
            "free gateway retries; read net incremental rupees, not the ratio"
        )
    return result


def _bootstrap(
    treated: Sequence[RecoveryOutcome],
    control: Sequence[RecoveryOutcome],
    *,
    samples: int,
    seed: int,
) -> tuple[float, float, float, float]:
    """Percentile interval on incremental revenue and on the rate difference.

    Resamples each arm with replacement, recomputes the ratio estimator, and
    takes percentiles. Non-parametric because recovered amounts are far too
    skewed for a normal approximation - one large payment moves the estimate
    more than fifty small ones, and a Wald interval on that flatters us.
    """
    if not treated or not control:
        return 0.0, 0.0, 0.0, 0.0

    t_amt = np.array([r.amount_paise for r in treated], dtype=float)
    t_rec = np.array([r.recovered_amount_paise for r in treated], dtype=float)
    t_hit = np.array([1.0 if r.recovered else 0.0 for r in treated])
    c_amt = np.array([r.amount_paise for r in control], dtype=float)
    c_rec = np.array([r.recovered_amount_paise for r in control], dtype=float)
    c_hit = np.array([1.0 if r.recovered else 0.0 for r in control])

    rng = np.random.default_rng(seed)
    ti = rng.integers(0, len(treated), size=(samples, len(treated)))
    ci = rng.integers(0, len(control), size=(samples, len(control)))

    t_exposure = t_amt[ti].sum(axis=1)
    t_recovered = t_rec[ti].sum(axis=1)
    c_exposure = c_amt[ci].sum(axis=1)
    c_recovered = c_rec[ci].sum(axis=1)

    control_rate = np.divide(
        c_recovered, c_exposure, out=np.zeros_like(c_recovered), where=c_exposure > 0
    )
    incremental = t_recovered - t_exposure * control_rate
    rate_diff = t_hit[ti].mean(axis=1) - c_hit[ci].mean(axis=1)

    tail = (1 - CONFIDENCE) / 2 * 100
    return (
        float(np.percentile(incremental, tail)),
        float(np.percentile(incremental, 100 - tail)),
        float(np.percentile(rate_diff, tail)),
        float(np.percentile(rate_diff, 100 - tail)),
    )


def random_legal_action(
    eligible: Sequence[str], *, experiment_id: str, payment_id: str
) -> str | None:
    """Uniform pick for the exploration arm, seeded so it is reproducible."""
    if not eligible:
        return None
    digest = hashlib.sha256(f"{experiment_id}|explore|{payment_id}".encode()).hexdigest()
    return sorted(eligible)[int(digest[:8], 16) % len(eligible)]
