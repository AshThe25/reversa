"""Estimating what would have happened anyway.

This is the load-bearing model in the whole product. Everything downstream -
which customers the optimiser picks, what the wind tunnel projects, whether an
intervention was worth its cost - reduces to one quantity:

    p_natural = P(this payment recovers | we do nothing)

and one difference:

    uplift(a) = P(recovers | action a) - p_natural

If p_natural is wrong, Reversa spends contact capacity on people who were going
to pay anyway and reports it as recovered revenue. That is precisely the failure
mode the product exists to call out, so getting this honest matters more than
getting it clever.

**Why a hierarchical rate model and not a gradient-boosted classifier.**

Three reasons, in order of how much they mattered.

Calibration beats discrimination here. The optimiser subtracts two
probabilities. A model that ranks well but is off in level produces confidently
wrong *differences*, and a difference of two badly-calibrated numbers is noise
with a decimal point. Beta-binomial cell rates are calibrated by construction.

It has to be explainable to a merchant who is about to spend money on it. Every
estimate traces to "412 comparable historical failures in this cell, shrunk
toward a parent of 3,880". The evidence graph can render that. A tree ensemble's
SHAP plot cannot be defended in a dispute.

It degrades honestly. A cell with n=3 comes back with a wide posterior, the
optimiser sees low confidence, and the policy gate can refuse. A neural net
returns 0.83 with the same face either way.

**Two design choices worth flagging.**

*Trained on the training era only.* The live day is a genuine temporal holdout -
the model has never seen it. Fitting on all data and reporting accuracy on all
data would be circular, and it is the most common way these numbers get faked.

*Uplift is estimated on the headroom scale.* Rather than modelling an absolute
Delta, we model what fraction of the remaining headroom an action captures:

    relative_uplift = (r_treated - r_control) / (1 - r_control)
    Delta_i         = relative_uplift * (1 - p_natural_i)

This encodes something true and otherwise easy to get wrong: you cannot add 20
points to someone already at 0.90. Modelling absolute uplift lets the optimiser
believe it can, and it will then happily spend a payment link on the customer
least able to benefit from one. The world's generative model damps uplift the
same way, but the estimator does not know that - it is a modelling assumption
that has to earn its place in the calibration report.

Uplift also shrinks toward *zero*, not toward the parent's mean, when evidence
is thin. An unproven intervention should look worthless, not average.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Sequence

from scipy import stats
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reversa.models import (
    Customer, DowntimeRecord, Payment, PaymentEvent, PaymentStatus, RunEra,
)

# Shrinkage strengths, in units of "pseudo-observations". A cell needs roughly
# this many real observations before it outvotes its parent.
KAPPA_NATURAL = 30.0
KAPPA_UPLIFT = 45.0        # uplift is a difference, so it needs more evidence

# Below this, an uplift cell is treated as carrying no information at all.
MIN_TREATED_FOR_UPLIFT = 12

# Prior on relative uplift, centred at zero. An intervention is assumed useless
# until the data says otherwise, and this sets how much data that takes. 0.30
# means "a priori, an action plausibly captures somewhere in +/-30% of the
# remaining headroom" - generous enough not to fight real effects, tight enough
# that a 12-observation arm cannot claim one.
UPLIFT_PRIOR_SD = 0.30

CREDIBLE_MASS = 0.90
_Z = 1.6449   # two-sided 90%

AMOUNT_BUCKETS_PAISE: tuple[int, ...] = (
    50_000, 2_00_000, 10_00_000, 50_00_000,
)
AMOUNT_LABELS = ("<500", "500-2k", "2k-10k", "10k-50k", "50k+")


def amount_bucket(paise: int) -> str:
    for i, edge in enumerate(AMOUNT_BUCKETS_PAISE):
        if paise < edge:
            return AMOUNT_LABELS[i]
    return AMOUNT_LABELS[-1]


@dataclass(frozen=True, slots=True)
class Features:
    """Everything the estimator is allowed to know about one failed payment.

    All observable from a Razorpay integration plus the merchant's own history.
    Nothing here comes from the simulator's hidden state - see
    tests/test_ground_truth_isolation.py, which enforces that.
    """

    failure_class: str
    method: str
    amount_paise: int
    tier: str
    in_downtime: bool
    prior_recovery_rate: float = 0.42
    prior_failures: int = 0

    @property
    def bucket(self) -> str:
        return amount_bucket(self.amount_paise)

    # cell keys, coarsest last
    def natural_keys(self) -> tuple[str, ...]:
        """Finest first."""
        return (
            f"{self.failure_class}|{self.method}|{self.bucket}|{self.tier}|{int(self.in_downtime)}",
            f"{self.failure_class}|{self.method}|{self.bucket}",
            f"{self.failure_class}",
        )

    def strata(self) -> tuple[str, ...]:
        """Population strata, finest first.

        Paired one-for-one with `uplift_keys` below. Treated and control counts
        MUST come from the same level of this hierarchy or the "uplift" is just
        a difference in population mix - see `_estimate_uplift`.
        """
        return (
            f"{self.failure_class}|{self.bucket}",
            f"{self.failure_class}",
            "_",
        )

    def uplift_keys(self, action: str) -> tuple[str, ...]:
        return (
            f"{action}|{self.failure_class}|{self.bucket}",
            f"{action}|{self.failure_class}",
            f"{action}",
        )


@dataclass(slots=True)
class Cell:
    n: float = 0.0
    k: float = 0.0

    @property
    def rate(self) -> float:
        return self.k / self.n if self.n else 0.0

    def add(self, success: bool, weight: float = 1.0) -> None:
        self.n += weight
        if success:
            self.k += weight


@dataclass(frozen=True, slots=True)
class UpliftEstimate:
    action: str
    delta: float
    lo: float
    hi: float
    relative: float
    treated_n: int
    control_n: int
    source_cell: str

    @property
    def credible(self) -> bool:
        """Is the effect distinguishable from zero at our credible mass?

        The optimiser is allowed to use non-credible estimates only if the
        action is free. Spending a voice call on an effect we cannot tell from
        zero is how recovery programmes burn money and goodwill at once.
        """
        return self.lo > 0.0

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "delta": round(self.delta, 5),
            "lo": round(self.lo, 5),
            "hi": round(self.hi, 5),
            "relative": round(self.relative, 5),
            "treated_n": self.treated_n,
            "control_n": self.control_n,
            "credible": self.credible,
            "source_cell": self.source_cell,
        }


@dataclass(slots=True)
class Estimate:
    p_natural: float
    p_natural_lo: float
    p_natural_hi: float
    support_n: int
    source_cell: str
    shrunk_from: str
    uplift: dict[str, UpliftEstimate] = field(default_factory=dict)

    @property
    def headroom(self) -> float:
        return 1.0 - self.p_natural

    @property
    def confidence(self) -> float:
        """0-1, from how tight the natural-recovery posterior is.

        A wide posterior is the signal the policy gate keys on to demand human
        review, so this has to reflect evidence, not vibes.
        """
        width = max(self.p_natural_hi - self.p_natural_lo, 1e-6)
        return float(max(0.0, min(1.0, 1.0 - width / 0.6)))

    def expected_incremental_paise(self, action: str, amount_paise: int) -> int:
        u = self.uplift.get(action)
        return int(round(amount_paise * u.delta)) if u else 0

    def best_action(self, allowed: Iterable[str] | None = None) -> str | None:
        pool = [u for a, u in self.uplift.items() if allowed is None or a in allowed]
        pool = [u for u in pool if u.delta > 0]
        return max(pool, key=lambda u: u.delta).action if pool else None

    def as_dict(self) -> dict:
        return {
            "p_natural": round(self.p_natural, 5),
            "p_natural_lo": round(self.p_natural_lo, 5),
            "p_natural_hi": round(self.p_natural_hi, 5),
            "support_n": self.support_n,
            "confidence": round(self.confidence, 4),
            "source_cell": self.source_cell,
            "shrunk_from": self.shrunk_from,
            "uplift": {a: u.as_dict() for a, u in self.uplift.items()},
        }


def _shrunk_mean(k: float, n: float, prior_rate: float, kappa: float) -> float:
    """Posterior mean only. The interval costs two beta.ppf calls, which is fine
    once but not 16,000 times while building a cohort."""
    return (k + kappa * prior_rate) / max(n + kappa, 1e-9)


def _beta_interval(k: float, n: float, prior_rate: float, kappa: float) -> tuple[float, float, float]:
    """Posterior mean and credible interval for a shrunk rate."""
    a = k + kappa * prior_rate
    b = (n - k) + kappa * (1.0 - prior_rate)
    a, b = max(a, 1e-6), max(b, 1e-6)
    mean = a / (a + b)
    tail = (1.0 - CREDIBLE_MASS) / 2.0
    return float(mean), float(stats.beta.ppf(tail, a, b)), float(stats.beta.ppf(1 - tail, a, b))


class CounterfactualModel:
    """Hierarchical empirical-Bayes estimator for natural recovery and uplift."""

    def __init__(self) -> None:
        self.natural: dict[str, Cell] = defaultdict(Cell)
        self.treated: dict[str, Cell] = defaultdict(Cell)
        self.control_for_uplift: dict[str, Cell] = defaultdict(Cell)
        self.global_natural: Cell = Cell()
        self.actions: tuple[str, ...] = ()
        self.fit_rows: int = 0
        self.fit_until: datetime | None = None

    # -- fitting ------------------------------------------------------------

    @classmethod
    def fit(cls, session: Session, *, until: datetime, era: str = RunEra.TRAINING) -> "CounterfactualModel":
        """Fit on history strictly before `until`.

        The live day is never in here. That is what makes the calibration report
        on the Evaluation page mean anything - the model is scored on a day it
        has never seen, the same way it would face tomorrow in production.
        """
        model = cls()
        model.fit_until = until

        # what we did, if anything, per payment. our own action log.
        action_rows = session.execute(
            select(PaymentEvent.payment_id, PaymentEvent.payload)
            .where(PaymentEvent.event_type == "recovery.attempted")
        ).all()
        actions: dict[str, str] = {
            pid: payload.get("action") for pid, payload in action_rows if payload
        }

        downtimes = session.execute(select(DowntimeRecord)).scalars().all()

        rows = session.execute(
            select(
                Payment.id, Payment.failure_class, Payment.method,
                Payment.instrument, Payment.amount_paise, Payment.status,
                Payment.created_at, Customer.tier,
                Customer.prior_failures, Customer.prior_natural_recoveries,
            )
            .join(Customer, Customer.id == Payment.customer_id)
            .where(
                Payment.status.in_((PaymentStatus.FAILED, PaymentStatus.RECOVERED)),
                Payment.created_at < until,
                Payment.era == era,
            )
        ).all()

        seen_actions: set[str] = set()
        for (pid, fclass, method, instrument, amount, status,
             created, tier, pf, pnr) in rows:
            if not fclass:
                continue
            recovered = status == PaymentStatus.RECOVERED
            in_dt = _covered_by_downtime(downtimes, created, method, instrument)
            feats = Features(
                failure_class=fclass, method=method, amount_paise=amount,
                tier=tier or "casual", in_downtime=in_dt,
            )
            action = actions.get(pid)
            model.fit_rows += 1

            if action:
                seen_actions.add(action)
                for key in feats.uplift_keys(action):
                    model.treated[key].add(recovered)
            else:
                # untreated: the control group for both models
                for key in feats.natural_keys():
                    model.natural[key].add(recovered)
                model.global_natural.add(recovered)
                # control counts at exactly the strata the uplift cells use,
                # so treated and control can back off together
                for key in feats.strata():
                    model.control_for_uplift[key].add(recovered)

        model.actions = tuple(sorted(seen_actions))
        return model

    # -- prediction ---------------------------------------------------------

    def estimate_natural(self, f: Features) -> Estimate:
        """Walk the hierarchy coarse to fine, each level shrunk toward the one above.

        The subtle bug this replaces: the first version tracked the running prior
        and the chosen cell in the same variable, so by the last iteration they
        were equal and the final shrinkage fell back to the *global* rate. An
        infra_transient cell with n=3 was being pulled toward 0.38 instead of
        toward its own class parent at 0.77 - a 34-point error on exactly the
        class where over-intervening is most wasteful.
        """
        grand = self.global_natural.rate or 0.35
        prior, prior_label = grand, "global"
        best = (self.global_natural, grand, 0, "global", "global")

        for key in reversed(f.natural_keys()):     # coarse -> fine
            cell = self.natural.get(key)
            if cell is None or cell.n == 0:
                continue
            # only the surviving (finest) cell needs an interval
            mean = _shrunk_mean(cell.k, cell.n, prior, KAPPA_NATURAL)
            best = (cell, prior, int(cell.n), key, prior_label)
            prior, prior_label = mean, key

        cell, cell_prior, n, key, parent = best
        mean, lo, hi = _beta_interval(cell.k, cell.n, cell_prior, KAPPA_NATURAL)
        return Estimate(
            p_natural=mean, p_natural_lo=lo, p_natural_hi=hi,
            support_n=n, source_cell=key, shrunk_from=parent,
        )

    def estimate(self, f: Features, actions: Sequence[str] | None = None) -> Estimate:
        est = self.estimate_natural(f)
        for action in (actions or self.actions):
            u = self._estimate_uplift(f, action, est)
            if u is not None:
                est.uplift[action] = u
        return est

    def _estimate_uplift(self, f: Features, action: str, natural: Estimate) -> UpliftEstimate | None:
        """Uplift for one action, with treated and control drawn from the SAME stratum.

        This is the part that has to be right. The first version backed off to a
        coarser *treated* cell when a fine one was thin, but always took control
        counts keyed by failure class. So `nudge_sms` on a dead instrument
        compared the global SMS-treated pool - mostly auth_friction, which
        recovers at 0.47 - against an instrument_invalid control at 0.06, and
        reported a large credible uplift for an action that cannot possibly help
        a cancelled card. That is textbook confounding by population mix, and it
        would have had the optimiser buying SMS for customers whose card is dead.

        Now treated and control back off together, level for level, so the
        difference is always computed within one stratum.
        """
        treated_key = control_key = ""
        treated_cell = control_cell = None

        for level, (t_key, s_key) in enumerate(zip(f.uplift_keys(action), f.strata())):
            t = self.treated.get(t_key)
            c = self.control_for_uplift.get(s_key)
            if (t is not None and t.n >= MIN_TREATED_FOR_UPLIFT
                    and c is not None and c.n >= MIN_TREATED_FOR_UPLIFT):
                treated_cell, treated_key = t, t_key
                control_cell, control_key = c, s_key
                break

        if treated_cell is None or control_cell is None:
            # never tried at a level where we also have a matched control. an
            # unproven intervention should look worthless, not average.
            return UpliftEstimate(action, 0.0, 0.0, 0.0, 0.0, 0, 0, "insufficient")

        control = control_cell

        grand = self.global_natural.rate or 0.35
        r_t = _shrunk_mean(treated_cell.k, treated_cell.n, grand, KAPPA_UPLIFT)
        r_c = _shrunk_mean(control.k, control.n, grand, KAPPA_UPLIFT)

        headroom = max(1.0 - r_c, 1e-3)
        raw_relative = (r_t - r_c) / headroom

        # Standard error of the relative effect, delta method on the two rates.
        var_t = r_t * (1 - r_t) / max(treated_cell.n, 1)
        var_c = r_c * (1 - r_c) / max(control.n, 1)
        se = math.sqrt(
            var_t / headroom ** 2 + var_c * (r_t - 1) ** 2 / headroom ** 4
        )
        se = max(se, 1e-6)

        # Conjugate normal update against a zero-centred prior. This replaces an
        # earlier ad-hoc shrinkage that multiplied BOTH the estimate and the
        # interval by n/(n+kappa) - which made a 12-observation arm look more
        # precise the less data it had, and it was reporting credible uplift for
        # actions nobody had meaningfully tried. Here thin evidence pulls the
        # mean to zero AND leaves the interval at prior width, so it straddles
        # zero and fails the credibility check, which is the honest outcome.
        prior_var = UPLIFT_PRIOR_SD ** 2
        post_var = 1.0 / (1.0 / prior_var + 1.0 / se ** 2)
        relative = raw_relative * (post_var / se ** 2)
        post_sd = math.sqrt(post_var)

        delta = relative * natural.headroom
        return UpliftEstimate(
            action=action,
            delta=float(delta),
            lo=float((relative - _Z * post_sd) * natural.headroom),
            hi=float((relative + _Z * post_sd) * natural.headroom),
            relative=float(relative),
            treated_n=int(treated_cell.n),
            control_n=int(control.n),
            source_cell=f"{treated_key} vs {control_key}",
        )

    # -- introspection ------------------------------------------------------

    def summary(self) -> dict:
        return {
            "fit_rows": self.fit_rows,
            "fit_until": self.fit_until.isoformat() if self.fit_until else None,
            "natural_cells": len(self.natural),
            "uplift_cells": len(self.treated),
            "actions_observed": list(self.actions),
            "global_natural_rate": round(self.global_natural.rate, 4),
            "global_control_n": int(self.global_natural.n),
        }


def _covered_by_downtime(
    downtimes: Sequence[DowntimeRecord], when: datetime, method: str, instrument: str
) -> bool:
    for d in downtimes:
        if d.method not in (method, "*"):
            continue
        if d.instrument not in (instrument, "ALL", "*"):
            continue
        end = d.end or when
        if d.begin <= when <= end:
            return True
    return False


def features_for(payment: Payment, customer: Customer, *, in_downtime: bool) -> Features:
    return Features(
        failure_class=payment.failure_class or "unknown",
        method=payment.method,
        amount_paise=payment.amount_paise,
        tier=customer.tier,
        in_downtime=in_downtime,
        prior_recovery_rate=customer.prior_recovery_rate,
        prior_failures=customer.prior_failures,
    )
