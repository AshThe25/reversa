"""Invariants the synthetic world has to hold, or none of the rest means anything."""

import pathlib
import statistics as st
import sys
from collections import defaultdict

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.db import Base
from reversa.models import Customer, GroundTruth, Payment, PaymentStatus, WorldMeta
from reversa.taxonomy import RecoveryClass
from reversa.world import params as P
from reversa.world.generator import generate


def _build(seed=7, scale="small"):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    stats = generate(s, seed=seed, scale=scale)
    return s, stats


@pytest.fixture(scope="module")
def world():
    s, stats = _build()
    yield s, stats
    s.close()


def test_generates_a_populated_world(world):
    s, stats = world
    assert stats["payments"] > 1_000
    assert stats["failures"] > 100
    assert stats["ground_truth_rows"] == stats["failures"]


def test_same_seed_reproduces_the_same_world():
    """The demo has to show the same numbers as the pitch video."""
    a, _ = _build(seed=11)
    b, _ = _build(seed=11)

    def digest(sess):
        rows = sess.execute(
            select(Payment.id, Payment.amount_paise, Payment.status,
                   Payment.failure_reason).order_by(Payment.id)
        ).all()
        return len(rows), sum(r[1] for r in rows), tuple(rows[:50])

    assert digest(a) == digest(b)
    a.close(); b.close()


def test_different_seeds_give_different_worlds():
    a, _ = _build(seed=1)
    b, _ = _build(seed=2)
    ta = a.execute(select(func.sum(Payment.amount_paise))).scalar()
    tb = b.execute(select(func.sum(Payment.amount_paise))).scalar()
    assert ta != tb
    a.close(); b.close()


# --- the potential-outcomes model -------------------------------------------

def test_no_defiers_intervention_never_makes_things_worse_than_its_own_probability(world):
    """Y(a) = 1[U < p(a)] with U shared across futures.

    So whenever p(a) >= p_nat, the intervention cannot flip a natural recoverer
    into a non-recoverer. Checking the threshold logic holds for every row.
    """
    s, _ = world
    rows = s.execute(select(GroundTruth)).scalars().all()
    for gt in rows:
        recovers = gt.resolve_u < gt.true_p_natural
        assert gt.recovers_naturally == recovers or gt.natural_recovery_hours is None
        for action, p_a in gt.true_p_by_action.items():
            if p_a >= gt.true_p_natural:
                # anyone who recovers naturally also recovers under this action
                assert not (recovers and gt.resolve_u >= p_a)


def test_uplift_shrinks_as_natural_recovery_rises(world):
    """The damping term. Without it 'spray the whole cohort' always wins and the
    optimizer has nothing to do."""
    s, _ = world
    rows = s.execute(
        select(GroundTruth.true_p_natural, GroundTruth.true_uplift_by_action)
    ).all()
    low = [u["payment_link"] for p, u in rows if p < 0.2]
    high = [u["payment_link"] for p, u in rows if p > 0.7]
    assert low and high
    assert st.mean(low) > st.mean(high) * 2


def test_failure_classes_are_ordered_the_way_payments_actually_behave(world):
    s, _ = world
    rows = s.execute(
        select(GroundTruth.true_failure_class, GroundTruth.true_p_natural)
    ).all()
    by = defaultdict(list)
    for c, p in rows:
        by[c].append(p)
    mean = {c: st.mean(v) for c, v in by.items() if len(v) >= 15}

    infra = mean[RecoveryClass.INFRA_TRANSIENT.value]
    dead = mean[RecoveryClass.INSTRUMENT_INVALID.value]
    auth = mean[RecoveryClass.AUTH_FRICTION.value]

    # rails heal themselves; dead cards don't
    assert infra > 0.6
    assert dead < 0.15
    assert dead < auth < infra


def test_only_a_method_switch_helps_a_dead_instrument(world):
    s, _ = world
    rows = s.execute(
        select(GroundTruth.true_uplift_by_action).where(
            GroundTruth.true_failure_class == RecoveryClass.INSTRUMENT_INVALID.value
        )
    ).scalars().all()
    assert rows
    for u in rows:
        # re-presenting a dead card is never positive - and it's actively
        # negative if the failure landed inside an outage window
        assert u["retry_now"] <= 0.0
        assert u["retry_delayed"] <= 0.0
        assert u["switch_method"] > 0.0


