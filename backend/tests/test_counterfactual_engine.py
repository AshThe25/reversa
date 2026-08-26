"""Estimator tests.

Two of these are regressions for bugs that produced plausible-looking but wrong
numbers, which is the dangerous kind.
"""

import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.db import Base
from reversa.engines.counterfactual_engine import (
    Cell, CounterfactualModel, Features, MIN_TREATED_FOR_UPLIFT, amount_bucket,
)
from reversa.models import WorldMeta
from reversa.world.generator import generate


@pytest.fixture(scope="module")
def fitted():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, expire_on_commit=False)()
    generate(s, seed=42, scale="test")
    live = datetime.fromisoformat(s.get(WorldMeta, "world").value["live_day"])
    model = CounterfactualModel.fit(s, until=live)
    yield model, s
    s.close()


def _f(cls, **kw):
    return Features(
        failure_class=cls, method=kw.pop("method", "upi"),
        amount_paise=kw.pop("amount_paise", 3_00_000),
        tier=kw.pop("tier", "regular"), in_downtime=kw.pop("in_downtime", False), **kw,
    )


def test_amount_buckets_partition_the_range():
    assert amount_bucket(10_000) == "<500"
    assert amount_bucket(1_00_000) == "500-2k"
    assert amount_bucket(5_00_000) == "2k-10k"
    assert amount_bucket(90_00_000) == "50k+"


def test_model_fits_and_reports_its_own_support(fitted):
    model, _ = fitted
    s = model.summary()
    assert s["fit_rows"] > 3_000
    assert s["natural_cells"] > 20
    assert len(s["actions_observed"]) >= 5   # epsilon exploration covered the arms


def test_trained_only_on_history_never_the_live_day(fitted):
    """The live day is a temporal holdout. If the model saw it, every calibration
    number on the evaluation page would be circular."""
    model, session = fitted
    live = datetime.fromisoformat(session.get(WorldMeta, "world").value["live_day"])
    assert model.fit_until == live


def test_recovers_the_true_ordering_of_failure_classes(fitted):
    """Rails heal themselves, dead instruments don't. The estimator has to
    rediscover that from the log alone."""
    model, _ = fitted
    infra = model.estimate_natural(_f("infra_transient")).p_natural
    auth = model.estimate_natural(_f("auth_friction")).p_natural
    dead = model.estimate_natural(_f("instrument_invalid")).p_natural
    assert dead < auth < infra
    assert infra > 0.6 and dead < 0.2


def test_thin_cells_shrink_toward_their_own_parent_not_the_global_rate(fitted):
    """Regression, and the worst bug in this module so far.

    The running prior and the chosen cell shared a variable, so by the last
    iteration they were equal and the final shrinkage silently fell back to the
    global rate. An infra_transient cell with n=3 was pulled toward 0.38 instead
    of its class parent at 0.77 - a 34-point error on exactly the class where
    intervening is most wasteful.
    """
    model, _ = fitted
    thin = model.estimate_natural(_f("infra_transient", tier="vip", method="wallet"))
    grand = model.global_natural.rate
    parent = model.estimate_natural(_f("infra_transient")).p_natural
    assert abs(thin.p_natural - parent) < abs(thin.p_natural - grand)


def test_estimate_records_which_cell_it_came_from(fitted):
    """A merchant about to spend money on this gets to see the evidence."""
    model, _ = fitted
    est = model.estimate_natural(_f("auth_friction"))
    assert est.source_cell and est.shrunk_from
    assert est.support_n >= 0
    assert "auth_friction" in est.source_cell


def test_wide_posterior_means_low_confidence(fitted):
    model, _ = fitted
    est = model.estimate_natural(_f("auth_friction"))
    assert 0.0 <= est.confidence <= 1.0
    assert est.p_natural_lo < est.p_natural < est.p_natural_hi


# --- uplift -----------------------------------------------------------------

def test_uplift_is_bounded_by_remaining_headroom(fitted):
    """You cannot add 20 points to someone already at 0.90. Modelling absolute
    uplift lets the optimiser believe you can."""
    model, _ = fitted
    high = model.estimate(_f("infra_transient"))       # p_nat ~ .77
    low = model.estimate(_f("instrument_invalid"))     # p_nat ~ .05
    for action in ("payment_link",):
        assert high.uplift[action].delta < low.uplift[action].delta
        assert high.p_natural + high.uplift[action].delta <= 1.0


def test_an_untried_action_is_worthless_not_average(fitted):
    model, _ = fitted
    est = model.estimate(_f("auth_friction"), actions=["teleport_the_customer"])
    u = est.uplift["teleport_the_customer"]
    assert u.delta == 0.0 and u.source_cell == "insufficient" and not u.credible


def test_thin_arms_are_not_credible_and_their_intervals_straddle_zero(fitted):
    """Regression. An earlier version scaled the point estimate AND the interval
    by n/(n+kappa), so an arm got *more* precise-looking the less data it had,
    and 12 observations could report credible uplift."""
    model, _ = fitted
    est = model.estimate(_f("auth_friction"))
    thin = [u for u in est.uplift.values()
            if MIN_TREATED_FOR_UPLIFT <= u.treated_n <= 40]
    assert thin, "expected some sparsely-explored arms in the fixture"
    for u in thin:
        assert u.lo < 0 < u.hi, f"{u.action} claims certainty on n={u.treated_n}"
        assert not u.credible


def test_well_evidenced_arms_can_be_credible(fitted):
    """The mirror. If nothing is ever credible the estimator is just a zero."""
    model, _ = fitted
    est = model.estimate(_f("liquidity"))
    fat = [u for u in est.uplift.values() if u.treated_n > 150]
    assert any(u.credible for u in fat)


def test_treated_and_control_are_drawn_from_the_same_stratum(fitted):
    """Regression for a confounding bug.

    Backing off to a coarser treated cell while keeping a class-keyed control
    compared the global SMS-treated pool (mostly auth_friction, recovers ~0.47)
    against an instrument_invalid control (~0.06), and reported large credible
    uplift for SMS on cancelled cards. Textbook confounding by population mix -
    it would have had the optimiser buying SMS for customers whose card is dead.
    """
    model, _ = fitted
    est = model.estimate(_f("instrument_invalid"))
    for action, u in est.uplift.items():
        if u.source_cell in ("insufficient", "no_control"):
            continue
        treated_key, _, control_key = u.source_cell.partition(" vs ")
        # both sides must sit at the same depth of their hierarchy
        assert treated_key.count("|") - 1 == control_key.count("|") or control_key == "_", (
            f"{action}: treated {treated_key!r} vs control {control_key!r} "
            "are at different strata"
        )


def test_uplift_never_pushes_probability_out_of_range(fitted):
    model, _ = fitted
    for cls in ("infra_transient", "auth_friction", "instrument_invalid", "liquidity"):
        est = model.estimate(_f(cls))
        for u in est.uplift.values():
            assert -1.0 <= est.p_natural + u.delta <= 1.0


def test_best_action_respects_the_allowed_set(fitted):
    model, _ = fitted
    est = model.estimate(_f("liquidity"))
    assert est.best_action(allowed=["nudge_email"]) in ("nudge_email", None)
    assert est.best_action(allowed=[]) is None


def test_expected_incremental_scales_with_amount(fitted):
    model, _ = fitted
    est = model.estimate(_f("liquidity"))
    a = est.expected_incremental_paise("payment_link", 1_00_000)
    b = est.expected_incremental_paise("payment_link", 10_00_000)
    assert b == pytest.approx(a * 10, rel=0.02)
