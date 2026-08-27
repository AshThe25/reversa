"""Root-cause investigation.

This is the clearest example in the product of a language model being the right
tool: the input is a heterogeneous pile of measurements that point in different
directions, and the job is to weigh them and write down a conclusion a human can
argue with. That is synthesis, which models are good at.

It is also the clearest example of a model being deliberately fenced in.

  It cannot invent a hypothesis. The label must come from a fixed vocabulary;
  anything else is rejected.

  It cannot invent a fact. Every id it cites is checked against the evidence
  actually collected, and a single fabricated citation rejects the whole
  response. That check produces the groundedness score.

  It cannot authorise anything. The conclusion is a narrative attached to an
  incident. No money path reads it.

  It is expected to decline. INSUFFICIENT_EVIDENCE is a first-class answer, and
  the deterministic path reaches it on exactly the same rules, so the demo's
  refusal moment does not depend on a model being in the loop.

Without an API key the rule-based investigator runs instead. It is a real
implementation over the same evidence, and it exists so the product is
demonstrable with no credentials - and so there is something to compare the
model against.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from reversa.ai.client import LLMClient, get_client
from reversa.engines.evidence_engine import HYPOTHESES, Evidence

MIN_CONFIDENCE_TO_ACT = 0.65

SYSTEM_PROMPT = f"""You are a payments incident investigator. You are given
structured evidence collected from a merchant's authorisation stream and from
the payment platform's downtime feed. Weigh it and return a root-cause finding.

Return ONLY a JSON object:
{{"root_cause": str, "hypothesis": str, "confidence": float, "supporting_evidence": [str], "contradicting_evidence": [str], "recommended_next_step": str, "requires_human_review": bool}}

`root_cause` must be exactly one of:
{chr(10).join(f"  {k} - {v}" for k, v in HYPOTHESES.items())}

Hard rules:
- Cite evidence by its bracketed id. Every id you cite must appear in the
  evidence below. Do not invent ids and do not cite an id you did not use.
- `confidence` is your posterior in [0, 1] that `root_cause` is correct.
- If the evidence is dispersed, contradictory, or spans slices with no common
  parent, return root_cause "INSUFFICIENT_EVIDENCE" with the contradicting ids
  and set requires_human_review true. Concluding nothing is a correct answer and
  is preferred over a confident guess.
- `hypothesis` is two or three sentences of plain English an operator can argue
  with. State what the evidence shows, not what you assume.
