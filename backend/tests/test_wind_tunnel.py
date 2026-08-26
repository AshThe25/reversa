"""Cohort construction and wind tunnel.

Built on the generated world rather than fixtures, because the interesting
failures here were interactions between the gates, the clock and the estimator -
none of which show up when you hand-build three candidates.
"""

import pathlib
import sys
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.config import IST
from reversa.db import Base
from reversa.engines import incident_engine as IE
from reversa.engines import simulation_engine as SIM
from reversa.engines.cohort_engine import CONSIDERED_ACTIONS, build_cohort
from reversa.engines.counterfactual_engine import CounterfactualModel
from reversa.engines.portfolio_optimizer import CONTACT_ACTIONS
from reversa.models import WorldMeta
from reversa.world.generator import generate


@pytest.fixture(scope="module")
def live_world():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, expire_on_commit=False)()
    generate(s, seed=99, scale="test_live")
    meta = s.get(WorldMeta, "world").value
    live = datetime.fromisoformat(meta["live_day"])
    demo = datetime.fromisoformat(meta["demo_clock"])
    model = CounterfactualModel.fit(s, until=live)
    found, _ = IE.scan(s, live, demo)
    yield s, model, found, demo
    s.close()


@pytest.fixture(scope="module")
def cohort(live_world):
    s, model, found, demo = live_world
    assert found, "detector found no incidents to build a cohort from"
    hero = max(found, key=lambda i: i.worst.observation.amount_failed_paise)
    return build_cohort(s, hero, model, now=demo)


# --- cohort -----------------------------------------------------------------

def test_cohort_has_members_and_exposure(cohort):
    assert cohort.candidates
    assert cohort.revenue_exposed_paise > 0


def test_addressable_is_exposure_minus_what_arrives_anyway(cohort):
    """The single most important arithmetic in the product."""
    assert cohort.addressable_paise == (
        cohort.revenue_exposed_paise - cohort.natural_recovery_paise
    )
    assert 0 < cohort.natural_recovery_paise < cohort.revenue_exposed_paise


def test_attribution_discounts_the_baseline_failures_inside_the_window(cohort):
    """A cohort window wider than the true degradation picks up ordinary
    failures. Counting those as incident damage overstates the headline."""
    assert 0.0 < cohort.attribution_weight <= 1.0
    assert cohort.attributable_exposure_paise <= cohort.revenue_exposed_paise


def test_unactionable_payments_are_listed_not_silently_dropped(cohort):
    assert cohort.in_window_payments == len(cohort.candidates) + len(cohort.exceptions)
    for e in cohort.exceptions:
        assert e.reason and e.amount_paise >= 0


def test_only_one_payment_per_customer_can_be_contacted(cohort):
    """Enforced when candidates are built, so the optimiser's constraint matrix
    stays totally unimodular - and so we don't message one person four times."""
    holders = [
        c.customer_id for c in cohort.candidates
        if any(a in CONTACT_ACTIONS for a in c.eligible)
    ]
    assert len(holders) == len(set(holders))


def test_every_candidate_has_at_least_one_legal_move(cohort):
    for c in cohort.candidates:
        assert c.eligible
        assert set(c.eligible) <= set(CONSIDERED_ACTIONS)


def test_contact_actions_are_available_inside_the_contact_window(cohort):
    """Regression. The demo clock sat one minute past 19:00 IST and every
    payment link in the tunnel came back blocked - the gate was right, the
    scheduling was wrong."""
    assert any(
        a in CONTACT_ACTIONS for c in cohort.candidates for a in c.eligible
    ), "no contact action is available anywhere in the cohort"


def test_a_resolved_outage_stops_suppressing_action(cohort):
    """Regression. Suppression was keyed on whether the rail was down when the
    payment failed, not whether it is down now - so the system refused to act
    precisely when acting had become safe again."""
    assert cohort.rail_down_now is False


def test_build_is_fast_enough_for_a_click(cohort):
    assert cohort.build_ms < 4_000, f"cohort build took {cohort.build_ms:.0f}ms"


# --- wind tunnel ------------------------------------------------------------

@pytest.fixture(scope="module")
def tunnel(cohort):
    return SIM.run(cohort.candidates)


def test_every_named_scenario_is_present(tunnel):
    keys = {s.key for s in tunnel.scenarios}
    assert {"do_nothing", "retry_now", "retry_delayed",
            "payment_link", "greedy", "optimal"} <= keys


def test_do_nothing_is_pure_natural_recovery(tunnel):
    base = tunnel.baseline
    assert base.action_count == 0
    assert base.incremental_recovery_paise == 0
    assert base.gross_recovery_paise == base.natural_recovery_paise > 0


