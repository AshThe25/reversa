"""The learned estimator, and the contest it has to win to be used.

The tests that matter are the ones about refusing. A model that trains on
anything it is handed, and is adopted whether or not it beats what was already
there, is a liability dressed as sophistication.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.engines.counterfactual_engine import Features  # noqa: E402
from reversa.engines.learned_baseline import (  # noqa: E402
    MIN_MARGIN, MIN_ROWS_TO_TRAIN, LearnedBaseline, bake_off, score,
)


def feat(fclass="infra_transient", method="upi", amount=50_00, tier="casual", incident=False):
    return Features(
        failure_class=fclass, method=method, amount_paise=amount,
        tier=tier, in_incident=incident,
    )


def separable(n=1200):
    """Rows where the outcome genuinely depends on the features.

    UPI recovers, cards do not. Any competent estimator should find this, which
    is what makes it a fair floor for the learned one.
    """
    rows = []
    for i in range(n):
        upi = i % 2 == 0
        f = feat(method="upi" if upi else "card", amount=1_00 * (i % 400 + 1))
        rows.append((f, upi if i % 10 else not upi))   # 10% label noise
    return rows


# --- refusing ---------------------------------------------------------------

def test_it_refuses_to_train_on_too_little_and_says_so_by_not_being_ready():
    model = LearnedBaseline.fit(separable(MIN_ROWS_TO_TRAIN - 1))
    assert not model.ready
    with pytest.raises(RuntimeError):
        model.predict(feat())


def test_it_refuses_when_every_outcome_is_the_same():
    """Nothing to learn from a window where everything recovered."""
    rows = [(feat(), True) for _ in range(MIN_ROWS_TO_TRAIN + 50)]
    assert not LearnedBaseline.fit(rows).ready


def test_a_refusal_is_not_an_error_it_is_a_verdict_for_the_incumbent():
    thin = separable(50)
    v = bake_off(thin, thin, lambda f: 0.5)
    assert v.winner == "incumbent"
    assert v.learned is None
    assert "training rows" in v.reason


# --- the contest ------------------------------------------------------------

def test_the_incumbent_keeps_its_place_unless_it_is_actually_beaten():
    """A tie goes to the estimator already in production.

    Here the incumbent is given the true generating probability, so the learned
    model cannot do better than match it, and must not be adopted for noise.
    """
    rows = separable(1400)
    cut = int(len(rows) * 0.7)
    truth = lambda f: 0.9 if f.method == "upi" else 0.1  # noqa: E731
    v = bake_off(rows[:cut], rows[cut:], truth)
    assert v.winner == "incumbent" or v.margin > MIN_MARGIN


def test_a_uselessly_miscalibrated_incumbent_does_lose():
    rows = separable(1400)
    cut = int(len(rows) * 0.7)
    v = bake_off(rows[:cut], rows[cut:], lambda f: 0.99)
    assert v.winner == "learned"
    assert v.learned is not None
    assert v.learned.brier < v.incumbent.brier


def test_the_verdict_carries_the_numbers_that_decided_it():
    rows = separable(1400)
    cut = int(len(rows) * 0.7)
    d = bake_off(rows[:cut], rows[cut:], lambda f: 0.5).as_dict()
    assert set(d) >= {"winner", "margin", "reason", "learned", "incumbent"}
    assert set(d["incumbent"]) >= {"brier", "log_loss", "calibration_error", "n"}


# --- scoring ----------------------------------------------------------------

def test_a_perfect_forecast_scores_about_zero():
    """Exactly zero is unreachable and that is deliberate.

    Probabilities are clipped away from 0 and 1 so log loss stays finite, which
    leaves a perfect forecast scoring the clip width rather than nothing.
    """
    CLIP = 1e-6
    s = score([1.0, 0.0, 1.0], [True, False, True])
    assert s.brier < 1e-9
    assert s.calibration_error == pytest.approx(CLIP, rel=1e-3)


def test_a_confidently_wrong_forecast_scores_worst():
    s = score([0.0, 1.0], [True, False])
    assert s.brier == pytest.approx(1.0, abs=1e-3)


def test_calibration_error_catches_a_model_that_ranks_well_but_lies_about_level():
    """Brier alone can look acceptable while every probability is inflated.

    This is the failure that overspends a budget: the ordering is right, so the
    allocation looks sane, and every expected value is too high.
    """
    outcomes = [True] * 30 + [False] * 70
    honest = [0.3] * 100
    inflated = [0.9] * 100
    assert score(inflated, outcomes).calibration_error > score(honest, outcomes).calibration_error


def test_predictions_are_probabilities():
    model = LearnedBaseline.fit(separable(1000))
    assert model.ready
    for p in model.predict_many([feat(method="upi"), feat(method="card")]):
        assert 0.0 <= p <= 1.0


def test_an_unseen_category_does_not_crash_or_silently_become_another_one():
    model = LearnedBaseline.fit(separable(1000))
    p = model.predict(feat(method="paylater_brand_that_did_not_exist_at_fit_time"))
    assert 0.0 <= p <= 1.0
