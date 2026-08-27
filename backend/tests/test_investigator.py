"""Root-cause investigation.

The tests that matter here are the ones about refusal and grounding. An
investigator that always finds a cause is worse than none, and a narrative
resting on facts that do not exist is not partly correct.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.ai.investigator import (
    MIN_CONFIDENCE_TO_ACT, _from_payload, _validator, investigate_deterministic,
)
from reversa.engines.evidence_engine import HYPOTHESES, Evidence


def ev(id_, kind, *, supports=None, contradicts=None, detail=None):
    return Evidence(
        id=id_, kind=kind, label=f"{kind} fact", source="payment_stream",
        supports=supports, contradicts=contradicts, detail=detail or {},
    )


DROP = ev("ev_001", "auth_rate_drop", supports="any")


# --- attribution ------------------------------------------------------------

def test_a_method_wide_break_with_downtime_is_attributed_confidently():
    finding = investigate_deterministic([
        DROP,
        ev("ev_002", "scope_method_wide", supports="psp_switch_degradation"),
        ev("ev_003", "downtime_corroboration", supports="psp_switch_degradation"),
    ])
    assert finding.root_cause == "psp_switch_degradation"
    assert finding.confidence >= MIN_CONFIDENCE_TO_ACT
    assert finding.actionable and not finding.requires_human_review


def test_the_same_break_without_platform_corroboration_is_less_confident():
    """It should still conclude, but rest more lightly on one source."""
    with_dt = investigate_deterministic([
        DROP,
        ev("ev_002", "scope_method_wide", supports="psp_switch_degradation"),
        ev("ev_003", "downtime_corroboration", supports="psp_switch_degradation"),
    ])
    without = investigate_deterministic([
        DROP,
        ev("ev_002", "scope_method_wide", supports="psp_switch_degradation"),
        ev("ev_003", "no_downtime_published", contradicts="psp_switch_degradation"),
    ])
    assert without.root_cause == "psp_switch_degradation"
    assert without.confidence < with_dt.confidence


def test_a_contained_break_is_attributed_to_the_bank_not_the_rail():
    finding = investigate_deterministic([
        DROP, ev("ev_002", "scope_contained", supports="bank_core_outage"),
    ])
    assert finding.root_cause == "bank_core_outage"


# --- refusal ----------------------------------------------------------------

def test_a_degradation_with_no_common_parent_refuses_to_conclude():
    """The case the whole product hangs on. Damage across unrelated slices has
    no containable scope, so no root cause is supportable."""
    finding = investigate_deterministic([
        DROP,
        ev("ev_002", "scope_uncontained", contradicts="psp_switch_degradation",
           detail={"members": ["upi/oksbi", "card/VISA", "netbanking/SBIN"]}),
    ])
    assert finding.insufficient
    assert finding.requires_human_review
    assert not finding.actionable
    assert finding.confidence == 0.0
    assert finding.contradicting


def test_a_dispersed_and_split_decline_mix_refuses_to_conclude():
    finding = investigate_deterministic([
        DROP,
        ev("ev_002", "error_dispersion", contradicts="any_single_infrastructure_cause"),
        ev("ev_003", "source_split", contradicts="any_single_infrastructure_cause"),
    ])
    assert finding.insufficient and finding.requires_human_review


def test_refusal_explains_itself_in_terms_an_operator_can_check():
    finding = investigate_deterministic([
        DROP, ev("ev_002", "scope_uncontained", contradicts="psp_switch_degradation"),
    ])
    assert "no common parent" in finding.hypothesis
    assert finding.next_step and "human" in finding.next_step.lower()


def test_evidence_that_discriminates_nothing_still_refuses():
    """A statistically solid break with no distinguishing evidence is not a
    licence to pick the most likely-sounding cause."""
    finding = investigate_deterministic([DROP])
    assert finding.insufficient


def test_nothing_unattributable_is_ever_actionable():
    for evidence in (
        [DROP],
        [DROP, ev("ev_002", "scope_uncontained", contradicts="psp_switch_degradation")],
        [DROP, ev("ev_002", "error_dispersion", contradicts="x"),
         ev("ev_003", "source_split", contradicts="x")],
    ):
        assert not investigate_deterministic(evidence).actionable


# --- what the model is allowed to return ------------------------------------

def test_an_invented_hypothesis_is_rejected():
    errors = _validator({
        "root_cause": "solar_flare", "confidence": 0.9, "hypothesis": "x" * 40,
        "supporting_evidence": [], "contradicting_evidence": [],
    })
    assert any("not a known hypothesis" in e for e in errors)


def test_a_confidence_outside_zero_to_one_is_rejected():
    errors = _validator({
        "root_cause": "bank_core_outage", "confidence": 7, "hypothesis": "x" * 40,
        "supporting_evidence": [], "contradicting_evidence": [],
    })
    assert any("confidence" in e for e in errors)


def test_insufficient_evidence_is_a_valid_answer_not_an_error():
    assert _validator({
        "root_cause": "INSUFFICIENT_EVIDENCE", "confidence": 0.0,
        "hypothesis": "The evidence does not discriminate between causes here.",
        "supporting_evidence": [], "contradicting_evidence": ["ev_002"],
    }) == []
    assert "INSUFFICIENT_EVIDENCE" in HYPOTHESES


def test_a_fabricated_citation_lowers_groundedness_and_is_dropped():
    """A narrative resting partly on facts that do not exist is not partly
    correct - the caller falls back rather than publishing it."""
    evidence = [DROP, ev("ev_002", "scope_method_wide", supports="psp_switch_degradation")]
    finding = _from_payload({
        "root_cause": "psp_switch_degradation",
        "confidence": 0.9,
        "hypothesis": "Every instrument on the method degraded at once, per the evidence.",
        "supporting_evidence": ["ev_001", "ev_002", "ev_999"],
        "contradicting_evidence": [],
        "recommended_next_step": "suppress the method",
        "requires_human_review": False,
    }, evidence)

    assert finding.groundedness == pytest.approx(2 / 3, rel=1e-3)
    assert "ev_999" not in finding.supporting


def test_a_fully_grounded_response_scores_one():
    evidence = [DROP, ev("ev_002", "scope_method_wide", supports="psp_switch_degradation")]
    finding = _from_payload({
        "root_cause": "psp_switch_degradation", "confidence": 0.85,
        "hypothesis": "Every instrument on the method degraded together, per ev_002.",
        "supporting_evidence": ["ev_001", "ev_002"],
        "contradicting_evidence": [],
        "recommended_next_step": "suppress", "requires_human_review": False,
    }, evidence)
    assert finding.groundedness == 1.0 and finding.produced_by == "llm"


def test_a_model_finding_below_the_confidence_floor_is_not_actionable():
    evidence = [DROP]
    finding = _from_payload({
        "root_cause": "bank_core_outage", "confidence": 0.4,
        "hypothesis": "Possibly a bank issue, though the evidence is thin here.",
        "supporting_evidence": ["ev_001"], "contradicting_evidence": [],
        "recommended_next_step": "look", "requires_human_review": False,
    }, evidence)
    assert not finding.actionable
