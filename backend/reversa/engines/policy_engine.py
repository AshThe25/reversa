"""Merchant policy: compiled, validated, and structurally unable to loosen anything.

A merchant writes what they want in English. It becomes a list of structured
rules that deterministic code evaluates. The natural language is never executed
and never reaches an eval - it is parsed into a fixed schema over an allowlisted
vocabulary of fields, operators and effects, and anything that does not fit is
rejected with a reason.

**The safety property is that policy can only restrict.**

There is deliberately no effect that permits something. The available effects are
BLOCK, REQUIRE_HUMAN_REVIEW, WAIT and PREFER - every one of them either removes an
option or reorders options that were already legal. So no sentence a merchant can
write, and no output an LLM can produce from it, can widen what the system is
allowed to do. "Contact everyone immediately regardless of consent" compiles to
nothing, because there is no rule shape that could express it.

That matters more than it sounds. The compiler's input is untrusted text and its
author is an LLM; both are things you plan to be wrong about. Making the *output
language* incapable of expressing a dangerous instruction is a stronger guarantee
than validating the instructions after the fact.

Compilation itself lives in `ai/policy_compiler.py`. This module owns the schema,
the validator and the evaluator - the parts that must hold whether or not there
is a language model in the loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Sequence

from reversa.engines.policy_gates import Basis
from reversa.models import ActionType


class Field(StrEnum):
    """Everything a rule is allowed to look at. Nothing else is addressable."""

    AMOUNT = "amount_paise"
    P_NATURAL = "p_natural"
    CONFIDENCE = "confidence"
    FAILURE_CLASS = "failure_class"
    METHOD = "method"
    INSTRUMENT = "instrument"
    CUSTOMER_TIER = "customer_tier"
    EXPECTED_INCREMENTAL = "expected_incremental_paise"
    INCIDENT_ACTIVE = "incident_active"
    CREDIT_LINKED = "credit_linked"


NUMERIC_FIELDS = {
    Field.AMOUNT, Field.P_NATURAL, Field.CONFIDENCE, Field.EXPECTED_INCREMENTAL,
}
BOOLEAN_FIELDS = {Field.INCIDENT_ACTIVE, Field.CREDIT_LINKED}


class Op(StrEnum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    NEQ = "neq"
    IN = "in"


class Effect(StrEnum):
    """Every effect narrows. There is no effect that permits."""

    BLOCK = "block"
    """Remove one action, or all of them, from this candidate."""

    REQUIRE_HUMAN_REVIEW = "require_human_review"
    """Remove every automated action and route to a person."""

    WAIT = "wait"
    """Remove immediate actions, leaving delayed ones."""

    PREFER = "prefer_action"
    """Reorder among actions that are already permitted. Cannot add one."""


# Actions that count as "immediate" for a WAIT effect.
IMMEDIATE_ACTIONS = frozenset({ActionType.RETRY_NOW, ActionType.VOICE_CALL})


@dataclass(frozen=True, slots=True)
class Condition:
    field: str
    op: str
    value: Any

    def matches(self, ctx: dict) -> bool:
        actual = ctx.get(self.field)
        if actual is None:
            return False
        try:
            if self.op == Op.GT:
                return float(actual) > float(self.value)
            if self.op == Op.GTE:
                return float(actual) >= float(self.value)
            if self.op == Op.LT:
                return float(actual) < float(self.value)
            if self.op == Op.LTE:
                return float(actual) <= float(self.value)
            if self.op == Op.EQ:
                return actual == self.value
            if self.op == Op.NEQ:
                return actual != self.value
            if self.op == Op.IN:
                return actual in (self.value or [])
        except (TypeError, ValueError):
            # A malformed comparison must not silently pass. Failing closed
            # means the rule does not fire, which can only ever leave the
            # baseline gates in charge.
            return False
        return False

    def describe(self) -> str:
        symbol = {
            Op.GT: ">", Op.GTE: ">=", Op.LT: "<", Op.LTE: "<=",
            Op.EQ: "is", Op.NEQ: "is not", Op.IN: "in",
        }[Op(self.op)]
        value = self.value
        if self.field == Field.AMOUNT and isinstance(value, (int, float)):
            value = f"Rs {value / 100:,.0f}"
        return f"{self.field} {symbol} {value}"

    def as_dict(self) -> dict:
        return {"field": self.field, "op": self.op, "value": self.value}


@dataclass(frozen=True, slots=True)
class Rule:
    priority: int
    label: str
    conditions: tuple[Condition, ...]
    effect: str
    effect_arg: str | None = None
    source_span: str | None = None

    def matches(self, ctx: dict) -> bool:
        return all(c.matches(ctx) for c in self.conditions)

    def describe(self) -> str:
        when = " AND ".join(c.describe() for c in self.conditions) or "always"
        arg = f" ({self.effect_arg})" if self.effect_arg else ""
        return f"P{self.priority}: IF {when} -> {self.effect.upper()}{arg}"

    def as_dict(self) -> dict:
        return {
            "priority": self.priority,
            "label": self.label,
            "conditions": [c.as_dict() for c in self.conditions],
            "effect": self.effect,
            "effect_arg": self.effect_arg,
            "source_span": self.source_span,
            "describe": self.describe(),
        }


@dataclass(slots=True)
class Policy:
    name: str
    rules: list[Rule] = field(default_factory=list)
    source_text: str = ""
    warnings: list[str] = field(default_factory=list)
    compiled_by: str = "deterministic"

    def sorted_rules(self) -> list[Rule]:
        return sorted(self.rules, key=lambda r: r.priority)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "compiled_by": self.compiled_by,
            "source_text": self.source_text,
            "warnings": self.warnings,
            "rules": [r.as_dict() for r in self.sorted_rules()],
        }


@dataclass(slots=True)
class Decision:
    """What a policy did to one candidate's option set."""

    allowed: tuple[str, ...]
    blocked: dict[str, str]
    preferred: str | None
    requires_human_review: bool
    fired: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "allowed": list(self.allowed),
            "blocked": self.blocked,
            "preferred": self.preferred,
            "requires_human_review": self.requires_human_review,
            "fired": list(self.fired),
        }


