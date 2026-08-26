"""Compliance gates.

Nothing executes until it clears every gate here. The optimizer proposes, gates
dispose, and a blocked action gets recorded with the rule that blocked it rather
than silently dropped.

On which rules actually apply - this matters and it's easy to get wrong.

RBI's recovery-conduct rules (08:00-19:00 contact window, mandatory agent
identification, no masked numbers, pause while a grievance is pending) govern
*lenders* recovering *loans*. A D2C merchant chasing a failed card payment for a
kurta is not a regulated entity and those rules do not bind it. Claiming
otherwise would be wrong, and someone at Razorpay would catch it in about four
seconds.

They DO bind directly when the recovery is credit-linked - EMI, BNPL, pay-later,
lender-backed subscriptions - which is a large and growing slice of Razorpay
volume. So Reversa treats the RBI window as: statutory where credit is involved,
and a self-imposed standard everywhere else, because it is the strictest
defensible norm in Indian financial communication and a merchant that respects it
is never the one in the news.

What binds every merchant, always:

- TRAI TCCCPR / DLT. Commercial messages to Indian numbers need per-channel
  consent and a pre-registered template. An unregistered template is a
  regulatory problem, not a deliverability one.
- DPDP Act 2023. Contacting someone using their personal data needs consent for
  that purpose, and withdrawal has to be honoured.

Every verdict carries a `basis` saying which of the three it is - statutory,
adopted standard, or our own product invariant. Merging those into undifferentiated
"compliance" is how teams end up unable to answer which rules they could relax
under pressure and which they cannot.

Two design notes worth flagging.

A gate distinguishes a permanent block ("card's expired, no retry will ever
work") from a temporal one ("it's 22:40, come back at 08:00"). Collapsing those
into one boolean is how compliant systems quietly lose money - everything that's
merely early gets thrown away.

And gates run against a preloaded ComplianceIndex, not live queries. The Wind
Tunnel evaluates gates over every candidate x every action to count policy
violations per scenario; at 40k candidates that's ~350k evaluations and a
per-row SELECT would make the whole feature unusable.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Callable, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from reversa.config import IST, Settings, get_settings
from reversa.models import (
    ActionResult,
    ActionType,
    ComplianceEvent,
    Customer,
    RecoveryAction,
)
from reversa.taxonomy import NEVER_AUTO_ACTION, RecoveryClass, classify

# actions that reach an actual human. only these get contact windows, consent
# and frequency caps - a silent gateway retry touches nobody.
PAYER_CONTACTING: frozenset[str] = frozenset({
    ActionType.NUDGE_SMS,
    ActionType.NUDGE_WHATSAPP,
    ActionType.NUDGE_EMAIL,
    ActionType.PAYMENT_LINK,
    ActionType.VOICE_CALL,
})

# email is pull-based and async; RBI's contact-hours rule targets intrusive
# channels. still subject to consent and frequency below.
TIME_RESTRICTED: frozenset[str] = frozenset({
    ActionType.NUDGE_SMS,
    ActionType.NUDGE_WHATSAPP,
    ActionType.PAYMENT_LINK,
    ActionType.VOICE_CALL,
})

# DLT template ids. in prod these come from the operator's DLT portal. pinned
# here so an unregistered body can't go out even by accident.
REGISTERED_TEMPLATES: dict[str, str] = {
    ActionType.NUDGE_SMS: "DLT-RZPRVS-1101-RETRY-EN",
    ActionType.NUDGE_WHATSAPP: "DLT-RZPRVS-1104-RETRY-HI",
    ActionType.PAYMENT_LINK: "DLT-RZPRVS-1107-LINK-EN",
}

FREEZING_EVENTS = ("complaint_raised", "dispute_opened")

FREE_ACTIONS = frozenset({ActionType.NO_ACTION, ActionType.WAIT})


class Basis(StrEnum):
    """Where a rule's authority comes from. See the module docstring."""

    STATUTORY = "statutory"
    """Binding law for this merchant. Cannot be relaxed by anyone."""

    ADOPTED = "adopted_standard"
    """A stricter norm we hold ourselves to. Statutory when credit-linked."""

    INVARIANT = "product_invariant"
    """Reversa's own safety rule. Not law, but not merchant-tunable either."""

    CONFIGURED = "merchant_policy"
    """A limit the merchant set. The only kind a merchant may loosen."""


@dataclass(frozen=True, slots=True)
class Verdict:
    gate: str
    allowed: bool
    rule: str
    detail: str = ""
    # keep `basis` after `detail`: the gates below pass detail positionally, and
    # slotting a new field in ahead of it silently rewrote every one of them.
    basis: str = Basis.INVARIANT
    retry_after: datetime | None = None

    @property
    def permanent(self) -> bool:
        return not self.allowed and self.retry_after is None

    def as_dict(self) -> dict:
        return {
            "gate": self.gate,
            "allowed": self.allowed,
            "rule": self.rule,
            "basis": self.basis,
            "detail": self.detail,
            "retry_after": self.retry_after.isoformat() if self.retry_after else None,
        }


