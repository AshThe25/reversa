"""Optimizer tests.

The first two are the product thesis expressed as assertions. If they fail, the
pitch is wrong, not just the code.
"""

import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.engines.portfolio_optimizer import (
    Candidate, natural_recovery_paise, solve, solve_do_nothing,
    solve_fixed_action, solve_greedy,
)
from reversa.world import params as P

ALL = ("retry_now", "retry_delayed", "switch_method", "payment_link",
       "nudge_sms", "nudge_whatsapp", "nudge_email", "voice_call")


def cand(pid, amount, p_nat, uplift, *, cid=None, eligible=ALL, credible=True):
    return Candidate(
        payment_id=pid, customer_id=cid or f"cus_{pid}", amount_paise=amount,
        failure_class="auth_friction", p_natural=p_nat, confidence=0.8,
        uplift=uplift, uplift_credible={a: credible for a in uplift},
        eligible=tuple(eligible),
    )


# --- the thesis -------------------------------------------------------------

def test_a_big_payment_that_would_recover_anyway_loses_to_a_small_one_that_wont():
    """The whole argument. Sorting by amount buys the first and skips the second."""
    big_but_safe = cand("big", 50_00_000, 0.88, {"payment_link": 0.02})
    small_but_movable = cand("small", 4_00_000, 0.20, {"payment_link": 0.30})

    plan = solve([big_but_safe, small_but_movable], {"payment_link": 1})
    assert [a.payment_id for a in plan.assignments] == ["small"]


def test_uplift_not_gross_recovery_drives_the_choice():
    """Both candidates recover the same rupees in expectation. Only one of them
    recovers rupees *because of us*."""
    a = cand("a", 10_00_000, 0.80, {"nudge_sms": 0.05})   # 0.85 gross, 0.05 incremental
    b = cand("b", 10_00_000, 0.10, {"nudge_sms": 0.25})   # 0.35 gross, 0.25 incremental
    plan = solve([a, b], {"nudge_sms": 1})
    assert [x.payment_id for x in plan.assignments] == ["b"]


# --- correctness ------------------------------------------------------------

def test_solution_is_integral_because_the_matrix_is_totally_unimodular():
    """Every variable sits in exactly one payment row and one action row, so the
    LP relaxation's vertices are integral and HiGHS returns the true integer
    optimum. Asserting it rather than trusting it, because a future constraint
    could quietly break the property."""
    rng = np.random.default_rng(7)
    cands = [
        cand(f"p{i}", int(rng.integers(50_000, 40_00_000)), float(rng.uniform(0.05, 0.9)),
             {a: float(rng.uniform(0, 0.25)) for a in ALL})
        for i in range(400)
    ]
    plan = solve(cands, {"payment_link": 30, "nudge_sms": 100, "retry_delayed": 200})
    assert plan.integral and plan.status == "optimal"
    assert not plan.notes


def test_never_assigns_two_actions_to_one_payment():
    cands = [cand(f"p{i}", 5_00_000, 0.2, {a: 0.2 for a in ALL}) for i in range(50)]
    plan = solve(cands, {a: 100 for a in ALL})
    seen = [a.payment_id for a in plan.assignments]
    assert len(seen) == len(set(seen))


def test_respects_every_capacity_limit():
    cands = [cand(f"p{i}", 5_00_000, 0.2, {"payment_link": 0.3, "nudge_sms": 0.25})
             for i in range(500)]
    caps = {"payment_link": 30, "nudge_sms": 40}
    plan = solve(cands, caps)
    for action, limit in caps.items():
        assert plan.by_action.get(action, 0) <= limit
    assert "payment_link" in plan.exhausted_actions()


def test_gate_blocked_actions_are_never_chosen():
    """Compliance is not an input to the objective - it removes the variable."""
    c = cand("p1", 50_00_000, 0.1, {"voice_call": 0.9}, eligible=("nudge_email",))
    plan = solve([c], {"voice_call": 10, "nudge_email": 10})
    assert all(a.action == "nudge_email" for a in plan.assignments)


def test_non_credible_uplift_cannot_buy_a_paid_action():
    """Spending on an effect we cannot distinguish from zero is how recovery
    programmes burn budget and goodwill at once."""
    c = cand("p1", 50_00_000, 0.1, {"voice_call": 0.4}, credible=False)
    assert solve([c], {"voice_call": 5}).assignments == []
    # ...but a free action on the same shaky estimate is allowed
    free = cand("p2", 50_00_000, 0.1, {"retry_delayed": 0.2}, credible=False)
    assert solve([free], {"retry_delayed": 5}).assignments


