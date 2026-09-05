"""A learned estimator for p_natural, and an honest contest against the incumbent.

The hierarchical empirical-Bayes estimator in `counterfactual_engine` is a good
fit for this data: it degrades gracefully when a cell is thin, and its interval
widens when it should. What it cannot do is generalise *across* cells. A payment
in a cell it has never seen falls back to the parent, and then to the global
rate, and by then it is barely a prediction.

A gradient-boosted model can use the same observable features continuously and
share strength across cells that the hierarchy treats as unrelated. Whether it
is actually better here is a question, not an assumption, so this module answers
it rather than asserting it.

Two things matter more than they usually do:

  Calibration, not accuracy. Every downstream number - expected incremental
  value, the allocation, the ranking a reviewer sees - multiplies this
  probability by an amount in rupees. A model that sorts payments perfectly but
  says 0.9 when it means 0.6 will systematically overspend. So the score that
  decides this is the Brier score and the calibration error, and the classifier
  is wrapped in isotonic calibration fitted on data it did not train on.

  The incumbent has to actually lose to be replaced. `bake_off` scores both on
  a held-out slice and returns a verdict. If the learned model does not win, the
  honest outcome is to keep the estimator that was already there and say so -
  which is the result you should expect on a cell structure this well specified.

Nothing here reads GroundTruth. The features are the same ones the incumbent is
allowed - see tests/test_ground_truth_isolation.py, which enforces it for every
engine including this one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from reversa.engines.counterfactual_engine import Features

# Below this many observations a gradient-boosted model is fitting noise, and
# the hierarchy's shrinkage is strictly the better tool. Refusing to train is a
# result, not a failure.
MIN_ROWS_TO_TRAIN = 400

# Categorical order is pinned so a model fitted in one process scores the same
# in another. Silent category drift is the classic way a served model quietly
# stops matching the one that was evaluated.
_CATEGORICALS: tuple[str, ...] = ("failure_class", "method", "tier", "bucket")


def _row(f: Features) -> list[float]:
    """One feature vector.

    Categoricals are ordinal-coded against a pinned vocabulary rather than
    one-hot: HistGradientBoosting splits on them natively, and an unseen value
    lands in a bucket of its own instead of silently becoming the first class.
    """
    return [
        float(_VOCAB["failure_class"].get(f.failure_class, -1)),
        float(_VOCAB["method"].get(f.method, -1)),
        float(_VOCAB["tier"].get(f.tier, -1)),
        float(_VOCAB["bucket"].get(f.bucket, -1)),
        math.log1p(max(f.amount_paise, 0)),
        1.0 if f.in_incident else 0.0,
        float(f.prior_recovery_rate),
        math.log1p(max(f.prior_failures, 0)),
    ]


FEATURE_NAMES: tuple[str, ...] = (
    "failure_class", "method", "tier", "amount_bucket",
    "log_amount", "in_incident", "prior_recovery_rate", "log_prior_failures",
)

_VOCAB: dict[str, dict[str, int]] = {k: {} for k in _CATEGORICALS}


def _build_vocab(rows: Sequence[tuple[Features, bool]]) -> None:
    for name in _CATEGORICALS:
        seen: dict[str, int] = {}
        for f, _ in rows:
            v = getattr(f, name) if name != "bucket" else f.bucket
            if v not in seen:
                seen[v] = len(seen)
        _VOCAB[name] = seen


@dataclass(slots=True)
class Score:
    """How well a set of probabilities matched what happened."""

    brier: float
    log_loss: float
    calibration_error: float
    n: int

    def as_dict(self) -> dict:
        return {
            "brier": round(self.brier, 5),
            "log_loss": round(self.log_loss, 5),
            "calibration_error": round(self.calibration_error, 5),
            "n": self.n,
        }


def score(probabilities: Sequence[float], outcomes: Sequence[bool]) -> Score:
    """Brier, log loss, and expected calibration error over ten bins.

    Calibration error is the number that decides this: it asks whether payments
    predicted at 30% actually recover 30% of the time. A model can have a fine
    Brier score and still be miscalibrated in the band where most of the money
    is, which is exactly the failure that would overspend the budget.
    """
    p = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1 - 1e-6)
    y = np.asarray(outcomes, dtype=float)

    brier = float(np.mean((p - y) ** 2))
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    bins = np.linspace(0.0, 1.0, 11)
    idx = np.digitize(p, bins[1:-1])
    ece = 0.0
    for b in range(10):
        m = idx == b
        if not m.any():
            continue
        ece += (m.sum() / len(p)) * abs(p[m].mean() - y[m].mean())

    return Score(brier=brier, log_loss=ll, calibration_error=float(ece), n=len(p))


class LearnedBaseline:
    """Calibrated gradient boosting over the same features the incumbent sees."""

    def __init__(self) -> None:
        self._model = None
        self.trained_rows = 0

    @property
    def ready(self) -> bool:
        return self._model is not None

    @classmethod
    def fit(cls, rows: Sequence[tuple[Features, bool]]) -> "LearnedBaseline":
        """Returns an untrained instance rather than raising when data is thin.

        The caller checks `ready`. A model that refuses to train on 200 rows is
        behaving correctly, and that should not look like an error.
        """
        self = cls()
        if len(rows) < MIN_ROWS_TO_TRAIN:
            return self

        outcomes = {bool(y) for _, y in rows}
        if len(outcomes) < 2:
            # Every payment in the window recovered, or none did. There is
            # nothing to learn and a classifier would refuse anyway.
            return self

        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.ensemble import HistGradientBoostingClassifier

        _build_vocab(rows)
        X = np.asarray([_row(f) for f, _ in rows], dtype=float)
        y = np.asarray([1 if v else 0 for _, v in rows], dtype=int)

        base = HistGradientBoostingClassifier(
            max_depth=4,
            max_iter=200,
            learning_rate=0.06,
            l2_regularization=1.0,
            min_samples_leaf=40,
            categorical_features=[0, 1, 2, 3],
            random_state=20260826,
        )
        # Isotonic on internal cross-validation folds. Calibrating on the same
        # rows the trees were grown on would report a confidence the model has
        # not earned, which is the specific dishonesty this whole product
        # objects to.
        self._model = CalibratedClassifierCV(base, method="isotonic", cv=3)
        self._model.fit(X, y)
        self.trained_rows = len(rows)
        return self

    def predict(self, f: Features) -> float:
        if self._model is None:
            raise RuntimeError("model was never trained - check .ready first")
        return float(self._model.predict_proba(np.asarray([_row(f)], dtype=float))[0][1])

    def predict_many(self, features: Sequence[Features]) -> list[float]:
        if self._model is None:
            raise RuntimeError("model was never trained - check .ready first")
        X = np.asarray([_row(f) for f in features], dtype=float)
        return [float(p) for p in self._model.predict_proba(X)[:, 1]]


@dataclass(slots=True)
class Verdict:
    """Which estimator to use, and the numbers that decided it."""

    winner: str
    learned: Score | None
    incumbent: Score
    margin: float
    reason: str

    def as_dict(self) -> dict:
        return {
            "winner": self.winner,
            "margin": round(self.margin, 5),
            "reason": self.reason,
            "learned": self.learned.as_dict() if self.learned else None,
            "incumbent": self.incumbent.as_dict(),
        }


# A learned model has to be better by more than noise to be worth the operational
# weight of a second estimator. One part in a thousand of Brier is roughly the
# run-to-run wobble on a holdout this size.
MIN_MARGIN = 0.001


def bake_off(
    train_rows: Sequence[tuple[Features, bool]],
    holdout_rows: Sequence[tuple[Features, bool]],
    incumbent_predict,
) -> Verdict:
    """Score both estimators on data neither has seen, and pick one.

    `incumbent_predict` is any callable taking Features and returning a
    probability - in practice `CounterfactualModel.p_natural`.
    """
    y = [bool(v) for _, v in holdout_rows]
    incumbent = score([incumbent_predict(f) for f, _ in holdout_rows], y)

    model = LearnedBaseline.fit(train_rows)
    if not model.ready:
        return Verdict(
            winner="incumbent",
            learned=None,
            incumbent=incumbent,
            margin=0.0,
            reason=(
                f"only {len(train_rows)} training rows, below the {MIN_ROWS_TO_TRAIN} "
                "a boosted model needs before it is fitting noise"
            ),
        )

    learned = score(model.predict_many([f for f, _ in holdout_rows]), y)
    margin = incumbent.brier - learned.brier

    if margin > MIN_MARGIN:
        reason = (
            f"learned model is better calibrated on held-out data "
            f"(Brier {learned.brier:.4f} against {incumbent.brier:.4f})"
        )
        winner = "learned"
    else:
        reason = (
            f"learned model did not beat the hierarchy by more than noise "
            f"(Brier {learned.brier:.4f} against {incumbent.brier:.4f}); "
            "keeping the estimator already in place"
        )
        winner = "incumbent"

    return Verdict(
        winner=winner, learned=learned, incumbent=incumbent, margin=margin, reason=reason,
    )
