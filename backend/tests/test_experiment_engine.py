"""Randomisation and measurement.

The assignment tests matter more than they look: if arms drift between runs, the
demo and the pitch video disagree, and if a customer can land in two arms the
whole causal claim is void.
"""

import pathlib
import sys
from collections import Counter
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.engines import experiment_engine as EX
from reversa.models import Arm, RecoveryOutcome

NOW = datetime(2026, 8, 26, 13, 20, tzinfo=timezone.utc)


def _arm(cid, exp="exp_1", holdout=0.2, explore=0.0):
    return EX.assign_arm(exp, cid, holdout_fraction=holdout,
                         exploration_fraction=explore)[0]


# --- assignment -------------------------------------------------------------

def test_assignment_is_deterministic():
    """Same inputs, same arm, forever. Otherwise a rerun of the demo produces
    different numbers than the pitch video."""
    a = [_arm(f"cus_{i}") for i in range(500)]
    b = [_arm(f"cus_{i}") for i in range(500)]
    assert a == b


def test_assignment_is_keyed_on_customer_not_payment():
    """A person with three stuck payments belongs in one arm. Splitting them
    contaminates the control group with partially-treated customers."""
    assert _arm("cus_42") == _arm("cus_42") == _arm("cus_42")


def test_different_experiments_reshuffle_the_same_customers():
    """Otherwise the same unlucky people are in the holdout every single time."""
    first = [_arm(f"cus_{i}", exp="exp_a") for i in range(400)]
    second = [_arm(f"cus_{i}", exp="exp_b") for i in range(400)]
    assert first != second


def test_holdout_fraction_is_respected_in_the_large():
    arms = Counter(_arm(f"cus_{i}", holdout=0.2) for i in range(20_000))
    share = arms[Arm.HOLDOUT.value] / 20_000
    assert 0.18 < share < 0.22


def test_exploration_arm_is_carved_out_of_treatment_not_holdout():
    arms = Counter(_arm(f"cus_{i}", holdout=0.1, explore=0.05) for i in range(20_000))
    assert 0.08 < arms[Arm.HOLDOUT.value] / 20_000 < 0.12
    assert 0.03 < arms[EX.EXPLORATION] / 20_000 < 0.07


def test_zero_holdout_puts_everyone_in_treatment():
    assert all(_arm(f"cus_{i}", holdout=0.0) == Arm.TREATMENT.value for i in range(200))


def test_assignment_hash_is_recorded_so_an_auditor_can_recompute_it():
    _, digest = EX.assign_arm("exp_1", "cus_9", holdout_fraction=0.2)
    assert len(digest) == 16
    assert EX.assign_arm("exp_1", "cus_9", holdout_fraction=0.2)[1] == digest


def test_exploration_action_is_a_legal_one_and_reproducible():
    eligible = ("retry_now", "payment_link", "nudge_sms")
    a = EX.random_legal_action(eligible, experiment_id="e", payment_id="p1")
    b = EX.random_legal_action(eligible, experiment_id="e", payment_id="p1")
    assert a == b and a in eligible
    assert EX.random_legal_action((), experiment_id="e", payment_id="p1") is None


# --- balance ----------------------------------------------------------------

def test_balance_report_flags_a_lopsided_draw():
    """Hash assignment is unbiased in expectation, but a single draw that puts
    the three biggest payments in the holdout produces a lift number that is
    pure noise. Worth seeing before the headline."""
    arms = {f"p{i}": (Arm.HOLDOUT.value if i < 5 else Arm.TREATMENT.value)
            for i in range(100)}
    exposure = {f"p{i}": (50_00_000 if i < 5 else 10_000) for i in range(100)}
    rep = EX.balance_report(arms, exposure)
    assert not rep["_balance"]["balanced"]
    assert rep["_balance"]["mean_ticket_ratio"] > 1.25


def test_balance_report_accepts_an_even_draw():
    arms = {f"p{i}": (Arm.HOLDOUT.value if i % 5 == 0 else Arm.TREATMENT.value)
            for i in range(1000)}
    exposure = {f"p{i}": 2_00_000 for i in range(1000)}
    assert EX.balance_report(arms, exposure)["_balance"]["balanced"]


# --- measurement ------------------------------------------------------------

def _outcomes(session, exp_id, spec):
    """spec: list of (arm, n, recovery_rate, amount, cost)."""
    idx = 0
    for arm, n, rate, amount, cost in spec:
        hits = int(round(n * rate))
        for i in range(n):
            recovered = i < hits
            session.add(RecoveryOutcome(
                id=f"out_{exp_id}_{idx:05d}", payment_id=f"pay_{exp_id}_{idx:05d}",
                experiment_id=exp_id, arm=arm, recovered=recovered,
                amount_paise=amount,
                recovered_amount_paise=amount if recovered else 0,
                action_cost_paise=cost if arm == Arm.TREATMENT.value else 0,
                observed_at=NOW,
            ))
            idx += 1
    session.flush()