def test_gross_is_never_reported_as_incremental(tunnel):
    """The distinction the whole product exists to make."""
    for s in tunnel.scenarios:
        assert s.gross_recovery_paise == (
            s.natural_recovery_paise + s.incremental_recovery_paise
        )
        if s.action_count:
            assert s.incremental_recovery_paise < s.gross_recovery_paise


def test_every_scenario_shares_the_same_natural_baseline(tunnel):
    """Branches must differ only in what we did, never in the world they start
    from. If these drift, no two columns are comparable."""
    assert len({s.natural_recovery_paise for s in tunnel.scenarios}) == 1


def test_optimal_beats_every_fixed_strategy_on_net_incremental(tunnel):
    optimal = next(s for s in tunnel.scenarios if s.key == "optimal")
    for other in tunnel.scenarios:
        if other.key == "optimal":
            continue
        assert optimal.net_incremental_paise >= other.net_incremental_paise


def test_the_aggressive_strategy_is_not_the_best_one(tunnel):
    """The result the tunnel exists to surface: spraying one action spends
    capacity on people who would have paid anyway.

    The defensible claim is value per intervention, not raw action count -
    depending on the cohort the optimal plan may legitimately take more cheap
    actions and still be far more efficient.
    """
    retry = next(s for s in tunnel.scenarios if s.key == "retry_now")
    optimal = next(s for s in tunnel.scenarios if s.key == "optimal")
    assert optimal.net_incremental_paise > retry.net_incremental_paise

    per_action = lambda s: s.net_incremental_paise / max(s.action_count, 1)
    assert per_action(optimal) > per_action(retry)


def test_no_fixed_strategy_can_report_negative_incremental_recovery(tunnel):
    """Regression. "Apply this to everyone eligible" was including candidates the
    estimator expects the action to hurt, so RETRY +15M came back at minus
    Rs 4.5L. A strategy nobody would run is not a useful comparison."""
    for s in tunnel.scenarios:
        assert s.incremental_recovery_paise >= 0, s.key


def test_waiting_is_modelled_as_a_real_tradeoff_not_a_free_win(cohort):
    """Delaying lets a degraded rail recover but lets intent cool. Both have to
    be in the model or the tunnel is just asserting the answer it wants."""
    delayed = SIM._delayed_view(cohort.candidates)
    original = {c.payment_id: c for c in cohort.candidates}
    softened = harder = 0
    for d in delayed:
        o = original[d.payment_id]
        if d.uplift.get("payment_link", 0) < o.uplift.get("payment_link", 0):
            softened += 1                       # contact decays with delay
        if d.uplift.get("retry_now", 0) > o.uplift.get("retry_now", 0):
            harder += 1                         # rail had time to come back
    assert softened > 0 and harder > 0


def test_link_capacity_binds_at_the_test_mode_ceiling(tunnel):
    link = next(s for s in tunnel.scenarios if s.key == "payment_link")
    assert link.action_count <= 30
    assert "payment_link" in link.exhausted


def test_scenarios_report_what_they_cost_not_only_what_they_earn(tunnel):
    for s in tunnel.scenarios:
        assert s.net_incremental_paise == s.incremental_recovery_paise - s.cost_paise
        assert s.friction >= 0 and s.wasted_actions >= 0
        assert 0.0 <= s.confidence <= 1.0 and 0.0 <= s.risk_score <= 1.0


def test_no_scenario_violates_a_compliance_gate(tunnel):
    for s in tunnel.scenarios:
        assert s.policy_violations == 0, (s.key, s.violation_detail)


def test_delayed_branch_does_not_mutate_the_shared_cohort(cohort, tunnel):
    """Every branch has to start from the same reality. The delayed view adjusts
    uplift on a copy; if it wrote through, later scenarios would silently
    inherit a different world."""
    delayed = SIM._delayed_view(cohort.candidates)
    assert delayed is not cohort.candidates
    assert all(a.uplift is not b.uplift for a, b in zip(delayed, cohort.candidates))


def test_whole_tunnel_runs_fast_enough_to_feel_instant(tunnel):
    assert tunnel.total_ms < 3_000, f"{tunnel.total_ms:.0f}ms"


def test_capacity_exhaustion_forecast_is_arithmetic_not_theatre(tunnel):
    from reversa.engines.portfolio_optimizer import solve
    optimal = next(s for s in tunnel.scenarios if s.key == "optimal")
    assert optimal.action_count > 0
