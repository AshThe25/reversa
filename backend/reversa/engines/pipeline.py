"""Orchestration: detection through measurement, persisted and audited.

One place that runs the whole loop, so the API, the tests and the demo all
exercise the same code path rather than three variations that drift.

Every stage writes to the audit chain before moving on. That ordering matters:
the record of a decision has to exist independently of whether the next stage
succeeds, or a crash mid-execution leaves money moved and no explanation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reversa.config import Settings, get_settings
from reversa.engines import experiment_engine as EX
from reversa.engines import incident_engine as IE
from reversa.engines import simulation_engine as SIM
from reversa.engines.audit_engine import record
from reversa.engines.cohort_engine import CohortBuild, build_cohort
from reversa.engines.counterfactual_engine import CounterfactualModel
from reversa.engines.portfolio_optimizer import Candidate
from reversa.models import (
    ActionResult, Arm, Cohort, Experiment, ExperimentAssignment, Incident,
    IncidentStatus, RecoveryAction, RecoveryCandidate, RecoveryStrategy,
    SimulationRun, SimulationScenario, WorldMeta,
)
from reversa.world import params as P
from reversa.world.outcomes import realise


def _id(kind: str, seed: str) -> str:
    import hashlib
    return f"{kind}_{hashlib.sha256(seed.encode()).hexdigest()[:14]}"


@dataclass(slots=True)
class DemoClock:
    live_day: datetime
    now: datetime


def clock(session: Session) -> DemoClock:
    meta = session.get(WorldMeta, "world")
    if meta is None:
        raise RuntimeError("world has not been generated - run scripts.seed_world")
    return DemoClock(
        live_day=datetime.fromisoformat(meta.value["live_day"]),
        now=datetime.fromisoformat(meta.value["demo_clock"]),
    )


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------


def persist_incidents(
    session: Session,
    detected: Sequence[IE.DetectedIncident],
    *,
    merchant_id: str,
    now: datetime,
) -> list[Incident]:
    """Write detector output as durable incidents, idempotently.

    Keyed on slice plus first-seen so a re-scan updates rather than duplicates -
    the API re-runs detection on demand and a judge clicking twice must not
    double the incident list or the revenue exposed.
    """
    out: list[Incident] = []
    newly_seen: list[Incident] = []
    for d in detected:
        peak, worst = d.peak, d.worst
        obs = worst.observation
        incident_id = _id("inc", f"{d.slice.key}|{d.first_seen.isoformat()}")

        exposed = obs.amount_failed_paise
        severity = worst.severity(exposed)

        row = session.get(Incident, incident_id)
        is_new = row is None
        if is_new:
            row = Incident(id=incident_id, merchant_id=merchant_id)
            session.add(row)

        row.label = f"{d.slice.label()} degradation"
        row.slice_method = None if d.slice.method == IE.GLOBAL else d.slice.method
        row.slice_instrument = (
            None if d.slice.instrument == IE.GLOBAL else d.slice.instrument
        )
        row.slice_key = d.slice.key
        row.detected_at = d.first_seen
        row.window_start = obs.window_start
        row.window_end = obs.window_end
        row.resolved_at = d.last_seen if d.last_seen < now - timedelta(minutes=15) else None
        row.status = IncidentStatus.RESOLVED if row.resolved_at else IncidentStatus.OPEN
        row.severity = severity
        row.baseline_success_rate = worst.baseline_rate
        row.observed_success_rate = obs.success_rate
        row.observed_volume = obs.n
        row.baseline_volume = worst.baseline_n
        row.ewma_deviation = worst.ewma_deviation
        row.p_value = peak.p_value
        row.q_value = peak.q_value
        row.detection_rationale = worst.rationale()
        row.revenue_exposed_paise = exposed
        row.affected_payment_count = obs.n - obs.successes

        # A degradation spread across slices with no common parent has no
        # containable scope, so no single root cause is supportable from the
        # evidence. Marked here; the policy layer refuses to automate it.
        row.rca_is_ambiguous = d.is_diffuse
        if d.is_diffuse:
            row.label = (
                f"Unattributed degradation across {len(d.diffuse_members)} "
                "unrelated slices"
            )
            row.rca_class = "AMBIGUOUS"
            row.rca_confidence = 0.0
            row.rca_evidence = {"diffuse_members": list(d.diffuse_members)}

        out.append(row)
        if is_new:
            newly_seen.append(row)

    session.flush()
    # Only the first sighting is an event. This route is hit on every dashboard
    # load, and re-recording "detected" each time turns the ledger into a page-view
    # counter - 36 entries for 4 incidents after a few refreshes. An audit trail
    # that grows when you reload a page is not an audit trail.
    for row in newly_seen:
        record(
            session, actor="sentinel", event_type="incident.detected",
            subject_type="incident", subject_id=row.id,
            payload={
                "slice": row.slice_key,
                "severity": row.severity,
                "q_value": row.q_value,
                "baseline_success_rate": round(row.baseline_success_rate, 4),
                "observed_success_rate": round(row.observed_success_rate, 4),
                "revenue_exposed_paise": row.revenue_exposed_paise,
                "ambiguous": row.rca_is_ambiguous,
            },
            occurred_at=row.detected_at,
        )
    session.flush()
    return out


# ---------------------------------------------------------------------------
# cohort
# ---------------------------------------------------------------------------


def persist_cohort(
    session: Session, incident: Incident, build: CohortBuild, *, now: datetime
) -> Cohort:
    cohort_id = _id("coh", f"{incident.id}|{build.window_start.isoformat()}")
    cohort = session.get(Cohort, cohort_id)
    if cohort is None:
        cohort = Cohort(id=cohort_id, incident_id=incident.id)
        session.add(cohort)

    cohort.built_at = now
    cohort.member_count = len(build.candidates)
    cohort.revenue_exposed_paise = build.revenue_exposed_paise
    cohort.inclusion_rule = {
        "slice": build.incident_slice,
        "window_start": build.window_start.isoformat(),
        "window_end": build.window_end.isoformat(),
        "status": "failed",
        "attribution_weight": round(build.attribution_weight, 4),
        "rail_down_now": build.rail_down_now,
        "exceptions": build.exceptions_by_reason(),
    }
    session.flush()

    existing = {
        r.payment_id
        for r in session.execute(
            select(RecoveryCandidate).where(RecoveryCandidate.cohort_id == cohort_id)
        ).scalars()
    }
    rows = []
    for c in build.candidates:
        if c.payment_id in existing:
            continue
        best = max(c.uplift.items(), key=lambda kv: kv[1], default=(None, 0.0))
        rows.append(RecoveryCandidate(
            id=_id("cnd", f"{cohort_id}|{c.payment_id}"),
            cohort_id=cohort_id, payment_id=c.payment_id, customer_id=c.customer_id,
            amount_paise=c.amount_paise, failure_class=c.failure_class,
            p_natural=c.p_natural, p_natural_lo=0.0, p_natural_hi=0.0,
            natural_evidence_n=0,
            uplift_by_action={
                a: {
                    "delta": round(d, 5),
                    "credible": bool(c.uplift_credible.get(a, False)),
                    "ev_paise": int(round(c.amount_paise * d)),
                }
                for a, d in c.uplift.items()
            },
            eligible_actions=list(c.eligible),
            gate_report={},
            best_action=best[0],
            best_action_ev_paise=int(round(c.amount_paise * best[1])),
            confidence=c.confidence,
        ))
    session.add_all(rows)
    session.flush()

    record(
        session, actor="cohort_engine", event_type="cohort.built",
        subject_type="cohort", subject_id=cohort_id,
        payload={
            "incident_id": incident.id,
            "members": cohort.member_count,
            "revenue_exposed_paise": cohort.revenue_exposed_paise,
            "natural_recovery_paise": build.natural_recovery_paise,
            "addressable_paise": build.addressable_paise,
            "exceptions": build.exceptions_by_reason(),
        },
        occurred_at=now,
    )
    return cohort


# ---------------------------------------------------------------------------
# wind tunnel
# ---------------------------------------------------------------------------


def persist_simulation(
    session: Session,
    cohort: Cohort,
    run: SIM.WindTunnelRun,
    *,
    now: datetime,
    seed: int,
) -> SimulationRun:
    run_id = _id("sim", f"{cohort.id}|{now.isoformat()}|{seed}")
    sim = SimulationRun(
        id=run_id, cohort_id=cohort.id, incident_id=cohort.incident_id,
        created_at=now, seed=seed, capacity=run.capacity,
        candidate_count=run.candidate_count, compute_ms=run.total_ms,
    )
    session.merge(sim)
    session.flush()

    for sc in run.scenarios:
        session.merge(SimulationScenario(
            id=_id("scn", f"{run_id}|{sc.key}"),
            run_id=run_id, key=sc.key, label=sc.label, description=sc.description,
            expected_recovery_paise=sc.gross_recovery_paise,
            natural_recovery_paise=sc.natural_recovery_paise,
            incremental_recovery_paise=sc.incremental_recovery_paise,
            action_count=sc.action_count, action_breakdown=sc.by_action,
            capacity_used=sc.capacity_used,
            capacity_exhausted_at=",".join(sc.exhausted) or None,
            intervention_cost_paise=sc.cost_paise,
            net_incremental_paise=sc.net_incremental_paise,
            customer_friction_score=sc.friction,
            wasted_action_count=sc.wasted_actions,
            policy_violations=sc.policy_violations,
            violation_detail=sc.violation_detail,
            confidence=sc.confidence, risk_score=sc.risk_score,
            assignment=sc.assignment, optimizer_status=sc.solver,
        ))
    session.flush()

    record(
        session, actor="simulation_engine", event_type="windtunnel.run",
        subject_type="cohort", subject_id=cohort.id,
        payload={
            "run_id": run_id,
            "scenarios": {
                s.key: {
                    "incremental_paise": s.incremental_recovery_paise,
                    "actions": s.action_count,
                    "net_paise": s.net_incremental_paise,
                }
                for s in run.scenarios
            },
            "best": run.best.key,
            "compute_ms": round(run.total_ms, 1),
        },
        occurred_at=now,
    )
    return sim


# ---------------------------------------------------------------------------
# execution + measurement
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ExecutionReport:
    experiment_id: str
    strategy_id: str
    scenario_key: str
    arms: dict[str, int]
    actions_executed: int
    result: EX.ExperimentResult
    balance: dict
    projected_incremental_paise: int

    def as_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "strategy_id": self.strategy_id,
            "scenario_key": self.scenario_key,
            "arms": self.arms,
            "actions_executed": self.actions_executed,
            "projected_incremental_paise": self.projected_incremental_paise,
            "balance": self.balance,
            "result": self.result.as_dict(),
        }


def execute_and_measure(
    session: Session,
    cohort: Cohort,
    sim: SimulationRun,
    scenario: SIM.ScenarioResult,
    candidates: Sequence[Candidate],
    *,
    now: datetime,
    settings: Settings | None = None,
    exploration_fraction: float = 0.05,
    selected_by: str = "operator",
) -> ExecutionReport:
    """Randomise, act, resolve, measure. The part that produces a causal number."""
    settings = settings or get_settings()

    strategy_id = _id("str", f"{cohort.id}|{scenario.key}")
    session.merge(RecoveryStrategy(
        id=strategy_id, cohort_id=cohort.id,
        scenario_id=_id("scn", f"{sim.id}|{scenario.key}"),
        selected_at=now, selected_by=selected_by,
        rationale=(
            f"{scenario.label}: projected incremental "
            f"{scenario.incremental_recovery_paise / 1e7:.2f}L across "
            f"{scenario.action_count} actions, net of "
            f"{scenario.cost_paise / 100:.0f} rupees of intervention cost."
        ),
    ))
    session.flush()

    experiment_id = _id("exp", f"{cohort.id}|{scenario.key}")

    # Already run? Return what it measured rather than treating anyone twice.
    prior = session.get(Experiment, experiment_id)
    if prior is not None and prior.status == "concluded":
        return ExecutionReport(
            experiment_id=experiment_id, strategy_id=strategy_id,
            scenario_key=scenario.key,
            arms=_arm_counts(session, experiment_id),
            actions_executed=session.execute(
                select(func.count()).select_from(RecoveryAction).where(
                    RecoveryAction.experiment_id == experiment_id,
                    RecoveryAction.result == ActionResult.EXECUTED,
                )
            ).scalar() or 0,
            result=EX.results(session, experiment_id),
            balance=EX.balance_report(
                {a.payment_id: a.arm for a in session.execute(
                    select(ExperimentAssignment).where(
                        ExperimentAssignment.experiment_id == experiment_id
                    )
                ).scalars()},
                {c.payment_id: c.amount_paise for c in candidates},
            ),
            projected_incremental_paise=scenario.incremental_recovery_paise,
        )

    EX.open_experiment(
        session, experiment_id=experiment_id, cohort_id=cohort.id,
        strategy_id=strategy_id,
        name=f"{cohort.incident_id} / {scenario.key}",
        holdout_fraction=settings.holdout_fraction,
        exploration_fraction=exploration_fraction, now=now,
    )

    # The experiment population is the set of payments the strategy would act
    # on - not the whole cohort. Randomising across every candidate leaves the
    # treatment arm mostly untreated, and comparing two near-identical
    # populations measures nothing.
    planned = set(scenario.assignment)
    population = [c for c in candidates if c.payment_id in planned]
    if not population:
        population = list(candidates)

    pairs = [(c.payment_id, c.customer_id) for c in population]
    arms = EX.assign(
        session, experiment_id, pairs,
        holdout_fraction=settings.holdout_fraction,
        exploration_fraction=exploration_fraction, now=now,
        exposure={c.payment_id: c.amount_paise for c in population},
    )

    eligible = {c.payment_id: c.eligible for c in population}
    by_payment = {c.payment_id: c for c in population}

    actions = {p: a for p, a in scenario.assignment.items() if p in arms}
    for pid, arm in arms.items():
        if arm == Arm.HOLDOUT.value:
            actions.pop(pid, None)
        elif arm == EX.EXPLORATION:
            # exploration overrides the optimiser on purpose: without a slice of
            # randomised assignment the uplift model slowly fossilises around its
            # own past decisions and can never learn about an action it stopped
            # choosing.
            pick = EX.random_legal_action(
                eligible.get(pid, ()), experiment_id=experiment_id, payment_id=pid
            )
            if pick:
                actions[pid] = pick

    action_rows = []
    for idx, (pid, action) in enumerate(sorted(actions.items())):
        cand = by_payment.get(pid)
        if cand is None:
            continue
        action_rows.append(RecoveryAction(
            id=_id("act", f"{experiment_id}|{pid}"),
            strategy_id=strategy_id, payment_id=pid, customer_id=cand.customer_id,
            experiment_id=experiment_id, action_type=action,
            result=ActionResult.EXECUTED,
            arm=Arm.TREATMENT.value,
            scheduled_at=now, executed_at=now,
            expected_incremental_paise=int(round(cand.amount_paise * cand.uplift.get(action, 0.0))),
            p_natural_at_decision=cand.p_natural,
            considered={
                a: {
                    "delta": round(cand.uplift.get(a, 0.0), 5),
                    "credible": bool(cand.uplift_credible.get(a, False)),
                    "eligible": a in cand.eligible,
                }
                for a in cand.uplift
            },
            gate_verdicts={"eligible_actions": list(cand.eligible)},
            cost_paise=P.ACTION_COST_PAISE.get(action, 0),
            adapter_mode="simulation",
        ))

    # holdout members get a row too - "we deliberately did nothing" is a
    # decision, and a plan with no record of its control group is unauditable
    for pid, arm in sorted(arms.items()):
        if arm != Arm.HOLDOUT.value:
            continue
        cand = by_payment.get(pid)
        if cand is None:
            continue
        action_rows.append(RecoveryAction(
            id=_id("act", f"{experiment_id}|{pid}"),
            strategy_id=strategy_id, payment_id=pid, customer_id=cand.customer_id,
            experiment_id=experiment_id, action_type="no_action",
            result=ActionResult.WITHHELD_HOLDOUT, arm=Arm.HOLDOUT.value,
            scheduled_at=now, executed_at=None,
            expected_incremental_paise=0,
            p_natural_at_decision=cand.p_natural,
            considered={}, gate_verdicts={},
            suppressed_reason="randomised holdout - measurement control",
            cost_paise=0, adapter_mode="simulation",
        ))

    session.add_all(action_rows)
    session.flush()

    record(
        session, actor="executor", event_type="strategy.executed",
        subject_type="experiment", subject_id=experiment_id,
        payload={
            "scenario": scenario.key,
            "actions": len(actions),
            "arms": _counts(arms),
            "holdout_fraction": settings.holdout_fraction,
            "exploration_fraction": exploration_fraction,
        },
        occurred_at=now,
    )

    resolved_arms = {
        pid: (Arm.TREATMENT.value if arm == EX.EXPLORATION else arm)
        for pid, arm in arms.items()
    }
    realise(
        session, experiment_id=experiment_id, assignments=actions,
        arms=resolved_arms, now=now,
    )

    result = EX.results(session, experiment_id)
    EX.conclude(session, experiment_id, result, now=now)

    record(
        session, actor="experiment_engine", event_type="experiment.measured",
        subject_type="experiment", subject_id=experiment_id,
        payload={
            "incremental_paise": result.incremental_paise,
            "ci": [result.incremental_lo_paise, result.incremental_hi_paise],
            "significant": result.significant,
            "gross_recovery_paise": result.gross_recovery_paise,
            "natural_recovery_paise": result.natural_recovery_paise,
            "measurement_cost_paise": result.measurement_cost_paise,
        },
        occurred_at=now,
    )

    return ExecutionReport(
        experiment_id=experiment_id, strategy_id=strategy_id,
        scenario_key=scenario.key, arms=_counts(arms),
        actions_executed=len(actions), result=result,
        balance=EX.balance_report(
            arms, {c.payment_id: c.amount_paise for c in population}
        ),
        projected_incremental_paise=scenario.incremental_recovery_paise,
    )


def _arm_counts(session: Session, experiment_id: str) -> dict[str, int]:
    rows = session.execute(
        select(ExperimentAssignment.arm, func.count())
        .where(ExperimentAssignment.experiment_id == experiment_id)
        .group_by(ExperimentAssignment.arm)
    ).all()
    return {arm: n for arm, n in rows}


def _counts(arms: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for arm in arms.values():
        out[arm] = out.get(arm, 0) + 1
    return out