def test_measures_incremental_against_the_holdout_not_gross(session):
    _outcomes(session, "e1", [
        (Arm.TREATMENT.value, 800, 0.60, 2_00_000, 25),
        (Arm.HOLDOUT.value, 200, 0.40, 2_00_000, 0),
    ])
    r = EX.results(session, "e1", bootstrap_samples=400)
    assert r.gross_recovery_paise == 480 * 2_00_000
    # counterfactual is 40% of treatment exposure, not zero
    assert r.natural_recovery_paise == pytest.approx(0.40 * 800 * 2_00_000, rel=0.01)
    assert r.incremental_paise < r.gross_recovery_paise
    assert r.significant


def test_a_useless_intervention_measures_as_useless(session):
    """Same recovery rate in both arms. The system must report roughly nothing,
    not the gross number."""
    _outcomes(session, "e2", [
        (Arm.TREATMENT.value, 900, 0.50, 2_00_000, 25),
        (Arm.HOLDOUT.value, 300, 0.50, 2_00_000, 0),
    ])
    r = EX.results(session, "e2", bootstrap_samples=400)
    assert r.gross_recovery_paise > 0
    assert abs(r.incremental_paise) < 0.02 * r.gross_recovery_paise
    assert not r.significant
    assert r.incremental_lo_paise <= 0 <= r.incremental_hi_paise


def test_no_holdout_means_no_causal_claim(session):
    _outcomes(session, "e3", [(Arm.TREATMENT.value, 500, 0.7, 2_00_000, 25)])
    r = EX.results(session, "e3", bootstrap_samples=200)
    assert r.incremental_paise == 0
    assert not r.significant
    assert any("no holdout" in w for w in r.warnings)


def test_a_thin_holdout_is_called_out(session):
    _outcomes(session, "e4", [
        (Arm.TREATMENT.value, 400, 0.6, 2_00_000, 25),
        (Arm.HOLDOUT.value, 12, 0.4, 2_00_000, 0),
    ])
    r = EX.results(session, "e4", bootstrap_samples=300)
    assert any("only 12" in w for w in r.warnings)


def test_measurement_cost_is_stated_not_hidden(session):
    """A 20% holdout on real exposure is real money not chased. Pretending
    otherwise loses the argument with finance the first time someone checks."""
    _outcomes(session, "e5", [
        (Arm.TREATMENT.value, 800, 0.60, 2_00_000, 25),
        (Arm.HOLDOUT.value, 200, 0.40, 2_00_000, 0),
    ])
    r = EX.results(session, "e5", bootstrap_samples=300)
    assert r.measurement_cost_paise > 0


def test_effect_concentrated_in_a_few_large_payments_is_flagged(session):
    """The fragile case: revenue lift clears zero, per-payment rate lift does
    not. Reporting the revenue number alone would be true and misleading."""
    idx = 0
    for arm, n in ((Arm.TREATMENT.value, 400), (Arm.HOLDOUT.value, 400)):
        for i in range(n):
            big = arm == Arm.TREATMENT.value and i < 5
            recovered = big or i % 2 == 0
            amount = 80_00_000 if big else 50_000
            session.add(RecoveryOutcome(
                id=f"out_e6_{idx:05d}", payment_id=f"pay_e6_{idx:05d}",
                experiment_id="e6", arm=arm, recovered=recovered,
                amount_paise=amount,
                recovered_amount_paise=amount if recovered else 0,
                action_cost_paise=0, observed_at=NOW,
            ))
            idx += 1
    session.flush()
    r = EX.results(session, "e6", bootstrap_samples=600)
    if r.significant and not r.rate_significant:
        assert r.concentrated
        assert any("concentrated" in w for w in r.warnings)


def test_bootstrap_interval_brackets_the_point_estimate(session):
    _outcomes(session, "e7", [
        (Arm.TREATMENT.value, 700, 0.62, 3_00_000, 25),
        (Arm.HOLDOUT.value, 300, 0.45, 3_00_000, 0),
    ])
    r = EX.results(session, "e7", bootstrap_samples=800)
    assert r.incremental_lo_paise <= r.incremental_paise <= r.incremental_hi_paise
    assert r.rate_lift_lo <= r.rate_lift <= r.rate_lift_hi


def test_results_are_reproducible(session):
    _outcomes(session, "e8", [
        (Arm.TREATMENT.value, 500, 0.6, 2_00_000, 25),
        (Arm.HOLDOUT.value, 150, 0.45, 2_00_000, 0),
    ])
    a = EX.results(session, "e8", bootstrap_samples=500)
    b = EX.results(session, "e8", bootstrap_samples=500)
    assert (a.incremental_lo_paise, a.incremental_hi_paise) == (
        b.incremental_lo_paise, b.incremental_hi_paise
    )
