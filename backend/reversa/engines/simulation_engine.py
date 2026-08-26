"""The Revenue Wind Tunnel.

Rewind an incident, run the cohort through several possible futures, and report
what each one would actually have bought. Every figure here is computed from the
counterfactual estimates and the optimiser - nothing is authored, and the
frontend receives numbers rather than making them.

The column that matters is INCREMENTAL, and it exists because gross recovery is
the number every recovery product quotes and it is close to meaningless. On the
UPI incident in this world, roughly 56% of the exposed revenue arrives on its own
whatever anyone does. A tool that retries everything and reports the resulting
gross figure is claiming credit for money it did not move.

So each scenario reports three separate things:

    natural      what arrives if we do nothing at all
    gross        natural plus what the interventions add
    incremental  gross minus natural, i.e. what we actually caused

and alongside them the costs that any honest comparison needs: actions spent,
capacity consumed, customer friction incurred, and how many of those actions
landed on people the model thinks were going to pay anyway.

The interesting result usually is not "the most aggressive strategy wins". It
usually is not, because aggression spends scarce capacity on high-natural-recovery
customers and leaves the movable ones untouched.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from reversa.engines.portfolio_optimizer import (
    CONTACT_ACTIONS, Candidate, Plan, natural_recovery_paise, solve,
    solve_do_nothing, solve_fixed_action, solve_greedy,
)
from reversa.models import ActionType
from reversa.world import params as P

# Delay applied to the "retry later" branch, minutes. Long enough for a rail to
# come back, short enough that intent has not decayed.
DELAYED_RETRY_MINUTES = 15


@dataclass(slots=True)
class ScenarioResult:
    key: str
    label: str
    description: str

    natural_recovery_paise: int
    gross_recovery_paise: int
    incremental_recovery_paise: int

    action_count: int
    by_action: dict[str, int]
    capacity_used: dict[str, dict]
    exhausted: list[str]

    cost_paise: int
    net_incremental_paise: int
    friction: float
    wasted_actions: int
    contacted_customers: int

    confidence: float
    risk_score: float
    policy_violations: int
    violation_detail: dict

    solver: str
    solve_ms: float
    notes: list[str] = field(default_factory=list)
    assignment: dict[str, str] = field(default_factory=dict)

    @property
    def cost_per_incremental_rupee(self) -> float:
        if self.incremental_recovery_paise <= 0:
            return float("inf")
        return self.cost_paise / self.incremental_recovery_paise

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "natural_recovery_paise": self.natural_recovery_paise,
            "gross_recovery_paise": self.gross_recovery_paise,
            "incremental_recovery_paise": self.incremental_recovery_paise,
            "action_count": self.action_count,
            "by_action": self.by_action,
            "capacity_used": self.capacity_used,
            "exhausted": self.exhausted,
            "cost_paise": self.cost_paise,
            "net_incremental_paise": self.net_incremental_paise,
            "friction": round(self.friction, 2),
            "wasted_actions": self.wasted_actions,
            "contacted_customers": self.contacted_customers,
            "confidence": round(self.confidence, 4),
            "risk_score": round(self.risk_score, 4),
            "policy_violations": self.policy_violations,
            "violation_detail": self.violation_detail,
            "cost_per_incremental_rupee": (
                None if self.cost_per_incremental_rupee == float("inf")
                else round(self.cost_per_incremental_rupee, 4)
            ),
            "solver": self.solver,
            "solve_ms": round(self.solve_ms, 1),
            "notes": self.notes,
        }


@dataclass(slots=True)
class WindTunnelRun:
    scenarios: list[ScenarioResult]
    candidate_count: int
    capacity: dict[str, int]
    total_ms: float

    @property
    def baseline(self) -> ScenarioResult:
        return next(s for s in self.scenarios if s.key == "do_nothing")

    @property
    def best(self) -> ScenarioResult:
        """Best by net incremental, which is the only ranking that is defensible."""
        return max(self.scenarios, key=lambda s: s.net_incremental_paise)

    def as_dict(self) -> dict:
        return {
            "candidate_count": self.candidate_count,
            "capacity": self.capacity,
            "total_ms": round(self.total_ms, 1),
            "best_scenario": self.best.key,
            "scenarios": [s.as_dict() for s in self.scenarios],
        }


def _score(
    key: str,
    label: str,
    description: str,
    plan: Plan,
    candidates: Sequence[Candidate],
    natural: int,
) -> ScenarioResult:
    incremental = plan.expected_incremental_paise
    by_action = plan.by_action

    treated = {a.payment_id for a in plan.assignments}
    conf = [c.confidence for c in candidates if c.payment_id in treated]
    confidence = sum(conf) / len(conf) if conf else 1.0

    contacted = len({
        a.customer_id for a in plan.assignments if a.action in CONTACT_ACTIONS
    })

    # Risk is what this plan could cost us if the estimates are wrong: money
    # spent, goodwill spent, and how much of it rests on thin evidence.
    spend_risk = plan.cost_paise / max(natural, 1)
    friction_risk = plan.friction / max(len(candidates), 1)
    risk = min(1.0, 0.5 * (1 - confidence) + 0.3 * friction_risk + 0.2 * spend_risk)

    # Anything the gates would refuse. Should be zero for plans built from
    # `eligible`, but a merchant-authored policy can propose otherwise and this
    # is where that shows up.
    eligible_by_payment = {c.payment_id: set(c.eligible) for c in candidates}
    violations = [
        a for a in plan.assignments
        if a.action not in eligible_by_payment.get(a.payment_id, set())
    ]

    return ScenarioResult(
        key=key, label=label, description=description,
        natural_recovery_paise=natural,
        gross_recovery_paise=natural + incremental,
        incremental_recovery_paise=incremental,
        action_count=len(plan.assignments),
        by_action=by_action,
        capacity_used=plan.capacity_used(),
        exhausted=plan.exhausted_actions(),
        cost_paise=plan.cost_paise,
        net_incremental_paise=incremental - plan.cost_paise,
        friction=plan.friction,
        wasted_actions=plan.wasted(),
        contacted_customers=contacted,
        confidence=confidence,
        risk_score=risk,
        policy_violations=len(violations),
        violation_detail={
            "count": len(violations),
            "sample": [
                {"payment_id": v.payment_id, "action": v.action} for v in violations[:5]
            ],
        },
        solver=plan.solver,
        solve_ms=plan.solve_ms,
        notes=list(plan.notes),
        assignment={a.payment_id: a.action for a in plan.assignments},
    )


def _delayed_view(candidates: Sequence[Candidate]) -> list[Candidate]:
    """The cohort as it would look if we waited before re-presenting.

    Waiting is not free and it is not neutral. Two effects, in opposite
    directions, and the whole "retry now vs retry in 15 minutes" question is
    which one dominates:

      - a rail that was degraded has had time to come back, so a re-presentment
        that would have burned an attempt now has a chance;
      - contact-driven uplift decays with time since failure, because intent
        cools.

    Both are applied here to a copy. The originals are untouched so every branch
    of the tunnel starts from the same reality.
    """
    out: list[Candidate] = []
    hours = DELAYED_RETRY_MINUTES / 60.0
    for c in candidates:
        uplift = dict(c.uplift)
        # the penalty for re-presenting into a live outage no longer applies
        if ActionType.RETRY_NOW in uplift and ActionType.RETRY_DELAYED in uplift:
            uplift[ActionType.RETRY_NOW] = max(
                uplift[ActionType.RETRY_NOW], uplift[ActionType.RETRY_DELAYED]
            )
        for action, tau in P.CONTACT_DECAY_TAU_HOURS.items():
            if action in uplift:
                uplift[action] *= pow(2.718281828, -hours / tau)
        out.append(Candidate(
            payment_id=c.payment_id, customer_id=c.customer_id,
            amount_paise=c.amount_paise, failure_class=c.failure_class,
            p_natural=c.p_natural, confidence=c.confidence, uplift=uplift,
            uplift_credible=dict(c.uplift_credible), eligible=c.eligible,
            method=c.method,
        ))
    return out


def run(
    candidates: Sequence[Candidate],
    capacity: dict[str, int] | None = None,
    *,
    extra: dict[str, Callable[[Sequence[Candidate], dict], Plan]] | None = None,
) -> WindTunnelRun:
    """Evaluate every branch over one cohort."""
    started = time.perf_counter()
    capacity = dict(capacity or P.DEFAULT_CAPACITY)
    natural = natural_recovery_paise(candidates)
    delayed = _delayed_view(candidates)

    results: list[ScenarioResult] = [
        _score(
            "do_nothing", "DO NOTHING",
            "No intervention. The counterfactual every other column is measured "
            "against.",
            solve_do_nothing(candidates), candidates, natural,
        ),
        _score(
            "retry_now", "RETRY NOW",
            "Re-present every eligible payment immediately, largest expected "
            "value first.",
            solve_fixed_action(candidates, ActionType.RETRY_NOW, capacity),
            candidates, natural,
        ),
        _score(
            "retry_delayed", f"RETRY +{DELAYED_RETRY_MINUTES}M",
            f"Wait {DELAYED_RETRY_MINUTES} minutes for the rail to stabilise, "
            "then re-present.",
            solve_fixed_action(delayed, ActionType.RETRY_DELAYED, capacity),
            delayed, natural,
        ),
        _score(
            "payment_link", "LINK EVERYONE",
            "Send a fresh payment link to every eligible customer until link "
            "capacity runs out.",
            solve_fixed_action(candidates, ActionType.PAYMENT_LINK, capacity),
            candidates, natural,
        ),
        _score(
            "greedy", "GREEDY",
            "Take the highest-value move available, repeatedly, until capacity "
            "is gone. Included to show what the exact solve is worth.",
            solve_greedy(candidates, capacity), candidates, natural,
        ),
        _score(
            "optimal", "OPTIMAL",
            "Maximise expected incremental revenue net of cost, subject to "
            "capacity and every compliance gate.",
            solve(candidates, capacity), candidates, natural,
        ),
    ]

    for key, builder in (extra or {}).items():
        plan = builder(candidates, capacity)
        results.append(_score(key, key.upper(), "Merchant-defined policy.",
                              plan, candidates, natural))

    return WindTunnelRun(
        scenarios=results,
        candidate_count=len(candidates),
        capacity=capacity,
        total_ms=(time.perf_counter() - started) * 1000,
    )


def time_to_capacity_exhaustion(
    plan: Plan, arrivals_per_minute: float
) -> dict[str, float | None]:
    """When each capacity pool runs dry at a given arrival rate.

    Chaos mode's headline. "Current policy exhausts payment-link capacity in
    7m 12s" is the sentence that makes capacity feel real to an operator, and it
    is arithmetic, not theatre.
    """
    if arrivals_per_minute <= 0 or not plan.assignments:
        return {a: None for a in plan.capacity}

    share = {
        action: count / len(plan.assignments)
        for action, count in plan.by_action.items()
    }
    out: dict[str, float | None] = {}
    for action, limit in plan.capacity.items():
        rate = arrivals_per_minute * share.get(action, 0.0)
        out[action] = round(limit / rate, 2) if rate > 0 else None
    return out