@dataclass(slots=True)
class GateReport:
    action_type: str
    verdicts: list[Verdict] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return all(v.allowed for v in self.verdicts)

    @property
    def blocking(self) -> list[Verdict]:
        return [v for v in self.verdicts if not v.allowed]

    @property
    def permanently_blocked(self) -> bool:
        return any(v.permanent for v in self.blocking)

    @property
    def earliest_retry(self) -> datetime | None:
        """when every temporal blocker would have cleared."""
        if self.permanently_blocked:
            return None
        times = [v.retry_after for v in self.blocking if v.retry_after]
        return max(times) if times else None

    @property
    def reason(self) -> str | None:
        if self.allowed:
            return None
        v = self.blocking[0]
        return f"{v.gate}: {v.detail or v.rule}"[:120]

    def as_dict(self, *, verbose: bool = True) -> dict:
        out = {
            "action_type": self.action_type,
            "allowed": self.allowed,
            "reason": self.reason,
            "permanently_blocked": self.permanently_blocked,
            "earliest_retry": (
                self.earliest_retry.isoformat() if self.earliest_retry else None
            ),
        }
        if verbose:
            out["verdicts"] = [v.as_dict() for v in self.verdicts]
        return out


@dataclass(slots=True)
class GateSubject:
    """What the gates need to know about one recovery candidate.

    Deliberately not an ORM row - the Wind Tunnel builds these for hypothetical
    plans that were never persisted.
    """

    payment_id: str
    customer: Customer
    amount_paise: int
    failure_reason: str | None
    failure_class: str
    method: str
    instrument: str
    failed_at: datetime
    deadline_at: datetime
    contacts_used: int = 0
    retries_used: int = 0
    is_frozen: bool = False
    is_closed: bool = False
    credit_linked: bool = False
    """EMI / BNPL / lender-backed subscription. Flips the RBI recovery-conduct
    rules from a standard we adopt into law that binds us."""


class ComplianceIndex:
    """Per-customer compliance state, loaded once for a whole batch."""

    def __init__(
        self,
        frozen: set[str] | None = None,
        contacts: dict[str, list[datetime]] | None = None,
    ) -> None:
        self.frozen = frozen or set()
        self.contacts = contacts or {}

    @classmethod
    def load(cls, session: Session, customer_ids: Sequence[str]) -> "ComplianceIndex":
        ids = list({c for c in customer_ids})
        if not ids:
            return cls()

        frozen = set(
            session.execute(
                select(ComplianceEvent.customer_id).where(
                    ComplianceEvent.customer_id.in_(ids),
                    ComplianceEvent.active.is_(True),
                    ComplianceEvent.event_type.in_(FREEZING_EVENTS),
                )
            ).scalars()
        )

        contacts: dict[str, list[datetime]] = defaultdict(list)
        rows = session.execute(
            select(RecoveryAction.customer_id, RecoveryAction.executed_at).where(
                RecoveryAction.customer_id.in_(ids),
                RecoveryAction.action_type.in_(tuple(PAYER_CONTACTING)),
                RecoveryAction.executed_at.is_not(None),
                RecoveryAction.result.in_(
                    (ActionResult.EXECUTED, ActionResult.SUCCEEDED)
                ),
            )
        ).all()
        for cid, when in rows:
            if when is not None:
                contacts[cid].append(_aware(when))

        return cls(frozen=frozen, contacts=dict(contacts))

    def is_frozen(self, customer_id: str) -> bool:
        return customer_id in self.frozen

    def contact_times(self, customer_id: str) -> list[datetime]:
        return self.contacts.get(customer_id, [])

    def note_contact(self, customer_id: str, when: datetime) -> None:
        """Record a contact made during this batch.

        Without this, planning 500 actions in one pass would let the same
        customer be picked repeatedly - every one of them would see an empty
        contact history and pass the frequency gate.
        """
        self.contacts.setdefault(customer_id, []).append(_aware(when))


@dataclass(slots=True)
class GateContext:
    subject: GateSubject
    now: datetime
    settings: Settings
    index: ComplianceIndex
    instrument_down: bool = False
    template_id: str | None = None


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------


def _g_case_open(action: str, c: GateContext) -> Verdict:
    rule = "Reversa invariant: a closed or frozen case takes no further money actions"
    if c.subject.is_frozen or c.index.is_frozen(c.subject.customer.id):
        return Verdict("case_state", False, rule,
                       "frozen: complaint or dispute open for this customer")
    if c.subject.is_closed:
        return Verdict("case_state", False, rule, "case already closed")
    return Verdict("case_state", True, rule)


