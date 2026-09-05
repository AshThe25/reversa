"""Score the learned estimator against the incumbent on a temporal holdout.

    python -m scripts.bakeoff

Split is by time, not at random: the model is fitted on the earlier part of the
training window and scored on the later part, which is the only split that
mirrors what it faces in production. A random split would let it learn from
payments that happened after the ones it is predicting, and would flatter it.

Both estimators see the same features and the same history. Neither reads
GroundTruth.
"""

from sqlalchemy import select
from reversa.db import session_scope
from reversa.engines import pipeline as PL
from reversa.engines.counterfactual_engine import (
    CounterfactualModel, Features, degraded_buckets, bucket_keys,
)
from reversa.engines.learned_baseline import bake_off
from reversa.models import Customer, Payment, PaymentStatus, RunEra

with session_scope() as s:
    clock = PL.clock(s)
    until = clock.now
    degraded = degraded_buckets(s, until=until)

    rows = s.execute(
        select(
            Payment.failure_class, Payment.method, Payment.instrument,
            Payment.amount_paise, Payment.status, Payment.created_at,
            Customer.tier, Customer.prior_failures, Customer.prior_natural_recoveries,
        )
        .join(Customer, Customer.id == Payment.customer_id)
        .where(
            Payment.status.in_((PaymentStatus.FAILED, PaymentStatus.RECOVERED)),
            Payment.created_at < until,
            Payment.era == RunEra.TRAINING,
        )
        .order_by(Payment.created_at.asc())
    ).all()

    data = []
    for fclass, method, instrument, amount, status, created, tier, pf, pnr in rows:
        if not fclass:
            continue
        f = Features(
            failure_class=fclass, method=method, amount_paise=amount,
            tier=tier or "casual",
            in_incident=any(k in degraded for k in bucket_keys(method, instrument, created)),
            prior_recovery_rate=(pnr / pf) if pf else 0.42,
            prior_failures=pf or 0,
        )
        data.append((f, status == PaymentStatus.RECOVERED))

    cut = int(len(data) * 0.75)
    train, holdout = data[:cut], data[cut:]
    print(f"rows {len(data):,}   train {len(train):,}   holdout {len(holdout):,} (temporal split)")

    # The incumbent must be fitted on the same history the challenger gets.
    split_at = rows[cut][5]
    incumbent = CounterfactualModel.fit(s, until=split_at)
    print(f"incumbent fitted to {split_at:%Y-%m-%d %H:%M} on {incumbent.fit_rows:,} rows\n")

    v = bake_off(train, holdout, lambda f: incumbent.estimate_natural(f).p_natural)
    print("WINNER:", v.winner.upper())
    print("reason:", v.reason)
    print()
    if v.learned:
        print(f"{'':12} {'brier':>9} {'log loss':>9} {'calib err':>10}")
        print(f"{'learned':12} {v.learned.brier:>9.5f} {v.learned.log_loss:>9.5f} {v.learned.calibration_error:>10.5f}")
    print(f"{'incumbent':12} {v.incumbent.brier:>9.5f} {v.incumbent.log_loss:>9.5f} {v.incumbent.calibration_error:>10.5f}")
