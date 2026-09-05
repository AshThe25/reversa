"""The investigation agent.

What is worth testing here is not that the loop runs. It is that the trace tells
the truth: that the agent only used answers it actually asked for, that the
budget is a real ceiling, and that the catalogue of questions is wired to
evidence the engine genuinely produces.

That last one is not hypothetical. The first version of the tool catalogue
referenced six evidence kinds that did not exist, so half the questions returned
nothing and the agent looked like it was reasoning over an empty room.
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.ai.agent import (  # noqa: E402
    DEFAULT_BUDGET, TOOLS, cited_ids, run_deterministic,
)
from reversa.engines.evidence_engine import Evidence  # noqa: E402


def ev(id_, kind):
    return Evidence(id=id_, kind=kind, label=f"{kind} fact", source="payment_stream")


WIDE = [
    ev("ev_001", "auth_rate_drop"),
    ev("ev_002", "cross_method_reach"),
    ev("ev_003", "scope_method_wide"),
    ev("ev_004", "downtime_corroboration"),
    ev("ev_005", "error_concentration"),
]

NARROW = [
    ev("ev_001", "auth_rate_drop"),
    ev("ev_002", "scope_contained"),
    ev("ev_003", "no_downtime_published"),
]


def test_every_tool_maps_to_evidence_the_engine_actually_emits():
    """Guards the bug that shipped first: a catalogue of questions nobody answers.

    Read the kinds straight out of the engine source rather than importing a
    list, so adding a kind without offering it - or offering one that was
    renamed - fails here instead of silently returning an empty answer.
    """
    src = (
        pathlib.Path(__file__).resolve().parents[1]
        / "reversa" / "engines" / "evidence_engine.py"
    ).read_text()
    emitted = set(re.findall(r'kind="([a-z_]+)"', src))
    offered = {k for spec in TOOLS.values() for k in spec["kinds"]}

    assert not (offered - emitted), f"tools ask for kinds the engine never emits: {offered - emitted}"
    assert not (emitted - offered), f"engine emits kinds no question can reach: {emitted - offered}"


def test_the_budget_is_a_ceiling():
    for budget in (1, 2, 3, DEFAULT_BUDGET):
        trace = run_deterministic(WIDE, budget=budget)
        assert trace.asked <= budget


def test_running_out_of_budget_is_an_ending_not_an_error():
    trace = run_deterministic(NARROW, budget=2)
    assert trace.asked == 2
    assert trace.stopped_because == "budget_exhausted"


def test_it_stops_early_when_the_answers_in_hand_already_decide_it():
    """A method-wide degradation is upstream of any single instrument, so the
    remaining questions cannot move the conclusion."""
    trace = run_deterministic(WIDE)
    assert trace.stopped_because == "sufficient"
    assert trace.asked < len(TOOLS)
    assert trace.skipped


def test_the_stop_rule_only_reads_answers_the_agent_asked_for():
    """The regression that matters.

    An earlier stop rule tested the whole evidence list, so the agent could halt
    on a fact it had never retrieved and still report a three-question trace.
    Here the decisive fact exists but is only reachable through a question that
    comes after the early-stop check, so a trace claiming to have stopped early
    is claiming to have used evidence it never saw.
    """
    trace = run_deterministic(WIDE)
    seen = cited_ids(trace)
    for step in trace.steps:
        assert set(step.returned) <= seen
    # Nothing decisive may be claimed unless a question returned it.
    decisive = {"ev_002", "ev_003"}
    if trace.stopped_because == "sufficient":
        assert seen & decisive, "stopped early without having retrieved the deciding fact"


def test_every_step_records_why_it_was_asked():
    trace = run_deterministic(WIDE)
    assert trace.steps
    for step in trace.steps:
        assert step.rationale.strip(), f"step {step.n} has no rationale"
        assert step.tool in TOOLS


def test_asked_and_skipped_partition_the_catalogue():
    trace = run_deterministic(NARROW)
    assert set(t.tool for t in trace.steps) | set(trace.skipped) == set(TOOLS)
    assert not (set(t.tool for t in trace.steps) & set(trace.skipped))


def test_a_question_with_no_answer_says_so_rather_than_going_quiet():
    thin = [ev("ev_001", "auth_rate_drop")]
    trace = run_deterministic(thin, budget=3)
    empty = [s for s in trace.steps if not s.returned]
    assert empty, "expected at least one question with nothing on record"
    assert all(s.finding == "nothing on record" for s in empty)


def test_cited_ids_is_the_grounding_set_not_the_evidence_set():
    trace = run_deterministic(WIDE, budget=2)
    seen = cited_ids(trace)
    all_ids = {e.id for e in WIDE}
    assert seen < all_ids, "a two-question trace must not ground the whole evidence list"


def test_the_trace_serialises_for_the_api():
    payload = run_deterministic(WIDE).as_dict()
    assert set(payload) >= {
        "steps", "budget", "asked", "skipped", "stopped_because", "produced_by",
    }
    for step in payload["steps"]:
        assert set(step) >= {"n", "tool", "asks", "rationale", "returned", "finding"}