def apply_policy(policy: Policy, ctx: dict, eligible: Sequence[str]) -> Decision:
    """Narrow an already-legal option set. Never widens it.

    `eligible` has already cleared every compliance gate. Policy runs after, and
    can only take options away - which is why a merchant policy cannot create a
    compliance hole no matter what it says.
    """
    allowed = list(eligible)
    blocked: dict[str, str] = {}
    preferred: str | None = None
    review = False
    fired: list[str] = []

    for rule in policy.sorted_rules():
        if not rule.matches(ctx):
            continue
        fired.append(rule.label)

        if rule.effect == Effect.REQUIRE_HUMAN_REVIEW:
            for action in allowed:
                blocked[action] = f"{rule.label}: routed to human review"
            allowed = []
            review = True
            break

        if rule.effect == Effect.BLOCK:
            targets = [rule.effect_arg] if rule.effect_arg else list(allowed)
            for action in targets:
                if action in allowed:
                    allowed.remove(action)
                    blocked[action] = f"{rule.label}: blocked by policy"

        elif rule.effect == Effect.WAIT:
            for action in list(allowed):
                if action in IMMEDIATE_ACTIONS:
                    allowed.remove(action)
                    blocked[action] = f"{rule.label}: hold until conditions stabilise"

        elif rule.effect == Effect.PREFER:
            # Only meaningful if the preferred action survived the gates. A
            # preference cannot resurrect a blocked option.
            if rule.effect_arg in allowed:
                preferred = rule.effect_arg

    return Decision(tuple(allowed), blocked, preferred, review, tuple(fired))


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rules_checked: int = 0
    unreachable: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "rules_checked": self.rules_checked,
            "unreachable": self.unreachable,
        }