def test_negative_value_moves_are_skipped_even_with_spare_capacity():
    """A voice call costs Rs 14.50. Placing one for Rs 2 of expected uplift is a
    loss, and idle capacity is not a reason to take it."""
    c = cand("p1", 20_000, 0.3, {"voice_call": 0.01})
    assert solve([c], {"voice_call": 100}).assignments == []


def test_cost_is_netted_off_value_not_imposed_as_a_budget_row():
    """A budget constraint would be a knapsack row and would destroy the
    unimodularity the exact solve depends on."""
    c = cand("p1", 6_000, 0.1, {"voice_call": 0.30})   # 1800 paise uplift < 1450 cost? no
    cheap = cand("p2", 6_000, 0.1, {"nudge_email": 0.30})
    plan = solve([c, cheap], {"voice_call": 5, "nudge_email": 5})
    total = sum(a.expected_incremental_paise for a in plan.assignments)
    assert plan.net_paise == total - plan.cost_paise


# --- against the alternatives -----------------------------------------------

def test_exact_solve_is_never_worse_than_greedy():
    rng = np.random.default_rng(11)
    cands = [
        cand(f"p{i}", int(rng.integers(20_000, 60_00_000)), float(rng.uniform(0.02, 0.95)),
             {a: float(rng.uniform(0, 0.3)) for a in ALL})
        for i in range(600)
    ]
    caps = {"payment_link": 30, "voice_call": 15, "nudge_sms": 80,
            "nudge_whatsapp": 50, "retry_delayed": 150}
    exact = solve(cands, caps)
    greedy = solve_greedy(cands, caps)
    assert exact.net_paise >= greedy.net_paise


def test_spraying_one_action_at_everyone_is_capacity_bound_and_says_so():
    cands = [cand(f"p{i}", 5_00_000, 0.2, {"payment_link": 0.3}) for i in range(200)]
    plan = solve_fixed_action(cands, "payment_link", {"payment_link": 30})
    assert len(plan.assignments) == 30
    assert any("left untreated" in n for n in plan.notes)


def test_do_nothing_is_a_real_scenario_with_zero_actions():
    cands = [cand(f"p{i}", 5_00_000, 0.6, {"payment_link": 0.1}) for i in range(10)]
    plan = solve_do_nothing(cands)
    assert plan.assignments == [] and plan.expected_incremental_paise == 0
    # ...and yet money still arrives, which is the entire point
    assert natural_recovery_paise(cands) == 30_00_000


# --- reporting --------------------------------------------------------------

def test_plan_counts_actions_aimed_at_people_who_would_have_paid_anyway():
    cands = [cand("safe", 50_00_000, 0.92, {"nudge_sms": 0.05}),
             cand("movable", 50_00_000, 0.15, {"nudge_sms": 0.25})]
    plan = solve(cands, {"nudge_sms": 2})
    assert plan.wasted() == 1


def test_friction_accumulates_by_channel():
    cands = [cand("a", 50_00_000, 0.1, {"voice_call": 0.4}),
             cand("b", 50_00_000, 0.1, {"nudge_email": 0.4})]
    plan = solve(cands, {"voice_call": 1, "nudge_email": 1})
    assert plan.friction == pytest.approx(
        P.ACTION_FRICTION["voice_call"] + P.ACTION_FRICTION["nudge_email"]
    )


def test_empty_cohort_does_not_explode():
    plan = solve([], {"payment_link": 10})
    assert plan.assignments == [] and "no_positive_value" in plan.status


def test_scales_to_a_real_incident_cohort_fast():
    """The hero incident is ~950 candidates. A judge clicks Simulate and waits."""
    rng = np.random.default_rng(3)
    cands = [
        cand(f"p{i}", int(rng.integers(20_000, 60_00_000)), float(rng.uniform(0.02, 0.95)),
             {a: float(rng.uniform(0, 0.3)) for a in ALL})
        for i in range(2_000)
    ]
    plan = solve(cands, P.DEFAULT_CAPACITY)
    assert plan.status == "optimal"
    assert plan.solve_ms < 2_000, f"took {plan.solve_ms:.0f}ms"