- Never recommend a money-moving action. Recommend an investigative or
  operational next step."""


@dataclass(slots=True)
class Finding:
    root_cause: str
    hypothesis: str
    confidence: float
    supporting: tuple[str, ...]
    contradicting: tuple[str, ...]
    next_step: str
    requires_human_review: bool
    produced_by: str
    groundedness: float = 1.0
    latency_ms: float = 0.0
    cost_micro_usd: int = 0
    validation_errors: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = field(default=())

    @property
    def insufficient(self) -> bool:
        return self.root_cause == "INSUFFICIENT_EVIDENCE"

    @property
    def actionable(self) -> bool:
        """Whether a plan may be built on this finding at all."""
        return (
            not self.insufficient
            and not self.requires_human_review
            and self.confidence >= MIN_CONFIDENCE_TO_ACT
        )

    def as_dict(self) -> dict:
        return {
            "root_cause": self.root_cause,
            "root_cause_label": HYPOTHESES.get(self.root_cause, self.root_cause),
            "hypothesis": self.hypothesis,
            "confidence": round(self.confidence, 3),
            "supporting_evidence": list(self.supporting),
            "contradicting_evidence": list(self.contradicting),
            "recommended_next_step": self.next_step,
            "requires_human_review": self.requires_human_review,
            "insufficient_evidence": self.insufficient,
            "actionable": self.actionable,
            "produced_by": self.produced_by,
            "groundedness": round(self.groundedness, 3),
            "latency_ms": round(self.latency_ms, 1),
            "cost_micro_usd": self.cost_micro_usd,
            "validation_errors": list(self.validation_errors),
            "evidence": [e.as_dict() for e in self.evidence],
        }


def _validator(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["not an object"]
    if payload.get("root_cause") not in HYPOTHESES:
        errors.append(f"root_cause {payload.get('root_cause')!r} is not a known hypothesis")
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
        errors.append("confidence must be a number in [0, 1]")
    for key in ("supporting_evidence", "contradicting_evidence"):
        if not isinstance(payload.get(key), list):
            errors.append(f"{key} must be a list")
    if not isinstance(payload.get("hypothesis"), str) or len(payload["hypothesis"]) < 20:
        errors.append("hypothesis must be a short paragraph")
    return errors


def investigate(
    evidence: Sequence[Evidence], *, client: LLMClient | None = None
) -> Finding:
    """Weigh the evidence. Falls back to rules when no model is configured."""
    client = client or get_client()

    if client.available and evidence:
        started = time.perf_counter()
        rendered = "\n".join(e.as_prompt_line() for e in evidence)
        result = client.complete_json(
            system=SYSTEM_PROMPT,
            user=f"Evidence:\n{rendered}\n\nReturn the JSON finding.",
            validator=_validator,
        )
        if result is not None:
            finding = _from_payload(result.parsed, evidence)
            finding.latency_ms = (time.perf_counter() - started) * 1000
            finding.cost_micro_usd = result.cost_micro_usd

            # A fabricated citation invalidates the whole finding, not just the
            # citation. A narrative resting partly on facts that do not exist is
            # not partly correct.
            if finding.groundedness < 1.0:
                finding.validation_errors = (
                    f"cited {int((1 - finding.groundedness) * 100)}% evidence ids "
                    "that do not exist; falling back to the rule-based investigator",
                )
            else:
                return finding

    return investigate_deterministic(evidence)


def investigate_deterministic(evidence: Sequence[Evidence]) -> Finding:
    """Rules over the same evidence.

    Deliberately reaches INSUFFICIENT_EVIDENCE on the same conditions the model
    is told to: dispersed reason codes, a split between infrastructure and
    customer-side origins, or damage spanning slices with no common parent. The
    refusal in the demo is therefore a property of the system, not of whichever
    model happened to answer.
    """
    by_kind = {e.kind: e for e in evidence}
    ids = {e.id for e in evidence}

    contradicting = tuple(e.id for e in evidence if e.contradicts)
    supporting_for = lambda h: tuple(  # noqa: E731
        e.id for e in evidence if e.supports in (h, "any")
    )

    uncontained = "scope_uncontained" in by_kind
    dispersed = "error_dispersion" in by_kind
    split = "source_split" in by_kind
    cross_method = "cross_method_reach" in by_kind

    if uncontained or (dispersed and split):
        reasons = []
        if uncontained:
            reasons.append(
                "the degradation lands on slices with no common parent, which no "
                "single rail explains"
            )
        if dispersed:
            reasons.append("no reason code dominates the decline mix")
        if split:
            reasons.append(
                "declines split roughly evenly between infrastructure and "
                "customer-side origins"
            )
        return Finding(
            root_cause="INSUFFICIENT_EVIDENCE",
            hypothesis=(
                "The degradation is real and measurable, but its cause is not "
                "attributable from the available evidence: "
                + "; ".join(reasons)
                + ". A PSP fault would take one method down together and a single "
                "bank fault would stay inside one instrument. This does neither, "
                "so any root cause named here would be a guess carrying a "
                "confidence score."
            ),
            confidence=0.0,
            supporting=(),
            contradicting=contradicting,
            next_step=(
                "Route to a human. Compare merchant-side checkout latency against "
                "issuer response times for the window before treating any cohort."
            ),
            requires_human_review=True,
            produced_by="deterministic",
            evidence=tuple(evidence),
        )

    if "scope_method_wide" in by_kind:
        corroborated = "downtime_corroboration" in by_kind
        return Finding(
            root_cause="psp_switch_degradation",
            hypothesis=(
                "Every instrument on this method degraded simultaneously while "
                "other methods held, which is the signature of a fault at the PSP "
                "or switch rather than at any one bank."
                + (
                    " The platform published downtime for the same rail, which "
                    "corroborates it independently."
                    if corroborated
                    else " No platform downtime was published, so this rests on the "
                    "merchant-side stream alone."
                )
            ),
            confidence=0.88 if corroborated else 0.7,
            supporting=supporting_for("psp_switch_degradation"),
            contradicting=contradicting,
            next_step=(
                "Suppress this method at checkout until the auth rate recovers, and "
                "hold re-presentment until the rail has settled."
            ),
            requires_human_review=False,
            produced_by="deterministic",
            evidence=tuple(evidence),
        )

    if "scope_contained" in by_kind:
        return Finding(
            root_cause="bank_core_outage",
            hypothesis=(
                "The degradation is confined to a single instrument while its "
                "siblings on the same method are unaffected, which points at that "
                "bank rather than at shared infrastructure."
            ),
            confidence=0.78,
            supporting=supporting_for("bank_core_outage"),
            contradicting=contradicting,
            next_step=(
                "Deprioritise this instrument at checkout and re-present affected "
                "authorisations once its auth rate recovers."
            ),
            requires_human_review=False,
            produced_by="deterministic",
            evidence=tuple(evidence),
        )

    if cross_method:
        return Finding(
            root_cause="merchant_side_latency",
            hypothesis=(
                "Auth rates fell across several methods at once. Independent rails "
                "failing together points upstream of all of them - checkout or the "
                "merchant's own integration - rather than at any one provider."
            ),
            confidence=0.66,
            supporting=supporting_for("merchant_side_latency"),
            contradicting=contradicting,
            next_step=(
                "Check checkout latency and error rates for the window before "
                "treating any cohort."
            ),
            requires_human_review=False,
            produced_by="deterministic",
            evidence=tuple(evidence),
        )

    concentration = by_kind.get("error_concentration")
    if concentration and concentration.detail.get("error_source") == "issuer":
        return Finding(
            root_cause="issuer_authorisation_timeout",
            hypothesis=(
                "Declines concentrate on issuer-side authorisation failures, which "
                "points at the issuing side rather than the acquiring path."
            ),
            confidence=0.72,
            supporting=supporting_for("issuer_authorisation_timeout"),
            contradicting=contradicting,
            next_step="Re-present after the issuer's timeout window rather than immediately.",
            requires_human_review=False,
            produced_by="deterministic",
            evidence=tuple(evidence),
        )

    return Finding(
        root_cause="INSUFFICIENT_EVIDENCE",
        hypothesis=(
            "The auth-rate break is statistically solid, but none of the collected "
            "evidence discriminates between the candidate causes."
        ),
        confidence=0.0,
        supporting=(),
        contradicting=contradicting or tuple(sorted(ids))[:1],
        next_step="Route to a human before treating any cohort.",
        requires_human_review=True,
        produced_by="deterministic",
        evidence=tuple(evidence),
    )


def _from_payload(payload: dict, evidence: Sequence[Evidence]) -> Finding:
    ids = {e.id for e in evidence}
    supporting = [str(x) for x in payload.get("supporting_evidence", [])]
    contradicting = [str(x) for x in payload.get("contradicting_evidence", [])]
    cited = supporting + contradicting
    real = [c for c in cited if c in ids]
    groundedness = len(real) / len(cited) if cited else 1.0

    return Finding(
        root_cause=str(payload["root_cause"]),
        hypothesis=str(payload["hypothesis"]),
        confidence=float(payload["confidence"]),
        supporting=tuple(c for c in supporting if c in ids),
        contradicting=tuple(c for c in contradicting if c in ids),
        next_step=str(payload.get("recommended_next_step", ""))[:400],
        requires_human_review=bool(payload.get("requires_human_review", False)),
        produced_by="llm",
        groundedness=groundedness,
        evidence=tuple(evidence),
    )
