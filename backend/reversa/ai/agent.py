"""The investigation agent.

The one-shot investigator in `investigator.py` is handed every fact at once and
asked to weigh them. That is synthesis, and it works, but it cannot chase a
lead: it never decides that a number is worth a second look, and it never
declines to look at something because it already knows enough.

This is the loop. The agent sees a catalogue of questions it may ask about an
incident, asks one at a time, and after each answer either asks another or
stops. What makes the trace worth reading is not that the model talks to itself
- it is that the model *chose* an order and *chose* when to stop, and both
choices are recorded next to the evidence that drove them.

The fences from the one-shot path all still stand:

  It cannot invent a question. The tool name must be in the catalogue.
  It cannot invent a fact. Tools return evidence ids collected from the stream
  and the downtime feed; the groundedness check rejects any citation that did
  not come back from a tool the agent actually called.
  It cannot spend forever. The budget is fixed before the loop starts, and
  running out is a normal ending rather than an error.
  It is expected to decline. INSUFFICIENT_EVIDENCE remains a first-class
  conclusion, and the deterministic agent reaches it on the same rules.

One honest note on the implementation: `evidence_engine.collect()` runs a single
pass over the incident and returns everything it can establish. The tools here
serve slices of that result rather than issuing a fresh query each. The agent's
decisions are real - which questions it asks, in what order, and when it has
enough - but the database is read once, not once per step. Making each tool a
separate query would cost several seconds per investigation and change none of
the reasoning.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from typing import TYPE_CHECKING

from reversa.ai.client import LLMClient, get_client
from reversa.ai.probes import CATALOGUE as PROBE_CATALOGUE
from reversa.ai.probes import ProbeBudgetExceeded
from reversa.engines.evidence_engine import HYPOTHESES, Evidence

if TYPE_CHECKING:
    from reversa.ai.probes import Probes

# How many questions the agent may ask before it must conclude on what it has.
# Five is not arbitrary: the catalogue has six tools, and an agent that calls
# every one of them has not prioritised anything.
DEFAULT_BUDGET = 5


# --- the question catalogue -------------------------------------------------
#
# Each tool maps to the evidence kinds `collect()` produces. The description is
# what the model sees, so it is written as a question an analyst would ask
# rather than as a field name.

TOOLS: dict[str, dict[str, Any]] = {
    "measure_the_break": {
        "asks": "How big is the auth-rate drop, over what window, and is it statistically solid?",
        "kinds": ("auth_rate_drop",),
    },
    "decline_reason_mix": {
        "asks": "Do the declines concentrate on one reason code, or are they spread across many?",
        "kinds": ("error_concentration", "error_dispersion", "source_split"),
    },
    "platform_downtime": {
        "asks": "Did the payment platform publish downtime overlapping this window?",
        "kinds": ("downtime_corroboration", "no_downtime_published"),
    },
    "other_methods": {
        "asks": "Are other payment methods degraded at the same time, or is this one isolated?",
        "kinds": ("cross_method_reach",),
    },
    "sibling_instruments": {
        "asks": "Within this method, is every instrument affected or only one?",
        "kinds": ("scope_contained", "scope_method_wide"),
    },
    "slice_shape": {
        "asks": "Do the affected slices share a parent, or do they scatter with no common rail?",
        "kinds": ("scope_uncontained",),
    },
}


@dataclass(slots=True)
class Step:
    """One question and what came back."""

    n: int
    tool: str
    rationale: str
    returned: tuple[str, ...]
    finding: str

    def as_dict(self) -> dict:
        return {
            "n": self.n,
            "tool": self.tool,
            "asks": TOOLS[self.tool]["asks"] if self.tool in TOOLS else "",
            "rationale": self.rationale,
            "returned": list(self.returned),
            "finding": self.finding,
        }


@dataclass(slots=True)
class Trace:
    steps: tuple[Step, ...] = field(default=())
    budget: int = DEFAULT_BUDGET
    stopped_because: str = "concluded"
    produced_by: str = "rules"
    latency_ms: float = 0.0

    @property
    def asked(self) -> int:
        return len(self.steps)

    @property
    def skipped(self) -> tuple[str, ...]:
        """Questions the agent chose not to ask.

        Worth surfacing: an investigator that declines to check three things and
        says why is making a judgement, and the judgement is reviewable.
        """
        used = {s.tool for s in self.steps}
        return tuple(t for t in TOOLS if t not in used)

    def as_dict(self) -> dict:
        return {
            "steps": [s.as_dict() for s in self.steps],
            "budget": self.budget,
            "asked": self.asked,
            "skipped": list(self.skipped),
            "stopped_because": self.stopped_because,
            "produced_by": self.produced_by,
            "latency_ms": round(self.latency_ms, 1),
        }


def _by_kind(evidence: Sequence[Evidence], kinds: Sequence[str]) -> list[Evidence]:
    return [e for e in evidence if e.kind in kinds]


def _summarise(items: Sequence[Evidence]) -> str:
    if not items:
        return "nothing on record"
    return "; ".join(e.as_prompt_line() for e in items)


# Arguments a model may pass. Anything else is dropped rather than forwarded:
# a probe signature is not a place to discover what a model invented.
_PROBE_ARGS: dict[str, frozenset[str]] = {
    name: frozenset(spec["params"]) for name, spec in PROBE_CATALOGUE.items()
}


def _run_probe(probes: "Probes", name: str, args: dict) -> tuple[list[Evidence], str]:
    """Execute one probe with the arguments the model chose.

    Unknown keys are dropped and bad types are refused here rather than at the
    query, so a malformed argument costs the agent a step and an explanation
    instead of raising out of the loop. Budget exhaustion is the same: it is an
    answer the agent can act on, not a crash.
    """
    if name not in _PROBE_ARGS:
        return [], f"{name} is not a probe"

    clean: dict = {}
    for key, value in args.items():
        if key not in _PROBE_ARGS[name]:
            continue
        if key in ("window_minutes", "lookback_days"):
            try:
                clean[key] = int(value)
            except (TypeError, ValueError):
                continue
        else:
            clean[key] = str(value)

    try:
        result = getattr(probes, name)(**clean)
    except ProbeBudgetExceeded as exc:
        return [], str(exc)
    except TypeError as exc:
        # A required parameter the model did not supply - sibling_instruments
        # needs a method, for instance.
        return [], f"{name} needs different arguments: {exc}"

    return result.evidence, result.summary


# --- the deterministic agent ------------------------------------------------


def run_deterministic(evidence: Sequence[Evidence], *, budget: int = DEFAULT_BUDGET) -> Trace:
    """The same loop driven by rules instead of a model.

    It is not a stub. The ordering encodes how an on-call engineer actually
    triages a payments incident: establish the break is real, then find out how
    wide it is, because width is what separates a PSP fault from one bank having
    a bad afternoon. It stops as soon as the remaining questions cannot change
    the answer, which is the behaviour the model is being asked to imitate.
    """
    started = time.perf_counter()
    order = [
        "measure_the_break",
        "other_methods",
        "sibling_instruments",
        "decline_reason_mix",
        "platform_downtime",
        "slice_shape",
    ]
    steps: list[Step] = []
    stopped = "concluded"

    for name in order:
        if len(steps) >= budget:
            stopped = "budget_exhausted"
            break

        items = _by_kind(evidence, TOOLS[name]["kinds"])
        rationale = {
            "measure_the_break": "Establish the drop is real before explaining it.",
            "other_methods": "Width first: a fault that crosses methods is upstream of all of them.",
            "sibling_instruments": "If it stays inside one instrument it is that issuer, not the rail.",
            "decline_reason_mix": "A single dominant reason code names the layer that failed.",
            "platform_downtime": "Independent corroboration from the platform's own feed.",
            "slice_shape": "Scatter with no common parent means no single rail explains it.",
        }[name]

        steps.append(Step(
            n=len(steps) + 1,
            tool=name,
            rationale=rationale,
            returned=tuple(e.id for e in items),
            finding=_summarise(items),
        ))

        # Stop early when the answers already in hand decide it: a degradation
        # that spans a whole method is upstream of any one instrument, and the
        # reason mix cannot overturn that.
        #
        # This only looks at evidence returned by questions actually asked. An
        # earlier version tested the whole evidence list, which let the rule
        # stop on a fact the agent had not retrieved - a trace that claims to
        # have decided on three answers while really using five is worse than
        # no trace at all.
        seen = {eid for st in steps for eid in st.returned}
        decisive = {
            e.id for e in _by_kind(evidence, ("cross_method_reach", "scope_method_wide"))
        }
        if name == "sibling_instruments" and seen & decisive:
            stopped = "sufficient"
            break

    return Trace(
        steps=tuple(steps),
        budget=budget,
        stopped_because=stopped,
        produced_by="rules",
        latency_ms=(time.perf_counter() - started) * 1000,
    )


# --- the model-driven agent -------------------------------------------------

SYSTEM_PROMPT = f"""You are a payments incident investigator working one question
at a time. You may ask only the questions in the catalogue you are given. After
each answer, decide whether to ask another question or to conclude.

