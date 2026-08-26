"""Reality happening.

When Reversa executes a plan, something occurs in the world: some customers pay,
some don't. In production that arrives over hours as webhooks. Here the
simulator resolves it, and this module is where that resolution lives -
deliberately under world/ and not under engines/, because it reads the hidden
potential outcomes and no part of the system is allowed to.

The mechanics are the whole reason the measurement means anything. Each payment
carries a latent U drawn once. Whether it recovers under action a is
1[U < p(a)], with the SAME U across every branch. So:

  - a customer with U below p_natural pays regardless. Treating them buys
    nothing, and the money still shows up in gross recovery.
  - a customer with U between p_natural and p(a) pays only because we acted.
    That is the entire incremental effect.
  - a customer above p(a) is unreachable by this action.

Nothing here consults what Reversa predicted. The estimator can be badly wrong
and the world resolves exactly the same way, which is what makes the evaluation
a test rather than a mirror.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Sequence

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from reversa.models import (
    Arm, GroundTruth, Payment, PaymentAttempt, PaymentEvent, PaymentStatus,
    RecoveryOutcome,
)
from reversa.world import params as P


@dataclass(slots=True)
class Realisation:
    payment_id: str
    arm: str
    action: str | None
    recovered: bool
    amount_paise: int
    recovered_amount_paise: int
    hours_to_recovery: float | None

    # kept out of everything the system can read; used only by evaluation
    was_incremental: bool = False


def realise(
    session: Session,
    *,
    experiment_id: str,
    assignments: Mapping[str, str],
    arms: Mapping[str, str],
    now: datetime,
    seed: int = 20260826,
    horizon_hours: float = P.RECOVERY_HORIZON_HOURS,
) -> list[Realisation]:
    """Resolve outcomes for a set of payments and write the observable record.

    `assignments` maps payment_id -> action for the treated. `arms` maps
    payment_id -> arm for everyone in the experiment, holdout included - the
    holdout has to be resolved too, or there is nothing to compare against.
    """
    payment_ids = list(arms)
    if not payment_ids:
        return []

    truth = {
        gt.payment_id: gt
        for gt in session.execute(
            select(GroundTruth).where(GroundTruth.payment_id.in_(payment_ids))
        ).scalars()
    }
    payments = {
        p.id: p
        for p in session.execute(
            select(Payment).where(Payment.id.in_(payment_ids))
        ).scalars()
    }

    rng = np.random.default_rng(seed)
    out: list[Realisation] = []
    outcome_rows, attempt_rows, event_rows = [], [], []

    for idx, pid in enumerate(sorted(payment_ids)):
        gt, payment = truth.get(pid), payments.get(pid)
        if gt is None or payment is None:
            continue

        arm = arms[pid]
        action = assignments.get(pid) if arm == Arm.TREATMENT else None

        p_nat = gt.true_p_natural
        p_eff = gt.true_p_by_action.get(action, p_nat) if action else p_nat
        u = gt.resolve_u

        recovered = u < p_eff
        incremental = bool(p_nat <= u < p_eff)

        delay = None
        if recovered:
            mu, sigma = P.RECOVERY_DELAY_LOGNORMAL.get(gt.true_failure_class, (1.5, 1.2))
            delay = float(rng.lognormal(mu, sigma))
            if action:
                # an intervention pulls the recovery forward - the customer is
                # being handed the path rather than finding it themselves
                delay *= 0.55
            if delay > horizon_hours:
                # recovered, but outside the window a merchant may claim
                recovered, incremental, delay = False, False, None

        at = now + timedelta(hours=delay) if delay is not None else None
        amount = payment.amount_paise

        out.append(Realisation(
            payment_id=pid, arm=arm, action=action, recovered=recovered,
            amount_paise=amount,
            recovered_amount_paise=amount if recovered else 0,
            hours_to_recovery=delay, was_incremental=incremental,
        ))

        outcome_rows.append(RecoveryOutcome(
            id=f"out_{experiment_id[-8:]}_{idx:06d}",
            payment_id=pid, experiment_id=experiment_id, arm=arm,
            recovered=recovered, amount_paise=amount,
            recovered_amount_paise=amount if recovered else 0,
            recovered_at=at,
            hours_to_recovery=round(delay, 3) if delay else None,
            action_type=action,
            action_cost_paise=P.ACTION_COST_PAISE.get(action, 0) if action else 0,
            observed_at=now,
        ))

        gt.realised_action = action or "no_action"
        gt.realised_recovered = recovered
        gt.realised_incremental = incremental

        if recovered:
            payment.status = PaymentStatus.RECOVERED
            payment.resolved_at = at
            payment.recovered_amount_paise = amount
            payment.recovered_via = action or "natural"
            attempt_rows.append(PaymentAttempt(
                id=f"att_{experiment_id[-8:]}_{idx:06d}",
                payment_id=pid, attempt_no=2, method=payment.method,
                instrument=payment.instrument, succeeded=True, error_reason=None,
                origin="reversa" if action else "customer",
                adapter_mode="simulation", created_at=at,
            ))
            event_rows.append(PaymentEvent(
                id=f"pev_{experiment_id[-8:]}_{idx:06d}",
                payment_id=pid, event_type="payment.recovered",
                payload={"via": action or "natural", "arm": arm},
                occurred_at=at,
            ))

    session.add_all(outcome_rows)
    session.add_all(attempt_rows)
    session.add_all(event_rows)
    session.flush()
    return out
