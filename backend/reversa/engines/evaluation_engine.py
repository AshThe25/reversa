"""Scoring Reversa against the world's hidden answer key.

This is the ONLY module allowed to read GroundTruth.
tests/test_ground_truth_isolation.py walks the AST of everything else under
reversa/ and fails the build if anything so much as names it.

Everything here answers one question: was the system right? Not "does the system
report a nice number" - the system reporting its own number is precisely what
this exists to check.

The metric that matters most is the last one. The experiment engine estimates
incremental revenue from a randomised holdout and quotes a confidence interval.
The simulator knows the true incremental revenue exactly, because it knows each
payment's latent U and both potential outcomes. Comparing the two is a test of
the *measurement*, not of the recovery: if the holdout estimate's interval
contains the truth, the experiment design is sound. If it does not, the headline
number on every other page is worth nothing, and this page says so.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Sequence

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from reversa.engines import incident_engine as IE
from reversa.models import (
    Arm, DowntimeRecord, GroundTruth, Payment, RecoveryAction, RecoveryOutcome, WorldMeta,
)

# How close a detection has to be to a true onset to count as the same event.
MATCH_WINDOW = timedelta(minutes=25)

# Above this estimated natural-recovery probability, an intervention is counted
# as a false positive: we spent capacity on someone the model itself expected to
# pay anyway.
WASTE_THRESHOLD = 0.70

CALIBRATION_BINS = 10


@dataclass(slots=True)
class DetectionScore:
    true_incidents: int
    detected: int
    matched: int
    missed: list[str] = field(default_factory=list)
    false_alarms: int = 0
    latencies_min: list[float] = field(default_factory=list)
    downtime_lead_min: list[float] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.matched / self.true_incidents if self.true_incidents else 0.0

    @property
    def precision(self) -> float:
        return (self.detected - self.false_alarms) / self.detected if self.detected else 0.0

    @property
    def median_latency_min(self) -> float | None:
        return float(np.median(self.latencies_min)) if self.latencies_min else None

    def as_dict(self) -> dict:
        return {
            "true_incidents": self.true_incidents,
            "detected": self.detected,
            "matched": self.matched,
            "missed": self.missed,
            "false_alarms": self.false_alarms,
            "recall": round(self.recall, 4),
            "precision": round(self.precision, 4),
            "median_latency_min": (
                round(self.median_latency_min, 1) if self.median_latency_min is not None else None
            ),
            "latencies_min": [round(x, 1) for x in self.latencies_min],
        }


@dataclass(slots=True)
class CalibrationScore:
    n: int
    brier: float
    expected_calibration_error: float
    mean_predicted: float
    mean_actual: float
    bins: list[dict] = field(default_factory=list)

    @property
    def bias(self) -> float:
        """Positive means the estimator is systematically over-confident that
        payments recover on their own - which would make it under-intervene."""
        return self.mean_predicted - self.mean_actual

    def as_dict(self) -> dict:
        return {
            "n": self.n,
            "brier": round(self.brier, 5),
            "expected_calibration_error": round(self.expected_calibration_error, 5),
            "mean_predicted": round(self.mean_predicted, 5),
            "mean_actual": round(self.mean_actual, 5),
            "bias": round(self.bias, 5),
            "bins": self.bins,
        }


@dataclass(slots=True)
class DecisionScore:
    decisions: int
    chose_true_best: int
    chose_positive_uplift: int
    chose_harmful: int
    flagged_wasteful: int
    """Actions the system ITSELF expected to be waste - high estimated natural
    recovery. This is the proxy an operator sees, since truth is unavailable."""
    truly_ineffective: int
    """Actions whose TRUE uplift was <= 0. Only knowable here."""
    mean_regret: float

    @property
    def top1_accuracy(self) -> float:
        return self.chose_true_best / self.decisions if self.decisions else 0.0

    @property
    def positive_rate(self) -> float:
        return self.chose_positive_uplift / self.decisions if self.decisions else 0.0

    @property
    def effective_rate(self) -> float:
        return 1.0 - (self.truly_ineffective / self.decisions) if self.decisions else 0.0

    def as_dict(self) -> dict:
        return {
            "decisions": self.decisions,
            "top1_accuracy": round(self.top1_accuracy, 4),
            "chose_positive_uplift_rate": round(self.positive_rate, 4),
            "chose_harmful": self.chose_harmful,
            "flagged_wasteful": self.flagged_wasteful,
            "truly_ineffective": self.truly_ineffective,
            "effective_rate": round(self.effective_rate, 4),
            "mean_regret_uplift_points": round(self.mean_regret, 5),
            "note": (
                "top1_accuracy is scored against the best action that was "
                "actually AVAILABLE - grading the optimizer against an option a "
                "compliance gate had already removed would measure the gates, "
                "not the optimizer."
            ),
        }


@dataclass(slots=True)
class MeasurementScore:
    """The headline: does the holdout estimate recover the truth?"""

    experiment_id: str
    estimated_paise: int
    estimated_lo_paise: int
    estimated_hi_paise: int
    true_paise: int
    treated_payments: int

    @property
    def interval_contains_truth(self) -> bool:
        return self.estimated_lo_paise <= self.true_paise <= self.estimated_hi_paise

    @property
    def relative_error(self) -> float | None:
        if self.true_paise == 0:
            return None
        return (self.estimated_paise - self.true_paise) / abs(self.true_paise)

    def as_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "estimated_paise": self.estimated_paise,
            "estimated_lo_paise": self.estimated_lo_paise,
            "estimated_hi_paise": self.estimated_hi_paise,
            "true_paise": self.true_paise,
            "treated_payments": self.treated_payments,
            "interval_contains_truth": self.interval_contains_truth,
            "relative_error": (
                round(self.relative_error, 4) if self.relative_error is not None else None
            ),
        }


def score_detection(
    session: Session, detected: Sequence[IE.DetectedIncident], *, era: str = "live"
) -> DetectionScore:
    meta = session.get(WorldMeta, "true_incidents")
    truth = [i for i in (meta.value["incidents"] if meta else []) if i["era"] == era]

    score = DetectionScore(true_incidents=len(truth), detected=len(detected), matched=0)
    unmatched = set(range(len(detected)))

    for t in truth:
        start = datetime.fromisoformat(t["start"])
        end = datetime.fromisoformat(t["end"])
        hits = [
            (idx, d) for idx, d in enumerate(detected)
            if start - timedelta(minutes=5) <= d.first_seen <= end + MATCH_WINDOW
        ]
        if not hits:
            score.missed.append(t["template"])
            continue
        score.matched += 1
        first = min(hits, key=lambda h: h[1].first_seen)
        score.latencies_min.append((first[1].first_seen - start).total_seconds() / 60)
        for idx, _ in hits:
            unmatched.discard(idx)

    score.false_alarms = len(unmatched)
    return score


def score_lead_over_downtime_feed(
    session: Session, detected: Sequence[IE.DetectedIncident], *, era: str = "live"
) -> dict:
    """How far ahead of the platform's own downtime feed the detector was.

    This is the problem the feed cannot solve for a merchant: Razorpay publishes
    downtime some minutes after onset, and not for every event. A merchant who
    waits for it learns late, or never - and the payments lost in that window
    are lost before anyone knows there is a window.

    Detecting from the merchant's own authorisation stream removes the
    dependency. This measures whether that actually buys time, per incident,
    against the feed's own published begin time - which is why the detector
    never reads the feed as a trigger, only as corroboration afterwards.

    Incidents the feed never publishes are counted separately. For those the
    lead is not a number of minutes, it is the difference between knowing and
    not knowing.
    """
    meta = session.get(WorldMeta, "true_incidents")
    truth = [i for i in (meta.value["incidents"] if meta else []) if i["era"] == era]

    rows = session.execute(select(DowntimeRecord)).scalars().all()
    leads: list[float] = []
    never_published = 0
    per_incident: list[dict] = []

    for t in truth:
        start = datetime.fromisoformat(t["start"])
        end = datetime.fromisoformat(t["end"])

        ours = [
            d.first_seen for d in detected
            if start - timedelta(minutes=5) <= d.first_seen <= end + MATCH_WINDOW
        ]
        if not ours:
            continue                      # missed entirely; counted by score_detection
        detected_at = min(ours)

        method = t.get("method") or ""
        published = [
            r.begin for r in rows
            if (not method or r.method == method) and start <= r.begin <= end + MATCH_WINDOW
        ]
        if not published:
            never_published += 1
            per_incident.append({
                "template": t["template"],
                "lead_minutes": None,
                "feed_published": False,
            })
            continue

        lead = (min(published) - detected_at).total_seconds() / 60
        leads.append(lead)
        per_incident.append({
            "template": t["template"],
            "lead_minutes": round(lead, 1),
            "feed_published": True,
        })

    leads.sort()
    median = leads[len(leads) // 2] if leads else None
    return {
        "incidents_compared": len(per_incident),
        "feed_published": len(leads),
        "feed_never_published": never_published,
        "median_lead_minutes": round(median, 1) if median is not None else None,
        "ahead_of_feed": sum(1 for x in leads if x > 0),
        "per_incident": per_incident,
    }


def score_calibration(session: Session, experiment_id: str) -> CalibrationScore | None:
    """Reliability of the natural-recovery estimate, on the holdout only.

    The holdout is the only group where the estimate is directly testable,
    because nothing was done to them - so their realised outcome *is* the natural
    outcome. Scoring on the treated group would be measuring something else.
    """
    rows = session.execute(
        select(RecoveryAction.p_natural_at_decision, RecoveryOutcome.recovered)
        .join(RecoveryOutcome, RecoveryOutcome.payment_id == RecoveryAction.payment_id)
        .where(
            RecoveryAction.experiment_id == experiment_id,
            RecoveryOutcome.experiment_id == experiment_id,
            RecoveryOutcome.arm == Arm.HOLDOUT.value,
        )
    ).all()
    if len(rows) < 20:
        return None

    predicted = np.array([r[0] for r in rows], dtype=float)
    actual = np.array([1.0 if r[1] else 0.0 for r in rows], dtype=float)

    brier = float(np.mean((predicted - actual) ** 2))

    edges = np.linspace(0, 1, CALIBRATION_BINS + 1)
    bins, ece = [], 0.0
    for i in range(CALIBRATION_BINS):
        lo, hi = edges[i], edges[i + 1]
        mask = (predicted >= lo) & (predicted < hi if i < CALIBRATION_BINS - 1 else predicted <= hi)
        n = int(mask.sum())
        if n == 0:
            continue
        p_mean = float(predicted[mask].mean())
        a_mean = float(actual[mask].mean())
        ece += (n / len(rows)) * abs(p_mean - a_mean)
        bins.append({
            "bin_lo": round(float(lo), 2), "bin_hi": round(float(hi), 2),
            "n": n, "predicted": round(p_mean, 4), "actual": round(a_mean, 4),
        })

    return CalibrationScore(
        n=len(rows), brier=brier, expected_calibration_error=float(ece),
        mean_predicted=float(predicted.mean()), mean_actual=float(actual.mean()),
        bins=bins,
    )


def score_decisions(session: Session, experiment_id: str) -> DecisionScore:
    """Did the optimiser pick the action the world says was actually best?"""
    rows = session.execute(
        select(
            RecoveryAction.action_type, RecoveryAction.p_natural_at_decision,
            RecoveryAction.considered,
            GroundTruth.true_uplift_by_action,
        )
        .join(GroundTruth, GroundTruth.payment_id == RecoveryAction.payment_id)
        .where(
            RecoveryAction.experiment_id == experiment_id,
            RecoveryAction.arm == Arm.TREATMENT.value,
            RecoveryAction.action_type != "no_action",
        )
    ).all()

    if not rows:
        return DecisionScore(0, 0, 0, 0, 0, 0, 0.0)

    best_hits = positive = harmful = flagged = ineffective = 0
    regrets: list[float] = []

    for action, p_nat, considered, uplifts in rows:
        uplifts = uplifts or {}
        chosen = float(uplifts.get(action, 0.0))

        # Grade against the best option that was actually on the table. The
        # optimizer cannot pick an action a gate removed, and scoring it against
        # one measures the gates rather than the decision.
        available = {
            a for a, meta in (considered or {}).items()
            if isinstance(meta, dict) and meta.get("eligible")
        } or set(uplifts)
        reachable = {a: v for a, v in uplifts.items() if a in available}
        best_value = max(reachable.values()) if reachable else 0.0
        best_action = max(reachable, key=reachable.get) if reachable else None

        if action == best_action:
            best_hits += 1
        if chosen > 0:
            positive += 1
        else:
            ineffective += 1
        if chosen < 0:
            harmful += 1
        if p_nat >= WASTE_THRESHOLD:
            flagged += 1
        regrets.append(max(0.0, best_value - chosen))

    return DecisionScore(
        decisions=len(rows), chose_true_best=best_hits,
        chose_positive_uplift=positive, chose_harmful=harmful,
        flagged_wasteful=flagged, truly_ineffective=ineffective,
        mean_regret=float(np.mean(regrets)) if regrets else 0.0,
    )


def true_incremental(session: Session, experiment_id: str) -> tuple[int, int]:
    """Exact incremental revenue from the potential outcomes. (paise, treated n).

    No sampling error at all: a payment contributes its full amount if and only
    if the realised action moved its latent U across the threshold, which is
    recorded when the world resolved the outcome.
    """
    rows = session.execute(
        select(Payment.amount_paise, GroundTruth.realised_incremental)
        .join(GroundTruth, GroundTruth.payment_id == Payment.id)
        .join(RecoveryOutcome, RecoveryOutcome.payment_id == Payment.id)
        .where(
            RecoveryOutcome.experiment_id == experiment_id,
            RecoveryOutcome.arm == Arm.TREATMENT.value,
        )
    ).all()
    total = sum(amount for amount, incremental in rows if incremental)
    return int(total), len(rows)


def score_measurement(
    session: Session, experiment_id: str, estimate: dict
) -> MeasurementScore:
    truth, treated = true_incremental(session, experiment_id)
    return MeasurementScore(
        experiment_id=experiment_id,
        estimated_paise=int(estimate.get("incremental_paise", 0)),
        estimated_lo_paise=int(estimate.get("incremental_lo_paise", 0)),
        estimated_hi_paise=int(estimate.get("incremental_hi_paise", 0)),
        true_paise=truth,
        treated_payments=treated,
    )


def score_cohort(session: Session, experiment_id: str, incident_template: str | None = None) -> dict:
    """Did the cohort actually contain the payments the incident broke?

    Membership is a claim about causation, and it is checkable here: the world
    recorded which payments were truly inside an incident window on the affected
    slice.
    """
    rows = session.execute(
        select(GroundTruth.is_incident_member)
        .join(RecoveryOutcome, RecoveryOutcome.payment_id == GroundTruth.payment_id)
        .where(RecoveryOutcome.experiment_id == experiment_id)
    ).scalars().all()
    if not rows:
        return {"members": 0, "precision": None}

    true_members = sum(1 for r in rows if r)
    return {
        "members": len(rows),
        "true_incident_members": true_members,
        "precision": round(true_members / len(rows), 4),
        "note": (
            "Share of cohort members that were genuinely inside a true incident "
            "window. The remainder are ordinary baseline failures the window "
            "swept up - which is what the attribution weight discounts for."
        ),
    }


def evaluate(session: Session, *, detected: Sequence[IE.DetectedIncident]) -> dict:
    """Full report. Every number here is Reversa graded against the simulator."""
    started = time.perf_counter()

    detection = score_detection(session, detected)

    experiments = session.execute(
        select(RecoveryOutcome.experiment_id).distinct()
    ).scalars().all()

    per_experiment = []
    for experiment_id in experiments:
        if not experiment_id:
            continue
        from reversa.engines.experiment_engine import results as measure

        estimate = measure(session, experiment_id).as_dict()
        calibration = score_calibration(session, experiment_id)
        per_experiment.append({
            "experiment_id": experiment_id,
            "measurement": score_measurement(session, experiment_id, estimate).as_dict(),
            "calibration": calibration.as_dict() if calibration else None,
            "decisions": score_decisions(session, experiment_id).as_dict(),
            "cohort": score_cohort(session, experiment_id),
        })

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "detection": detection.as_dict(),
        "downtime_feed": score_lead_over_downtime_feed(session, detected),
        "experiments": per_experiment,
        "compute_ms": round((time.perf_counter() - started) * 1000, 1),
        "method_note": (
            "The simulator holds each payment's latent resolve and both potential "
            "outcomes. Reversa never reads them - an import-graph test enforces "
            "that. These figures are the system's output compared against that "
            "answer key, including where it was wrong."
        ),
    }