def _g_actionable(action: str, c: GateContext) -> Verdict:
    rule = "Reversa invariant: risk-blocked and unrecognised failures are never automated"
    try:
        rc = RecoveryClass(c.subject.failure_class)
    except ValueError:
        rc = RecoveryClass.UNKNOWN
    if rc in NEVER_AUTO_ACTION and action not in (ActionType.HUMAN_REVIEW,) and action not in FREE_ACTIONS:
        return Verdict("actionable_class", False, rule,
                       f"recovery class '{rc}' requires human review")
    return Verdict("actionable_class", True, rule)


def _g_deadline(action: str, c: GateContext) -> Verdict:
    rule = f"Reversa policy: cases expire {c.settings.case_ttl_days} days after failure"
    if action in FREE_ACTIONS:
        return Verdict("deadline", True, rule)
    if c.now >= _aware(c.subject.deadline_at):
        return Verdict("deadline", False, rule, "past the recovery deadline")
    return Verdict("deadline", True, rule)


def _g_complaint_freeze(action: str, c: GateContext) -> Verdict:
    rule = ("RBI recovery conduct: recovery activity pauses while a complaint "
            "from the borrower is pending")
    if action not in PAYER_CONTACTING:
        return Verdict("complaint_freeze", True, rule, "not a payer-contacting action")
    if c.index.is_frozen(c.subject.customer.id):
        return Verdict("complaint_freeze", False, rule,
                       "unresolved complaint or dispute open for this customer")
    return Verdict("complaint_freeze", True, rule)


def _g_opt_out(action: str, c: GateContext) -> Verdict:
    rule = "TRAI DLT / consumer preference: an opt-out is absolute and permanent"
    if action not in PAYER_CONTACTING:
        return Verdict("opt_out", True, rule, "not a payer-contacting action")
    if c.subject.customer.opted_out_at is not None:
        return Verdict("opt_out", False, rule, "customer has opted out of all contact")
    return Verdict("opt_out", True, rule)


def _g_consent(action: str, c: GateContext) -> Verdict:
    rule = "TRAI DLT: prior explicit consent required per channel"
    if action not in PAYER_CONTACTING:
        return Verdict("channel_consent", True, rule, "not a payer-contacting action")
    if not c.subject.customer.channel_consent(action):
        return Verdict("channel_consent", False, rule,
                       f"no consent on record for {action}")
    return Verdict("channel_consent", True, rule)


def _next_window_open(now: datetime, s: Settings) -> datetime:
    local = now.astimezone(IST)
    open_today = datetime.combine(
        local.date(), time(s.contact_window_start_hour), tzinfo=IST
    )
    if local < open_today:
        return open_today.astimezone(timezone.utc)
    return (open_today + timedelta(days=1)).astimezone(timezone.utc)


def _g_contact_window(action: str, c: GateContext) -> Verdict:
    s = c.settings
    rule = (f"RBI recovery conduct: no payer contact outside "
            f"{s.contact_window_start_hour:02d}:00-{s.contact_window_end_hour:02d}:00 IST")
    if action not in TIME_RESTRICTED:
        return Verdict("contact_window", True, rule, "channel is not time-restricted")

    hour = c.now.astimezone(IST).hour
    if s.contact_window_start_hour <= hour < s.contact_window_end_hour:
        return Verdict("contact_window", True, rule)
    return Verdict(
        "contact_window", False, rule,
        f"local time {c.now.astimezone(IST):%H:%M} IST is outside the window",
        retry_after=_next_window_open(c.now, s),
    )


def _g_contact_frequency(action: str, c: GateContext) -> Verdict:
    s = c.settings
    rule = (f"Reversa policy: max {s.max_contacts_per_case}/case, "
            f"{s.max_contacts_per_payer_per_day}/customer/day, "
            f"{s.min_hours_between_contacts}h apart")
    if action not in PAYER_CONTACTING:
        return Verdict("contact_frequency", True, rule, "not a payer-contacting action")

    if c.subject.contacts_used >= s.max_contacts_per_case:
        return Verdict("contact_frequency", False, rule,
                       f"case used all {s.max_contacts_per_case} contacts")

    sent = c.index.contact_times(c.subject.customer.id)
    if sent:
        last = max(sent)
        gap = timedelta(hours=s.min_hours_between_contacts)
        if c.now - last < gap:
            return Verdict(
                "contact_frequency", False, rule,
                f"last contact {round((c.now - last).total_seconds() / 3600, 1)}h ago",
                retry_after=last + gap,
            )
        day_start = (
            c.now.astimezone(IST)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(timezone.utc)
        )
        today = [t for t in sent if t >= day_start]
        if len(today) >= s.max_contacts_per_payer_per_day:
            return Verdict(
                "contact_frequency", False, rule,
                f"already contacted {len(today)}x today",
                retry_after=_next_window_open(c.now, s),
            )
    return Verdict("contact_frequency", True, rule)