VALID_ACTIONS = {a.value for a in ActionType}


def validate(policy: Policy) -> ValidationReport:
    """Structural check before a policy may be deployed.

    Deliberately paranoid about the things an LLM gets wrong: inventing a field,
    inventing an action, comparing a string to a number, or writing a rule that
    can never fire. None of these can breach a compliance gate - the effect
    vocabulary makes that impossible - but all of them silently produce a policy
    that does not do what the merchant asked, which is its own kind of failure.
    """
    report = ValidationReport(ok=True, rules_checked=len(policy.rules))
    seen_priorities: set[int] = set()

    for rule in policy.sorted_rules():
        if rule.effect not in set(Effect):
            report.errors.append(f"{rule.label}: unknown effect {rule.effect!r}")
        if rule.priority in seen_priorities:
            report.warnings.append(
                f"{rule.label}: duplicate priority {rule.priority}, order is ambiguous"
            )
        seen_priorities.add(rule.priority)

        if rule.effect in (Effect.BLOCK, Effect.PREFER) and rule.effect_arg:
            if rule.effect_arg not in VALID_ACTIONS:
                report.errors.append(
                    f"{rule.label}: {rule.effect_arg!r} is not an action this "
                    "system can take"
                )

        if not rule.conditions:
            report.warnings.append(
                f"{rule.label}: no conditions, fires on every candidate"
            )

        for cond in rule.conditions:
            if cond.field not in set(Field):
                report.errors.append(
                    f"{rule.label}: {cond.field!r} is not a field a rule may read"
                )
                continue
            if cond.op not in set(Op):
                report.errors.append(f"{rule.label}: unknown operator {cond.op!r}")
                continue
            numeric_op = cond.op in (Op.GT, Op.GTE, Op.LT, Op.LTE)
            if numeric_op and Field(cond.field) not in NUMERIC_FIELDS:
                report.errors.append(
                    f"{rule.label}: {cond.field} is not numeric, "
                    f"cannot compare with {cond.op}"
                )
            if numeric_op and not isinstance(cond.value, (int, float)):
                report.errors.append(
                    f"{rule.label}: {cond.value!r} is not a number"
                )
            if Field(cond.field) == Field.P_NATURAL and isinstance(cond.value, (int, float)):
                if not 0.0 <= float(cond.value) <= 1.0:
                    report.errors.append(
                        f"{rule.label}: p_natural is a probability, "
                        f"{cond.value} is outside [0, 1]"
                    )

    # A rule that can never fire is a merchant expectation that will silently
    # not be met, which is worth saying out loud.
    #
    # Guarded on the field being valid: this pass used to construct Field(...)
    # directly and blew up on exactly the unknown field the loop above had just
    # rejected - a validator that raises instead of reporting is no validator.
    for rule in policy.sorted_rules():
        for cond in rule.conditions:
            if cond.field not in set(Field):
                continue
            if (
                Field(cond.field) == Field.P_NATURAL
                and cond.op in (Op.GT, Op.GTE)
                and isinstance(cond.value, (int, float))
                and float(cond.value) >= 1.0
            ):
                report.unreachable.append(rule.label)

    report.ok = not report.errors
    return report


def enforcement_summary() -> dict:
    """What a policy can and cannot do, for the UI to state plainly."""
    return {
        "can": [
            "Block a specific action, or all actions, for matching candidates",
            "Route matching candidates to human review",
            "Hold immediate actions until conditions stabilise",
            "Prefer one already-permitted action over another",
        ],
        "cannot": [
            "Permit anything a compliance gate has refused",
            "Contact a customer outside the permitted window",
            "Override consent, opt-out or template registration",
            "Raise a capacity limit or a contact cap",
            "Read any field outside the allowlisted vocabulary",
            "Execute code - rules are data, never expressions",
        ],
        "tunable_basis": [Basis.CONFIGURED.value],
        "fields": sorted(f.value for f in Field),
        "effects": sorted(e.value for e in Effect),
    }