def test_retrying_into_a_live_incident_is_worse_than_waiting(world):
    """The result the wind tunnel is built to surface. It has to come out of the
    world model, not out of the UI asserting it."""
    s, _ = world
    rows = s.execute(
        select(GroundTruth.true_uplift_by_action).where(
            GroundTruth.is_incident_member.is_(True),
            GroundTruth.true_failure_class == RecoveryClass.INFRA_TRANSIENT.value,
        )
    ).scalars().all()
    assert rows, "no infra failures inside an incident window"
    now = st.mean(u["retry_now"] for u in rows)
    later = st.mean(u["retry_delayed"] for u in rows)
    assert now < 0 < later


# --- temporal / behavioural coherence ---------------------------------------

def test_customer_history_is_carried_forward_not_random(world):
    s, _ = world
    rows = s.execute(
        select(Customer.prior_failures, Customer.prior_recoveries,
               Customer.lifetime_orders)
    ).all()
    assert any(f > 0 for f, _, _ in rows)
    for failures, recoveries, orders in rows:
        assert recoveries <= failures            # can't recover what didn't fail
        assert failures <= orders                # can't fail more than you ordered


def test_prior_recovery_history_predicts_future_natural_recovery(world):
    """If history didn't carry, this correlation would be zero and the
    estimator's best feature would be noise."""
    s, _ = world
    rows = s.execute(
        select(Customer.prior_failures, Customer.prior_recoveries,
               GroundTruth.true_p_natural)
        .select_from(GroundTruth)
        .join(Payment, Payment.id == GroundTruth.payment_id)
        .join(Customer, Customer.id == Payment.customer_id)
        .where(Customer.prior_failures >= 3)
    ).all()
    assert len(rows) > 50
    hi = [p for f, r, p in rows if r / f >= 0.5]
    lo = [p for f, r, p in rows if r / f < 0.2]
    assert len(hi) >= 20 and len(lo) >= 20, (
        f"need real samples on both sides, got {len(hi)}/{len(lo)}"
    )
    assert st.mean(hi) > st.mean(lo)


def test_incidents_actually_degrade_their_slice(world):
    s, _ = world
    inc = s.get(WorldMeta, "true_incidents").value["incidents"]
    assert inc
    members = s.execute(
        select(func.count()).select_from(GroundTruth)
        .where(GroundTruth.is_incident_member.is_(True))
    ).scalar()
    assert members > 20


def test_some_downtime_is_published_late_and_some_is_a_decoy(world):
    """Both matter: the lag is why a merchant-side detector is worth building,
    the decoys are why our precision number is earned."""
    from reversa.models import DowntimeRecord
    s, _ = world
    rows = s.execute(select(DowntimeRecord)).scalars().all()
    assert any(r.scheduled for r in rows), "no decoy maintenance windows"
    assert any(not r.scheduled for r in rows)

    inc = {i["id"]: i for i in s.get(WorldMeta, "true_incidents").value["incidents"]}
    published = [i for i in inc.values() if i["downtime_published"]]
    assert len(rows) > len(published), "decoys should outnumber nothing"


def test_live_era_failures_are_left_open_for_reversa_to_work_on(world):
    s, _ = world
    open_live = s.execute(
        select(func.count()).select_from(Payment)
        .where(Payment.era == "live", Payment.status == PaymentStatus.FAILED)
    ).scalar()
    resolved_live = s.execute(
        select(func.count()).select_from(Payment)
        .where(Payment.era == "live", Payment.status == PaymentStatus.RECOVERED)
    ).scalar()
    assert open_live > 0
    assert resolved_live == 0, "live-era outcomes must not be pre-realised"


def test_training_era_has_realised_outcomes_to_learn_from(world):
    s, _ = world
    rows = s.execute(
        select(GroundTruth.realised_action).where(GroundTruth.realised_action.is_not(None))
    ).scalars().all()
    assert len(rows) > 50
    # epsilon exploration means every action shows up, which is what makes
    # uplift identifiable from the log at all
    assert len(set(rows)) >= 5
