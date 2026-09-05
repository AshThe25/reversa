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
    ChaosRequest, ExecuteRequest, PolicyCompileRequest, PolicySimulateRequest,
    ScanRequest, SessionRequest, WindTunnelRequest,
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

# incident id -> agent trace. Bounded because it is keyed on a set of incidents
# that is small by construction; a reseed changes the ids and the old entries
# become unreachable rather than stale.
_TRACE_CACHE: dict[str, dict] = {}
router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# system
# ---------------------------------------------------------------------------


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/system")
def system(db: DbSession = Depends(get_session),
           settings: Settings = Depends(get_settings),
           _: Session = Depends(requires_read)) -> dict:
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
        "ambiguous": row.rca_is_ambiguous,
        "rca_class": row.rca_class,
        "rca_confidence": row.rca_confidence,
        "rca_evidence": row.rca_evidence or {},
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


@router.get("/incidents/{incident_id}/investigation")
def investigation(incident_id: str, db: DbSession = Depends(get_session),
                  _: Session = Depends(requires_read)) -> dict:
    """Evidence, and the root-cause finding weighed from it.

    Every claim in the finding cites evidence by id, and a citation that does
    not resolve rejects the whole response - that check is what the groundedness
    score reports. INSUFFICIENT_EVIDENCE is a first-class answer here, not an
    error path.
    """
    from reversa.ai.agent import run_agent, run_deterministic
    from reversa.ai.investigator import investigate
    from reversa.engines.evidence_engine import collect

    from reversa.ai.probes import Probes

    detected = engine_state.detected_by_id(db, incident_id)
    if detected is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_incident"})

    # The whole response is cached, not half of it.
    #
    # An earlier version cached only the agent trace, which missed the point:
    # `investigate` makes a model call of its own, so every view still paid for
    # one even when the answer was already known. The world is static between
    # reseeds - same incident, same evidence, same finding - so the first reader
    # pays for it and nobody after them does.
    cached = _TRACE_CACHE.get(incident_id)
    if cached is not None:
        return cached

    st = engine_state.get(db)
    evidence = collect(db, detected, now=st.clock.now)
    finding = investigate(evidence)

    # The agent works the same evidence as a sequence of questions rather than
    # one pile, writing its own query arguments. The finding stays
    # authoritative; the trace is how the conclusion was reached, which is the
    # part a reviewer needs in order to disagree with it.
    #
    # It is an enhancement on top of a finding that already exists, so a failure
    # inside it must not take the page down - production 500'd on every
    # investigation once because the loop read the wrong attribute off the model
    # result, on a path no local run exercises without a key.
    try:
        trace, _conclusion = run_agent(
            evidence, probes=Probes(db, now=st.clock.now, prefix=incident_id[-6:]),
        )
    except Exception:
        log.exception("investigation agent failed; falling back to the rule-based trace")
        trace = run_deterministic(evidence)

    payload = {"incident_id": incident_id, **finding.as_dict(), "trace": trace.as_dict()}
    _TRACE_CACHE[incident_id] = payload
    return payload


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


@router.get("/review")
def review_queue(incident: str, db: DbSession = Depends(get_session),
                 _: Session = Depends(requires_read)) -> dict:
    """The actions a person has to see before they happen.

    Not every action: a queue containing all of them is a rubber stamp, and a
    rubber stamp launders an automated decision as a human one. The triage rule
    is deterministic and travels with each row, so a reviewer can see not only
    what they are approving but why this one reached them and the ones above it
    did not.
    """
    from reversa.ai.investigator import investigate
    from reversa.engines.evidence_engine import collect
    from reversa.engines import review_engine as RV

    try:
        detected, build = engine_state.cohort_for(db, incident)
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "unknown_incident"})

    st = engine_state.get(db)
    plan = solve(list(build.candidates), P.DEFAULT_CAPACITY)

    # An unattributed cause raises the bar for everything in the plan, so the
    # finding has to be read here rather than assumed.
    finding = investigate(collect(db, detected, now=st.clock.now))
    cases = RV.build_queue(
        plan.assignments, build.candidates, cause_resolved=finding.actionable,
    )

    return {
        "incident_id": incident,
        "cause_resolved": finding.actionable,
        "root_cause": finding.root_cause,
        "summary": RV.summarise(cases),
        "cases": [c.as_dict() for c in cases],
        "thresholds": {"high_value_paise": RV.HIGH_VALUE_PAISE},
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


# ---------------------------------------------------------------------------
# policies
# ---------------------------------------------------------------------------


@router.get("/policies/capabilities")
def policy_capabilities(_: Session = Depends(requires_read)) -> dict:
    """What a merchant policy can and cannot do, stated plainly.

    Worth surfacing rather than documenting: the guarantee is that policy can
    only narrow, and a merchant is far likelier to trust that if the product
    tells them where the ceiling is before they write anything.
    """
    from reversa.engines.policy_engine import enforcement_summary

    return enforcement_summary()


@router.post("/policies/compile")
def compile_policy_route(body: PolicyCompileRequest,
                         _: Session = Depends(requires_simulate)) -> dict:
    from reversa.ai.policy_compiler import compile_policy

    policy, meta = compile_policy(body.text, name=body.name)
    return {"policy": policy.as_dict(), **meta}


@router.post("/policies/simulate")
def simulate_policy_route(body: PolicySimulateRequest,
                          db: DbSession = Depends(get_session),
                          _: Session = Depends(requires_simulate)) -> dict:
    """Compile a policy and run the wind tunnel with it as an extra branch.

    Simulate before deploy is the entire point: a merchant should be able to see
    what their sentences cost them in recovered revenue before those sentences
    start governing real money.
    """
    from reversa.ai.policy_compiler import compile_policy

    try:
        _, build = engine_state.cohort_for(db, body.incident_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "unknown_incident"})
    if not build.candidates:
        raise HTTPException(status_code=422,
                            detail={"error": "cohort_has_no_actionable_candidates"})

    policy, meta = compile_policy(body.text, name=body.name)
    if not meta["validation"]["ok"]:
        return {"policy": policy.as_dict(), **meta, "run": None}

    run = SIM.run(build.candidates, P.DEFAULT_CAPACITY, policy=policy)
    return {"policy": policy.as_dict(), **meta, "run": run.as_dict()}


@router.get("/evaluation")
def evaluation(db: DbSession = Depends(get_session),
               _: Session = Depends(requires_read)) -> dict:
    """Reversa graded against the simulator's hidden answer key.

    Nothing on this route is self-reported. Detector recall is measured against
    the incidents the world actually injected; the natural-recovery estimate is
    scored on the holdout, where the realised outcome IS the natural outcome;
    and the headline incremental figure is compared against the exact value
    computed from potential outcomes.
    """
    from reversa.engines import evaluation_engine as EV

    st = engine_state.get(db)
    return EV.evaluate(db, detected=st.detected)


@router.get("/audit/verify")
def audit_verify(db: DbSession = Depends(get_session),
                 _: Session = Depends(requires_read)) -> dict:
    """Recompute the whole chain and report the first divergence, if any."""
    return verify_chain(db).as_dict()
