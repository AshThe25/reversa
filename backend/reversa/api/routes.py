"""HTTP surface.

Every number returned here is computed by an engine. There is no endpoint that
returns an authored figure, and the frontend has no arithmetic in it - if a
value appears on screen it came from this file, which came from a solver or a
count.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from reversa.adapters.razorpay_adapter import get_client
from reversa.api import state as engine_state
from reversa.api.schemas import (
    ChaosRequest, ExecuteRequest, ScanRequest, SessionRequest, WindTunnelRequest,
)
from reversa.api.deps import requires_execute, requires_read, requires_simulate
from reversa.config import Settings, get_settings
from reversa.db import get_session
from reversa.engines import experiment_engine as EX
from reversa.engines import pipeline as PL
from reversa.engines import simulation_engine as SIM
from reversa.engines.audit_engine import verify_chain
from reversa.engines.portfolio_optimizer import solve
from reversa.models import (
    AuditEvent, Cohort, Experiment, Incident, IncidentStatus, Payment,
    PaymentStatus, RecoveryAction, SimulationRun, WorldMeta,
)
from reversa.security.auth import DEMO, OPERATOR, Session, constant_time_equals, issue
from reversa.world import params as P
from reversa.world.generator import MERCHANT_ID

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# system
# ---------------------------------------------------------------------------


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/system")
def system(db: DbSession = Depends(get_session),
           settings: Settings = Depends(get_settings)) -> dict:
    """What mode everything is running in.

    Surfaced rather than buried: a payments demo that does not say out loud
    which numbers came from a live API and which from a simulator is doing the
    thing this whole project argues against.
    """
    client = get_client()
    world = db.get(WorldMeta, "world")
    st = engine_state.get(db)

    return {
        "adapters": {
            "razorpay": {
                "mode": "RAZORPAY TEST MODE" if not client.offline else "SIMULATION MODE",
                "live_calls": client.stats()["live_api_calls"],
                "payment_link_budget": client.link_budget.as_dict(),
                "note": (
                    "Razorpay test mode caps a business at 30 Payment Links and "
                    "does not support UPI Payment Links at all. Both limits are "
                    "enforced in the adapter, not worked around."
                ),
            },
            "llm": {
                "mode": "anthropic" if settings.has_llm else "deterministic fallback",
                "model": settings.llm_model if settings.has_llm else None,
            },
        },
        "world": world.value if world else None,
        "engine": {
            "fit_ms": round(st.fit_ms, 1),
            "scan_ms": round(st.scan_ms, 1),
            "incidents_detected": len(st.detected),
            "detector": st.diagnostics,
            "estimator": st.model.summary() if st.model else None,
        },
        "capacity_defaults": P.DEFAULT_CAPACITY,
    }


@router.post("/auth/session", status_code=status.HTTP_201_CREATED)
def create_session(body: SessionRequest = Body(default=SessionRequest()),
                   settings: Settings = Depends(get_settings)) -> dict:
    """Open a session.

    A correct access code gets operator scope, which includes EXECUTE. Without
    one, and only when demo sessions are enabled, the caller gets read plus
    simulate - enough to explore every future in the wind tunnel, not enough to
    commit one. That distinction is the point: an evaluator should be able to
    click everything without any path to moving money.
    """
    if body.access_code and settings.demo_access_code:
        if constant_time_equals(body.access_code, settings.demo_access_code):
            token, session = issue("operator", OPERATOR, settings.session_secret,
                                   ttl_seconds=settings.session_ttl_seconds)
            return {"token": token, "session": session.as_dict(), "role": "operator"}
        raise HTTPException(status_code=401, detail={"error": "invalid_access_code"})

    if not settings.allow_demo_sessions:
        raise HTTPException(status_code=403, detail={"error": "demo_sessions_disabled"})

    token, session = issue("demo", DEMO, settings.session_secret,
                           ttl_seconds=settings.session_ttl_seconds)
    return {"token": token, "session": session.as_dict(), "role": "demo"}


@router.get("/auth/me")
def whoami(session: Session = Depends(requires_read)) -> dict:
    return session.as_dict()


# ---------------------------------------------------------------------------
# command centre
# ---------------------------------------------------------------------------


@router.get("/overview")
def overview(db: DbSession = Depends(get_session),
             _: Session = Depends(requires_read)) -> dict:
    st = engine_state.get(db)
    incidents = PL.persist_incidents(db, st.detected, merchant_id=MERCHANT_ID,
                                     now=st.clock.now)
    db.commit()

    open_incidents = [i for i in incidents if i.status == IncidentStatus.OPEN]
    exposed = sum(i.revenue_exposed_paise for i in incidents)

    failed_today, failed_amount = db.execute(
        select(func.count(), func.coalesce(func.sum(Payment.amount_paise), 0))
        .where(Payment.era == "live", Payment.status == PaymentStatus.FAILED)
    ).one()

    concluded = db.execute(
        select(Experiment).where(Experiment.status == "concluded")
    ).scalars().all()
    measured_incremental = sum(
        (e.results or {}).get("incremental_paise", 0) for e in concluded
    )
    measured_natural = sum(
        (e.results or {}).get("natural_recovery_paise", 0) for e in concluded
    )

    used = dict(db.execute(
        select(RecoveryAction.action_type, func.count())
        .group_by(RecoveryAction.action_type)
    ).all())
    capacity_total = sum(P.DEFAULT_CAPACITY.values())
    capacity_used = sum(used.get(a, 0) for a in P.DEFAULT_CAPACITY)

    return {
        "as_of": st.clock.now.isoformat(),
        "revenue_at_risk_paise": exposed,
        "live_failed_payments": failed_today,
        "live_failed_amount_paise": int(failed_amount),
        "natural_recovery_paise": measured_natural,
        "incremental_recovery_paise": measured_incremental,
        "active_incidents": len(open_incidents),
        "total_incidents": len(incidents),
        "experiments_concluded": len(concluded),
        "capacity": {
            "used": capacity_used,
            "total": capacity_total,
            "by_action": {a: used.get(a, 0) for a in P.DEFAULT_CAPACITY},
        },
        "detector": st.diagnostics,
    }


# ---------------------------------------------------------------------------
# incidents
# ---------------------------------------------------------------------------


def _incident_dict(row: Incident) -> dict:
    return {
        "id": row.id,
        "label": row.label,
        "slice": row.slice_key,
        "method": row.slice_method,
        "instrument": row.slice_instrument,
        "severity": row.severity,
        "status": row.status,
        "detected_at": row.detected_at.isoformat(),
        "window_start": row.window_start.isoformat(),
        "window_end": row.window_end.isoformat(),
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "baseline_success_rate": row.baseline_success_rate,
        "observed_success_rate": row.observed_success_rate,
        "observed_volume": row.observed_volume,
        "affected_payment_count": row.affected_payment_count,
        "revenue_exposed_paise": row.revenue_exposed_paise,
        "p_value": row.p_value,
        "q_value": row.q_value,
        "detection_rationale": row.detection_rationale,
    }


@router.post("/incidents/scan")
def scan(body: ScanRequest = Body(default=ScanRequest()),
         db: DbSession = Depends(get_session),
         _: Session = Depends(requires_simulate)) -> dict:
    st = engine_state.get(db, force=body.force)
    rows = PL.persist_incidents(db, st.detected, merchant_id=MERCHANT_ID, now=st.clock.now)
    db.commit()
    return {
        "incidents": [_incident_dict(r) for r in rows],
        "diagnostics": st.diagnostics,
        "scan_ms": round(st.scan_ms, 1),
    }


@router.get("/incidents")
def list_incidents(db: DbSession = Depends(get_session),
                   _: Session = Depends(requires_read)) -> dict:
    st = engine_state.get(db)
    rows = PL.persist_incidents(db, st.detected, merchant_id=MERCHANT_ID, now=st.clock.now)
    db.commit()
    rows.sort(key=lambda r: r.revenue_exposed_paise, reverse=True)
    return {"incidents": [_incident_dict(r) for r in rows]}


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, db: DbSession = Depends(get_session),
                 _: Session = Depends(requires_read)) -> dict:
    row = db.get(Incident, incident_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_incident"})

    detected = engine_state.detected_by_id(db, incident_id)
    signals = []
    if detected:
        for s in detected.signals[:40]:
            signals.append({
                "at": s.observation.window_end.isoformat(),
                "window_minutes": s.observation.window_minutes,
                "n": s.observation.n,
                "success_rate": s.observation.success_rate,
                "baseline_rate": s.baseline_rate,
                "q_value": s.q_value,
                "top_reason": s.top_reason,
                "top_reason_share": s.top_reason_share,
                "rolled_up_from": list(s.rolled_up_from),
            })

    return {
        **_incident_dict(row),
        "signals": signals,
        "failure_mix": _failure_mix(db, row),
    }


def _failure_mix(db: DbSession, row: Incident) -> list[dict]:
    q = (
        select(Payment.failure_reason, Payment.failure_class,
               func.count(), func.sum(Payment.amount_paise))
        .where(
            Payment.status == PaymentStatus.FAILED,
            Payment.created_at >= row.window_start,
            Payment.created_at < row.window_end,
        )
        .group_by(Payment.failure_reason, Payment.failure_class)
        .order_by(func.count().desc())
        .limit(12)
    )
    if row.slice_method:
        q = q.where(Payment.method == row.slice_method)
    if row.slice_instrument:
        q = q.where(Payment.instrument == row.slice_instrument)

    return [
        {"reason": r, "failure_class": c, "count": n, "amount_paise": int(amt or 0)}
        for r, c, n, amt in db.execute(q).all()
    ]


@router.get("/incidents/{incident_id}/cohort")
def get_cohort(incident_id: str, db: DbSession = Depends(get_session),
               _: Session = Depends(requires_read)) -> dict:
    try:
        _, build = engine_state.cohort_for(db, incident_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "unknown_incident"})

    top = sorted(build.candidates, key=lambda c: -c.amount_paise)[:60]
    return {
        "incident_id": incident_id,
        **build.as_dict(),
        "exception_sample": [e.as_dict() for e in build.exceptions[:25]],
        "candidates": [
            {
                "payment_id": c.payment_id,
                "customer_id": c.customer_id,
                "amount_paise": c.amount_paise,
                "failure_class": c.failure_class,
                "method": c.method,
                "p_natural": round(c.p_natural, 4),
                "confidence": round(c.confidence, 4),
                "eligible": list(c.eligible),
                "uplift": {
                    a: {
                        "delta": round(d, 5),
                        "credible": bool(c.uplift_credible.get(a, False)),
                        "ev_paise": int(round(c.amount_paise * d)),
                    }
                    for a, d in sorted(c.uplift.items(), key=lambda kv: -kv[1])
                },
                "would_recover_anyway": c.would_recover_anyway,
            }
            for c in top
        ],
    }


# ---------------------------------------------------------------------------
# wind tunnel
# ---------------------------------------------------------------------------


@router.post("/windtunnel")
def wind_tunnel(body: WindTunnelRequest,
                db: DbSession = Depends(get_session),
                _: Session = Depends(requires_simulate)) -> dict:
    try:
        _, build = engine_state.cohort_for(db, body.incident_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "unknown_incident"})
    if not build.candidates:
        raise HTTPException(status_code=422,
                            detail={"error": "cohort_has_no_actionable_candidates"})

    capacity = {**P.DEFAULT_CAPACITY, **(body.capacity or {})}
    run = SIM.run(build.candidates, capacity)

    st = engine_state.get(db)
    incident = db.get(Incident, body.incident_id)
    cohort = PL.persist_cohort(db, incident, build, now=st.clock.now)
    PL.persist_simulation(db, cohort, run, now=st.clock.now, seed=20260826)
    db.commit()

    return {
        "incident_id": body.incident_id,
        "cohort": build.as_dict(),
        **run.as_dict(),
    }


@router.post("/chaos")
def chaos(body: ChaosRequest, db: DbSession = Depends(get_session),
          _: Session = Depends(requires_simulate)) -> dict:
    """What the current plan does under a stressed world.

    Volume and capacity are scaled, the optimiser is re-solved, and the result
    includes when each capacity pool runs dry at the given arrival rate. It is
    arithmetic over a real re-solve, not an animation.
    """
    try:
        _, build = engine_state.cohort_for(db, body.incident_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "unknown_incident"})

    scaled_capacity = {
        a: int(limit * body.capacity_multiplier)
        for a, limit in P.DEFAULT_CAPACITY.items()
    }
    candidates = list(build.candidates)
    if body.volume_multiplier > 1:
        # replay the cohort to model a heavier day. ids are suffixed so the
        # optimiser treats them as distinct payments rather than deduping.
        extra = int(len(candidates) * (body.volume_multiplier - 1))
        base = candidates[:]
        for i in range(extra):
            src = base[i % len(base)]
            clone = type(src)(**{**src.__dict__, "payment_id": f"{src.payment_id}#c{i}",
                                 "customer_id": f"{src.customer_id}#c{i}"})
            candidates.append(clone)

    baseline = SIM.run(build.candidates, P.DEFAULT_CAPACITY)
    stressed = SIM.run(candidates, scaled_capacity)
    plan = solve(candidates, scaled_capacity)

    return {
        "incident_id": body.incident_id,
        "volume_multiplier": body.volume_multiplier,
        "capacity_multiplier": body.capacity_multiplier,
        "candidates": len(candidates),
        "baseline": baseline.best.as_dict(),
        "stressed": stressed.best.as_dict(),
        "exhaustion_minutes": SIM.time_to_capacity_exhaustion(
            plan, body.arrivals_per_minute
        ),
        "capacity": scaled_capacity,
    }


# ---------------------------------------------------------------------------
# execution + experiments
# ---------------------------------------------------------------------------


@router.post("/experiments/execute")
def execute(body: ExecuteRequest, db: DbSession = Depends(get_session),
            session: Session = Depends(requires_execute)) -> dict:
    try:
        _, build = engine_state.cohort_for(db, body.incident_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "unknown_incident"})
    if not build.candidates:
        raise HTTPException(status_code=422,
                            detail={"error": "cohort_has_no_actionable_candidates"})

    st = engine_state.get(db)
    capacity = {**P.DEFAULT_CAPACITY, **(body.capacity or {})}
    run = SIM.run(build.candidates, capacity)

    scenario = next((s for s in run.scenarios if s.key == body.scenario), None)
    if scenario is None:
        raise HTTPException(status_code=422, detail={
            "error": "unknown_scenario",
            "available": [s.key for s in run.scenarios],
        })

    incident = db.get(Incident, body.incident_id)
    cohort = PL.persist_cohort(db, incident, build, now=st.clock.now)
    sim = PL.persist_simulation(db, cohort, run, now=st.clock.now, seed=20260826)

    settings = get_settings()
    settings_override = settings.model_copy(
        update={"holdout_fraction": body.holdout_fraction}
    )
    report = PL.execute_and_measure(
        db, cohort, sim, scenario, build.candidates, now=st.clock.now,
        settings=settings_override, exploration_fraction=body.exploration_fraction,
        selected_by=session.subject,
    )
    db.commit()
    return report.as_dict()


@router.get("/experiments")
def list_experiments(db: DbSession = Depends(get_session),
                     _: Session = Depends(requires_read)) -> dict:
    rows = db.execute(
        select(Experiment).order_by(Experiment.started_at.desc()).limit(50)
    ).scalars().all()
    return {
        "experiments": [
            {
                "id": e.id, "name": e.name, "status": e.status,
                "cohort_id": e.cohort_id,
                "holdout_fraction": e.holdout_fraction,
                "assignment_method": e.assignment_method,
                "started_at": e.started_at.isoformat(),
                "concluded_at": e.concluded_at.isoformat() if e.concluded_at else None,
                "results": e.results or {},
            }
            for e in rows
        ]
    }


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: str, db: DbSession = Depends(get_session),
                   _: Session = Depends(requires_read)) -> dict:
    exp = db.get(Experiment, experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_experiment"})
    live = EX.results(db, experiment_id)
    return {
        "id": exp.id, "name": exp.name, "status": exp.status,
        "holdout_fraction": exp.holdout_fraction,
        "assignment_method": exp.assignment_method,
        "started_at": exp.started_at.isoformat(),
        "results": live.as_dict(),
    }


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


@router.get("/audit")
def audit(limit: int = 100, db: DbSession = Depends(get_session),
          _: Session = Depends(requires_read)) -> dict:
    limit = max(1, min(limit, 500))
    rows = db.execute(
        select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit)
    ).scalars().all()
    return {
        "events": [
            {
                "seq": r.seq, "id": r.id, "at": r.occurred_at.isoformat(),
                "actor": r.actor, "event_type": r.event_type,
                "subject_type": r.subject_type, "subject_id": r.subject_id,
                "payload": r.payload,
                "prev_hash": r.prev_hash[:16], "entry_hash": r.entry_hash[:16],
            }
            for r in rows
        ]
    }


@router.get("/audit/verify")
def audit_verify(db: DbSession = Depends(get_session),
                 _: Session = Depends(requires_read)) -> dict:
    """Recompute the whole chain and report the first divergence, if any."""
    return verify_chain(db).as_dict()
