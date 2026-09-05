"""Human review.

The interesting tests are about what does *not* reach a person. A queue that
holds everything is a rubber stamp, and a rubber stamp is worse than no gate:
it adds latency and records an automated decision as a human one.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.engines import review_engine as RV  # noqa: E402
from reversa.engines.portfolio_optimizer import Assignment, Candidate  # noqa: E402
from reversa.models import ActionType  # noqa: E402


def cand(pid, amount):
    return Candidate(
        payment_id=pid, customer_id=f"cus_{pid}", amount_paise=amount,
        failure_class="infra_transient", p_natural=0.5, confidence=0.9, uplift={},
    )


def assign(pid, action, lift, p_natural=0.5):
    return Assignment(
        payment_id=pid, customer_id=f"cus_{pid}", action=str(action),
        expected_incremental_paise=lift, cost_paise=0, p_natural=p_natural,
    )


# --- what reaches a person --------------------------------------------------

@pytest.mark.parametrize("action", sorted(RV.PAYER_CONTACTING))
def test_anything_the_customer_sees_reaches_a_person(action):
    """Regardless of amount. A cheap SMS is still an SMS to a real person."""
    t = RV.triage(action, amount_paise=1_00, cause_resolved=True)
    assert t.needs_human
    assert t.reason == RV.ReviewReason.CUSTOMER_CONTACT


def test_a_large_amount_reaches_a_person_even_when_silent():
    t = RV.triage(ActionType.RETRY_NOW, amount_paise=RV.HIGH_VALUE_PAISE, cause_resolved=True)
    assert t.needs_human
    assert t.reason == RV.ReviewReason.HIGH_VALUE


def test_an_unattributed_cause_escalates_even_a_silent_retry():
    """A plan built on an unexplained break is a guess with good arithmetic."""
    t = RV.triage(ActionType.RETRY_NOW, amount_paise=1_00, cause_resolved=False)
    assert t.needs_human
    assert t.reason == RV.ReviewReason.UNRESOLVED_CAUSE


def test_a_silent_reversible_retry_does_not():
    t = RV.triage(ActionType.RETRY_NOW, amount_paise=1_00, cause_resolved=True)
    assert not t.needs_human
    assert t.reason == RV.ReviewReason.SILENT_AND_REVERSIBLE


def test_doing_nothing_is_never_a_review():
    for action in (ActionType.NO_ACTION, ActionType.WAIT):
        t = RV.triage(action, amount_paise=10_00_00_00, cause_resolved=False)
        assert not t.needs_human


def test_contact_outranks_value_in_the_reason_given():
    """Both apply; the reviewer should read the more serious one first."""
    t = RV.triage(
        ActionType.PAYMENT_LINK, amount_paise=RV.HIGH_VALUE_PAISE * 10, cause_resolved=False,
    )
    assert t.reason == RV.ReviewReason.CUSTOMER_CONTACT


# --- the queue --------------------------------------------------------------

def test_the_queue_is_ordered_by_what_is_riding_on_the_decision():
    """Not by amount.

    A large payment that was recovering anyway carries almost no incremental
    value, and putting it at the top of the queue spends the reviewer's
    attention on the decision that matters least.
    """
    candidates = [cand("p_big", 90_000_00), cand("p_small", 900_00)]
    assignments = [
        assign("p_big", ActionType.PAYMENT_LINK, 100),        # huge, nearly no lift
        assign("p_small", ActionType.PAYMENT_LINK, 50_000),   # small, real lift
    ]
    queue = RV.build_queue(assignments, candidates)
    assert [c.payment_id for c in queue] == ["p_small", "p_big"]


def test_an_assignment_with_no_candidate_is_a_bug_not_a_skip():
    with pytest.raises(KeyError):
        RV.build_queue([assign("ghost", ActionType.RETRY_NOW, 10)], [cand("real", 100)])


def test_auto_approved_rows_still_say_why():
    """'Nobody looked at this' and 'this did not require looking at' are
    different claims, and the trail has to tell them apart."""
    queue = RV.build_queue(
        [assign("p1", ActionType.RETRY_NOW, 500)], [cand("p1", 1_000_00)],
    )
    row = queue[0]
    assert row.decision == RV.Decision.AUTO_APPROVED
    assert row.triage.reason == RV.ReviewReason.SILENT_AND_REVERSIBLE
    assert row.as_dict()["explanation"].strip()


def test_the_summary_splits_pending_from_auto_and_totals_the_value():
    candidates = [cand("p1", 1_000_00), cand("p2", 1_000_00), cand("p3", 90_000_00)]
    assignments = [
        assign("p1", ActionType.RETRY_NOW, 100),        # auto
        assign("p2", ActionType.PAYMENT_LINK, 200),     # contact -> pending
        assign("p3", ActionType.RETRY_NOW, 300),        # high value -> pending
    ]
    s = RV.summarise(RV.build_queue(assignments, candidates))
    assert s["total"] == 3
    assert s["pending"] == 2
    assert s["auto_approved"] == 1
    assert s["pending_value_paise"] == 500
    assert s["auto_value_paise"] == 100
    assert s["by_reason"] == {"customer_contact": 1, "high_value": 1}


def test_an_unresolved_cause_pulls_the_whole_plan_into_review():
    candidates = [cand(f"p{i}", 1_000_00) for i in range(5)]
    assignments = [assign(f"p{i}", ActionType.RETRY_NOW, 100) for i in range(5)]

    resolved = RV.summarise(RV.build_queue(assignments, candidates, cause_resolved=True))
    unresolved = RV.summarise(RV.build_queue(assignments, candidates, cause_resolved=False))

    assert resolved["pending"] == 0
    assert unresolved["pending"] == 5


def test_the_queue_is_capped_so_it_stays_reviewable():
    candidates = [cand(f"p{i}", 1_000_00) for i in range(200)]
    assignments = [assign(f"p{i}", ActionType.PAYMENT_LINK, i) for i in range(200)]
    assert len(RV.build_queue(assignments, candidates, limit=25)) == 25