def _g_retry_budget(action: str, c: GateContext) -> Verdict:
    rule = f"Reversa policy: max {c.settings.max_retries_per_case} re-presentments per case"
    if action not in (ActionType.RETRY_NOW, ActionType.RETRY_DELAYED, ActionType.SWITCH_METHOD):
        return Verdict("retry_budget", True, rule, "not a retry")
    if c.subject.retries_used >= c.settings.max_retries_per_case:
        return Verdict("retry_budget", False, rule, "retry budget exhausted")
    return Verdict("retry_budget", True, rule)


def _g_instrument_viable(action: str, c: GateContext) -> Verdict:
    rule = "Reversa invariant: never re-present an instrument that cannot succeed"
    if action not in (ActionType.RETRY_NOW, ActionType.RETRY_DELAYED):
        return Verdict("instrument_viability", True, rule, "not a same-instrument retry")
    mode = classify(c.subject.failure_reason)
    if not mode.same_instrument_viable:
        return Verdict("instrument_viability", False, rule,
                       f"'{mode.reason}' is terminal for this instrument; "
                       "only a method switch can work")
    return Verdict("instrument_viability", True, rule)


def _g_downtime_suppression(action: str, c: GateContext) -> Verdict:
    rule = ("Reversa invariant: do not re-present into a rail Razorpay reports "
            "degraded, and do not blame the customer for it")
    if not c.instrument_down:
        return Verdict("downtime_suppression", True, rule)
    if action in ({ActionType.RETRY_NOW} | PAYER_CONTACTING):
        return Verdict(
            "downtime_suppression", False, rule,
            "target rail is inside an active downtime window",
            retry_after=c.now + timedelta(minutes=20),
        )
    return Verdict("downtime_suppression", True, rule)


def _g_template_registered(action: str, c: GateContext) -> Verdict:
    rule = "TRAI DLT: commercial messages must use a pre-registered template"
    if action not in REGISTERED_TEMPLATES:
        return Verdict("dlt_template", True, rule, "channel needs no template")
    if c.template_id is None:
        return Verdict("dlt_template", True, rule, "template resolved at render time")
    if c.template_id != REGISTERED_TEMPLATES[action]:
        return Verdict("dlt_template", False, rule,
                       f"template '{c.template_id}' is not registered for {action}")
    return Verdict("dlt_template", True, rule)


# (gate, basis). Kept next to the function rather than inside it so the whole
# regulatory posture of the system is readable in one screen.
GATES: tuple[tuple[Callable[[str, GateContext], Verdict], str], ...] = (
    (_g_case_open,             Basis.INVARIANT),
    (_g_actionable,            Basis.INVARIANT),
    (_g_deadline,              Basis.CONFIGURED),
    (_g_complaint_freeze,      Basis.ADOPTED),    # statutory if credit-linked
    (_g_opt_out,               Basis.STATUTORY),  # DPDP s.6(6) withdrawal, TCCCPR
    (_g_consent,               Basis.STATUTORY),  # TCCCPR / DLT, DPDP purpose limit
    (_g_contact_window,        Basis.ADOPTED),    # statutory if credit-linked
    (_g_contact_frequency,     Basis.CONFIGURED),
    (_g_retry_budget,          Basis.CONFIGURED),
    (_g_instrument_viable,     Basis.INVARIANT),
    (_g_downtime_suppression,  Basis.INVARIANT),
    (_g_template_registered,   Basis.STATUTORY),  # TCCCPR registered template
)

# A merchant policy may tighten any of these. It may never loosen the ones that
# are not CONFIGURED - see engines/policy_engine.py, which enforces it.
MERCHANT_TUNABLE = frozenset({Basis.CONFIGURED})


def evaluate(action_type: str, ctx: GateContext) -> GateReport:
    """Run every gate.

    All of them run even after the first denial - the audit record should show
    the full compliance posture of a decision, not whichever rule happened to be
    checked first.
    """
    verdicts = []
    for gate, basis in GATES:
        v = gate(action_type, ctx)
        if basis == Basis.ADOPTED and ctx.subject.credit_linked:
            # not a standard we chose any more, it's the law for this payment
            basis = Basis.STATUTORY
        verdicts.append(replace(v, basis=basis))
    return GateReport(action_type, verdicts)


def allowed_actions(candidates: Iterable[str], ctx: GateContext) -> dict[str, GateReport]:
    return {a: evaluate(a, ctx) for a in candidates}


def eligible(candidates: Iterable[str], ctx: GateContext) -> list[str]:
    return [a for a in candidates if evaluate(a, ctx).allowed]


def _aware(v: datetime) -> datetime:
    """sqlite drops tzinfo. stored timestamps are UTC by construction."""
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v