Ask fewer questions rather than more. Stop as soon as the remaining questions
cannot change your answer, and say so.

Return ONLY a JSON object, one of these two shapes.

To ask:
{{"action": "ask", "tool": "<name from the catalogue>",
  "args": {{...}}, "why": "<one sentence>"}}

`args` are the parameters for that tool. Choose them - narrow a window, name a
specific instrument, look further back - rather than accepting defaults, because
choosing them is the point of asking.

To finish:
{{"action": "conclude", "root_cause": "<one of: {', '.join(HYPOTHESES)}>",
  "confidence": <0.0-1.0>, "rationale": "<two sentences>",
  "cites": ["<evidence id>", ...]}}

Rules:
- Every id in `cites` must have been returned to you by a question you asked.
- If the evidence does not discriminate between causes, return
  INSUFFICIENT_EVIDENCE with confidence 0.0. That is a correct answer, not a
  failure.
- Never name a root cause the evidence cannot carry.
"""


def _step_validator(payload: Any) -> list[str]:
    errs: list[str] = []
    if not isinstance(payload, dict):
        return ["response must be a JSON object"]
    action = payload.get("action")
    if action not in ("ask", "conclude"):
        errs.append("action must be 'ask' or 'conclude'")
        return errs
    if action == "ask":
        known = set(TOOLS) | set(PROBE_CATALOGUE)
        if payload.get("tool") not in known:
            errs.append(f"tool must be one of: {', '.join(sorted(known))}")
        if "args" in payload and not isinstance(payload["args"], dict):
            errs.append("args must be an object")
        if not str(payload.get("why", "")).strip():
            errs.append("why is required")
    else:
        if payload.get("root_cause") not in HYPOTHESES:
            errs.append(f"root_cause must be one of: {', '.join(HYPOTHESES)}")
        try:
            c = float(payload.get("confidence"))
            if not 0.0 <= c <= 1.0:
                errs.append("confidence must be between 0 and 1")
        except (TypeError, ValueError):
            errs.append("confidence must be a number")
        if not isinstance(payload.get("cites"), list):
            errs.append("cites must be a list of evidence ids")
    return errs


def run_agent(
    evidence: Sequence[Evidence],
    *,
    client: LLMClient | None = None,
    budget: int = DEFAULT_BUDGET,
    probes: "Probes | None" = None,
) -> tuple[Trace, dict | None]:
    """Drive the loop with a model, falling back to rules with no key.

    With `probes`, the agent writes its own query arguments and they run against
    the payment stream when asked. Without them it reads the pre-computed
    evidence slices, which is what the deterministic path uses and what any
    caller without a database session gets.

    Returns the trace and the concluding payload. A None payload means the agent
    never concluded - it ran out of budget - and the caller should treat that
    the same as insufficient evidence rather than inventing an answer.
    """
    client = client or get_client()
    if not client.available:
        return run_deterministic(evidence, budget=budget), None

    started = time.perf_counter()
    if probes is not None:
        catalogue = "\n".join(
            f"- {name}: {spec['asks']}\n    args: "
            + ", ".join(f"{k} ({v})" for k, v in spec["params"].items())
            for name, spec in PROBE_CATALOGUE.items()
        )
        available = list(PROBE_CATALOGUE)
    else:
        catalogue = "\n".join(f"- {name}: {spec['asks']}" for name, spec in TOOLS.items())
        available = list(TOOLS)
    steps: list[Step] = []
    transcript: list[str] = []
    stopped = "concluded"
    conclusion: dict | None = None

    while True:
        if len(steps) >= budget:
            stopped = "budget_exhausted"
            break

        # With probes, a tool stays available - asking auth_rate again with a
        # tighter window is the whole point. Without them each slice is read
        # once, because reading it twice returns the same rows.
        if probes is not None:
            remaining = available
        else:
            remaining = [t for t in available if t not in {s.tool for s in steps}]
        if not remaining:
            stopped = "no_questions_left"
            break

        user = (
            f"Questions still available:\n"
            + "\n".join(
                f"- {t}: {(PROBE_CATALOGUE if probes is not None else TOOLS)[t]['asks']}"
                for t in remaining
            )
            + f"\n\nAnswers so far ({len(steps)} of {budget} questions used):\n"
            + ("\n".join(transcript) if transcript else "none yet")
        )
        result = client.complete_json(
            system=SYSTEM_PROMPT + f"\n\nFull catalogue:\n{catalogue}",
            user=user,
            validator=_step_validator,
        )
        if result is None:
            # The model failed the schema twice. Finish on rules rather than
            # leaving the incident un-investigated.
            det = run_deterministic(evidence, budget=budget)
            det.produced_by = "rules_after_model_error"
            return det, None

        payload = result.parsed
        if payload["action"] == "conclude":
            conclusion = payload
            break

        name = payload["tool"]
        if probes is not None:
            items, summary = _run_probe(probes, name, payload.get("args") or {})
        else:
            items = _by_kind(evidence, TOOLS[name]["kinds"])
            summary = _summarise(items)
        steps.append(Step(
            n=len(steps) + 1,
            tool=name,
            rationale=str(payload["why"]).strip(),
            returned=tuple(e.id for e in items),
            finding=summary,
        ))
        transcript.append(f"Q{len(steps)} {name}: {summary}")

    trace = Trace(
        steps=tuple(steps),
        budget=budget,
        stopped_because=stopped,
        produced_by="anthropic",
        latency_ms=(time.perf_counter() - started) * 1000,
    )
    return trace, conclusion


def cited_ids(trace: Trace) -> set[str]:
    """Every evidence id the agent actually received.

    The groundedness check runs against this rather than against all evidence:
    citing a fact the agent never asked for is a fabrication even when the fact
    happens to be true.
    """
    return {eid for step in trace.steps for eid in step.returned}
