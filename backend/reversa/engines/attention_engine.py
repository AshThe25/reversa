"""What deserves the next ten minutes.

A dashboard that reports state is not the same as a dashboard that is useful.
Five tiles and a list of degraded slices tell an operator what is true; they do
not tell them what to do about it, and the gap between those two things is where
the money sits. Somebody opens this at 2pm, sees eleven open incidents and a
capacity bar at 80%, and has to work out on their own which of those is worth
interrupting their afternoon for. Usually they pick the biggest number, which is
the wrong answer often enough to matter.

So this ranks. Every item here is a claim that something is costing money right
now and that a specific person can do a specific thing about it. Ranking is by
money at stake, because that is the only ordering that survives an argument.

Two rules about what goes in.

  It must be actionable. "UPI is degraded" is an observation. "UPI is degraded,
  nothing is running against it, and here is the plan" is an item. If there is
  no next step, it belongs on a chart, not here.

  It must be quiet when things are fine. A list that always has nine rows gets
  read once and then ignored forever, and an alert nobody reads is worse than no
  alert because it costs the attention it fails to earn. Every rule below has a
  threshold that a healthy system does not cross.

Nothing here calls a model. These are cheap deterministic queries over state we
already hold, which means this can run on every dashboard load without a budget
conversation, and means the ranking is reproducible - the same state produces
the same list, and two people looking at it see the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reversa.engines.policy_gates import PAYER_CONTACTING
from reversa.models import (
    DowntimeRecord, Experiment, Incident, IncidentStatus, RecoveryAction,
)
from reversa.world import params as P

# A capacity bar reads as fine until it is suddenly not. Past this share of the
# budget the question stops being "are we spending" and becomes "will there be
# anything left when something actually breaks", which is worth raising before
# the answer is no.
CAPACITY_PRESSURE = 0.80

# Below this there is nothing to say. An incident exposing four hundred rupees
# is real and should still appear on the incidents page, but it does not deserve
# to interrupt anyone, and putting it here would train people to skim.
MATERIAL_PAISE = 50_000_00

# Unproven spend is worth raising on principle, but not at any size. A campaign
# that has cost forty rupees and not yet proved itself is a rounding error, and
# putting it in front of someone teaches them the list is padded.
UNPROVEN_FLOOR_PAISE = 1_000_00


def _name(inc: Incident) -> str:
    """A slice as somebody would say it out loud.

    The stored key is `upi/*` or `*/*`, which is right for a database and wrong
    for a sentence a person reads while deciding what to do next.
    """
    if inc.slice_method and inc.slice_instrument:
        return f"{inc.slice_method.upper()} / {inc.slice_instrument}"
    if inc.slice_method:
        return inc.slice_method.upper()
    # Lower case because every headline places this mid-sentence. The
    # method names are acronyms and stay upper.
    return "several unrelated slices"


class Urgency(StrEnum):
    """How much of someone's day this is worth.

    Deliberately three levels. Five would imply a precision the underlying
    thresholds do not have, and everything ends up amber anyway.
    """

    ACT = "act"          # money is moving and nothing is stopping it
    REVIEW = "review"    # a person is the blocker
    WATCH = "watch"      # worth knowing, not worth interrupting


@dataclass(frozen=True, slots=True)
class Item:
    """One thing worth doing, and enough context to decide without leaving."""

    kind: str
    urgency: Urgency
    headline: str
    detail: str
    money_paise: int
    action_label: str
    action_path: str
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "urgency": str(self.urgency),
            "headline": self.headline,
            "detail": self.detail,
            "money_paise": self.money_paise,
            "action_label": self.action_label,
            "action_path": self.action_path,
            "evidence": self.evidence,
        }


# --- the rules --------------------------------------------------------------
#
# Each returns zero or more items. They are separate functions because each one
# is a separate claim about the world and should be arguable - and testable -
# on its own.


def _unattended(db: Session, open_incidents: list[Incident]) -> list[Item]:
    """Open, material, and nothing running against it.

    The worst state the system can be in, because it is the one where the
    machinery has done its job - found the break, priced it - and then stopped.
    Every minute here is money leaving for a reason nobody has decided about.
    """
    if not open_incidents:
        return []

    attended = {
        row[0] for row in db.execute(
            select(Experiment.cohort_id).where(Experiment.cohort_id.is_not(None))
        ).all()
    }

    items = []
    for inc in open_incidents:
        if inc.revenue_exposed_paise < MATERIAL_PAISE:
            continue
        # Cohort ids are derived from the incident, so an experiment on this
        # incident's cohort is the signal that somebody has already acted.
        if any(inc.id in str(c) for c in attended):
            continue
        # Where the button goes depends on whether the plan can actually be
        # built. An attributable break goes straight to the optimiser and runs
        # it - one click, no intermediate page whose only content is another
        # button. A diffuse one cannot be planned against and the optimiser
        # refuses it by design, so sending someone there would hand them a
        # disabled control and no explanation; they go and read the
        # investigation instead.
        planable = not inc.rca_is_ambiguous
        items.append(Item(
            kind="unattended_incident",
            urgency=Urgency.ACT,
            headline=f"Nothing is running against {_name(inc)}",
            detail=(
                f"Success fell from {inc.baseline_success_rate:.0%} to "
                f"{inc.observed_success_rate:.0%} across "
                f"{inc.affected_payment_count:,} payments. No recovery plan has "
                "been built for it yet."
            ),
            money_paise=inc.revenue_exposed_paise,
            action_label="Build the plan" if planable else "Read the investigation first",
            action_path=(
                f"/futures?incident={inc.id}&auto=1" if planable
                else f"/incidents/{inc.id}"
            ),
            evidence={"incident_id": inc.id, "q_value": inc.q_value},
        ))
    return items


def _unresolved_cause(open_incidents: list[Incident]) -> list[Item]:
    """A plan here would rest on a guess, so a person should see the guess.

    Separate from the review queue on purpose. The queue asks "do you approve
    this action"; this asks the earlier question, which is whether we understand
    the break well enough for the question to mean anything.
    """
    items = []
    for inc in open_incidents:
        if not inc.rca_is_ambiguous or inc.revenue_exposed_paise < MATERIAL_PAISE:
            continue
        items.append(Item(
            kind="unresolved_cause",
            urgency=Urgency.REVIEW,
            headline=f"We cannot say why {_name(inc)} broke",
            detail=(
                "The investigation could not attribute a cause with enough "
                "confidence to act on. Any plan built on this is arithmetic on "
                "top of a guess, so it is worth a look before it runs."
            ),
            money_paise=inc.revenue_exposed_paise,
            action_label="Read the investigation",
            action_path=f"/incidents/{inc.id}",
            evidence={
                "incident_id": inc.id,
                "rca_class": inc.rca_class,
                "rca_confidence": inc.rca_confidence,
            },
        ))
    return items


def _awaiting_review(db: Session) -> list[Item]:
    """Decisions blocked on a human, with the money that is waiting on them.

    Only payer-contacting actions, which is the same rule the review engine
    uses: a gateway retry needs nobody, and counting it here would inflate the
    number until it stopped meaning anything.
    """
    rows = db.execute(
        select(
            func.count(RecoveryAction.id),
            func.coalesce(func.sum(RecoveryAction.expected_incremental_paise), 0),
        ).where(
            RecoveryAction.action_type.in_(tuple(PAYER_CONTACTING)),
            RecoveryAction.executed_at.is_(None),
        )
    ).one()
    pending, value = int(rows[0]), int(rows[1])
    if pending == 0:
        return []

    return [Item(
        kind="awaiting_review",
        urgency=Urgency.REVIEW,
        headline=f"{pending} decision{'s' if pending != 1 else ''} waiting on a human",
        detail=(
            "These reach the customer directly and cannot be recalled once "
            "sent, so they do not auto-approve. Nothing happens until somebody "
            "says yes."
        ),
        money_paise=value,
        action_label="Open the review queue",
        action_path="/incidents",
        evidence={"pending": pending},
    )]


def _capacity_pressure(db: Session) -> list[Item]:
    """Budget nearly spent.

    The failure this prevents is specific and common: a merchant burns their
    contact budget on a quiet Tuesday recovering payments that were going to
    land anyway, and then a real outage arrives on Friday with nothing left to
    spend on it. The budget is not the constraint people think it is - the
    constraint is having it when it matters.
    """
    used = dict(db.execute(
        select(RecoveryAction.action_type, func.count()).group_by(RecoveryAction.action_type)
    ).all())
    total = sum(P.DEFAULT_CAPACITY.values())
    spent = sum(used.get(a, 0) for a in P.DEFAULT_CAPACITY)
    if total == 0 or spent / total < CAPACITY_PRESSURE:
        return []

    return [Item(
        kind="capacity_pressure",
        urgency=Urgency.WATCH,
        headline=f"{spent / total:.0%} of the treatment budget is gone",
        detail=(
            f"{spent:,} of {total:,} actions used. When this runs out the "
            "system stops treating, including for an incident that has not "
            "happened yet. Worth deciding now whether the remainder is "
            "reserved or spent."
        ),
        money_paise=0,
        action_label="Review the policy",
        action_path="/policies",
        evidence={"used": spent, "total": total},
    )]


def _unproven_spend(db: Session) -> list[Item]:
    """Paying for something that has not been shown to work.

    A concluded experiment whose revenue interval still crosses zero has not
    demonstrated an effect. That is not the same as demonstrating there is no
    effect - usually it means the arms were too small - but either way money is
    going out against a result that cannot carry it, and continuing is a choice
    somebody should make on purpose.
    """
    concluded = db.execute(
        select(Experiment).where(Experiment.status == "concluded")
    ).scalars().all()

    items = []
    for exp in concluded:
        r = exp.results or {}
        cost = int(r.get("cost_paise", 0))
        if cost < UNPROVEN_FLOOR_PAISE or r.get("significant"):
            continue
        lo = int(r.get("incremental_lo_paise", 0))
        hi = int(r.get("incremental_hi_paise", 0))
        items.append(Item(
            kind="unproven_spend",
            urgency=Urgency.REVIEW,
            headline=f"{exp.name} cost money without proving it worked",
            detail=(
                f"The incremental interval runs from {lo / 100:,.0f} to "
                f"{hi / 100:,.0f} rupees, which includes zero. Most likely the "
                "arms were too small to resolve the effect rather than the "
                "treatment being useless - but on this evidence it cannot be "
                "told apart, and it is still being paid for."
            ),
            money_paise=cost,
            action_label="See the interval",
            action_path=f"/experiments/{exp.id}",
            evidence={"experiment_id": exp.id, "lo": lo, "hi": hi},
        ))
    return items


def _blind_window(db: Session, open_incidents: list[Incident]) -> list[Item]:
    """Broken here, silent on the status feed.

    Razorpay publishes downtime, and merchants reasonably treat that feed as the
    answer to "is it them or is it me". It is a good feed and it is not
    instant - a window has to be confirmed before it is worth publishing, and
    confirmation takes evidence that accumulates over minutes. That lag is
    exactly the interval in which a merchant is losing money while the official
    answer is that nothing is wrong, and it is the interval where an operator
    most often blames their own release and starts rolling back the wrong thing.

    Saying so is the honest version of a comparison we already run. It is not a
    claim that the feed is late in general, only that for this slice, right now,
    we are seeing something it is not showing.
    """
    if not open_incidents:
        return []

    published = db.execute(select(DowntimeRecord)).scalars().all()

    items = []
    for inc in open_incidents:
        if inc.revenue_exposed_paise < MATERIAL_PAISE:
            continue
        covered = any(
            d.method == inc.slice_method
            and d.begin <= inc.window_end + timedelta(minutes=5)
            and (d.end is None or d.end >= inc.window_start)
            for d in published
        )
        if covered:
            continue
        items.append(Item(
            kind="blind_window",
            urgency=Urgency.WATCH,
            headline=f"The status feed has not confirmed {_name(inc)}",
            detail=(
                "We are seeing a statistically significant drop that the "
                "published downtime feed has not confirmed yet. That gap is "
                "usually confirmation lag rather than disagreement - but while "
                "it lasts, the official answer to 'is it them or is it us' is "
                "wrong, and it is not us."
            ),
            money_paise=inc.revenue_exposed_paise,
            action_label="See the evidence",
            action_path=f"/incidents/{inc.id}",
            evidence={"incident_id": inc.id, "method": inc.slice_method},
        ))
    return items


# --- assembly ---------------------------------------------------------------

_URGENCY_ORDER = {Urgency.ACT: 0, Urgency.REVIEW: 1, Urgency.WATCH: 2}


def _collapse(items: list[Item]) -> list[Item]:
    """One row per incident, however many rules fired on it.

    Three rules can be true about the same broken slice at once: nothing is
    running against it, we cannot say why it broke, and the status feed has not
    confirmed it. All three are worth knowing and none of them is a separate
    piece of work - it is one incident, and it takes one person one visit.

    Listing them separately is how a triage list turns back into the wall of
    numbers it was supposed to replace. So the most urgent framing wins the row
    and the others survive as short notes on it, which keeps the second and
    third facts without spending a second and third line on them.
    """
    by_incident: dict[str, Item] = {}
    standalone: list[Item] = []

    for item in items:
        inc_id = item.evidence.get("incident_id")
        if not inc_id:
            standalone.append(item)
            continue
        held = by_incident.get(inc_id)
        if held is None:
            by_incident[inc_id] = item
            continue
        # Keep the more urgent framing; fold the other into it as a note.
        winner, loser = (
            (held, item)
            if _URGENCY_ORDER[held.urgency] <= _URGENCY_ORDER[item.urgency]
            else (item, held)
        )
        notes = [*winner.evidence.get("also", []), loser.headline]
        by_incident[inc_id] = Item(
            kind=winner.kind,
            urgency=winner.urgency,
            headline=winner.headline,
            detail=winner.detail,
            money_paise=max(winner.money_paise, loser.money_paise),
            action_label=winner.action_label,
            action_path=winner.action_path,
            evidence={**winner.evidence, "also": notes},
        )

    return [*by_incident.values(), *standalone]


def assess(db: Session, *, limit: int = 5) -> list[Item]:
    """The ranked list.

    Urgency first, then money. Sorting by money alone would let a large but
    already-handled incident outrank a smaller one that nothing is running
    against, and the second is the one that needs a person.

    Capped, because a triage list that scrolls is a list nobody finishes. The
    tail is not hidden - it is on the pages these items link to, which is where
    it belongs.
    """
    open_incidents = list(db.execute(
        select(Incident).where(Incident.status == IncidentStatus.OPEN)
    ).scalars().all())

    items = _collapse([
        *_unattended(db, open_incidents),
        *_unresolved_cause(open_incidents),
        *_awaiting_review(db),
        *_capacity_pressure(db),
        *_unproven_spend(db),
        *_blind_window(db, open_incidents),
    ])
    items.sort(key=lambda i: (_URGENCY_ORDER[i.urgency], -i.money_paise))
    return items[:limit]


def summarise(items: list[Item]) -> dict:
    """Headline counts, and the one sentence to show when the list is empty."""
    return {
        "items": [i.as_dict() for i in items],
        "total": len(items),
        "act": sum(1 for i in items if i.urgency == Urgency.ACT),
        "money_at_stake_paise": sum(
            i.money_paise for i in items if i.urgency == Urgency.ACT
        ),
        "all_clear": not items,
    }
