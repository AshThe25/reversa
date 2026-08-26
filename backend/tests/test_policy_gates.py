import pathlib
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.config import IST
from reversa.engines import policy_gates as G
from reversa.models import ActionType, ComplianceEvent

NOON_IST = datetime(2026, 8, 26, 12, 0, tzinfo=IST).astimezone(timezone.utc)


def ctx(subject, settings, index, *, now=NOON_IST, **kw):
    return G.GateContext(subject=subject, now=now, settings=settings, index=index, **kw)


# --- contact window (RBI 08:00-19:00 IST) ----------------------------------

@pytest.mark.parametrize(
    "hour,ok",
    [(7, False), (8, True), (12, True), (18, True), (19, False), (23, False), (3, False)],
)
def test_contact_window_boundaries(make_subject, settings, index, hour, ok):
    now = datetime(2026, 8, 26, hour, 30, tzinfo=IST).astimezone(timezone.utc)
    r = G.evaluate(ActionType.NUDGE_SMS, ctx(make_subject(), settings, index, now=now))
    assert next(v for v in r.verdicts if v.gate == "contact_window").allowed is ok


def test_out_of_window_is_temporal_not_permanent(make_subject, settings, index):
    late = datetime(2026, 8, 26, 22, 40, tzinfo=IST).astimezone(timezone.utc)
    r = G.evaluate(ActionType.NUDGE_SMS, ctx(make_subject(), settings, index, now=late))
    assert not r.allowed and not r.permanently_blocked
    reopen = r.earliest_retry.astimezone(IST)
    assert (reopen.hour, reopen.day) == (8, 27)  # tomorrow morning, not dropped


def test_silent_retry_ignores_contact_window(make_subject, settings, index):
    """a gateway re-presentment contacts nobody, so 02:00 is fine."""
    night = datetime(2026, 8, 26, 2, 15, tzinfo=IST).astimezone(timezone.utc)
    s = make_subject(reason="gateway_technical_error")
    assert G.evaluate(ActionType.RETRY_NOW, ctx(s, settings, index, now=night)).allowed


# --- freezes / consent ------------------------------------------------------

def test_open_complaint_freezes_contact_but_not_retries(
    session, make_subject, make_customer, settings
):
    cust = make_customer()
    session.add(ComplianceEvent(
        id=f"ce_{uuid.uuid4().hex[:8]}", customer_id=cust.id,
        event_type="complaint_raised", occurred_at=datetime.now(timezone.utc),
        active=True,
    ))
    session.flush()
    idx = G.ComplianceIndex.load(session, [cust.id])
    subj = make_subject(customer=cust)

    r = G.evaluate(ActionType.NUDGE_SMS, ctx(subj, settings, idx))
    assert not r.allowed and r.permanently_blocked


def test_opt_out_blocks_every_channel(make_subject, make_customer, settings, index):
    cust = make_customer(opted_out_at=datetime.now(timezone.utc))
    s = make_subject(customer=cust)
    for a in (ActionType.NUDGE_SMS, ActionType.NUDGE_EMAIL,
              ActionType.PAYMENT_LINK, ActionType.VOICE_CALL):
        assert not G.evaluate(a, ctx(s, settings, index)).allowed
    # but we can still silently re-present
    assert G.evaluate(ActionType.RETRY_DELAYED, ctx(s, settings, index)).allowed


def test_consent_is_per_channel(make_subject, make_customer, settings, index):
    cust = make_customer(sms_consent=True, whatsapp_consent=False, voice_consent=False)
    s = make_subject(customer=cust)
    assert G.evaluate(ActionType.NUDGE_SMS, ctx(s, settings, index)).allowed
    assert not G.evaluate(ActionType.NUDGE_WHATSAPP, ctx(s, settings, index)).allowed
    assert not G.evaluate(ActionType.VOICE_CALL, ctx(s, settings, index)).allowed


# --- frequency --------------------------------------------------------------

def test_min_gap_between_contacts(make_subject, settings, index):
    s = make_subject(contacts_used=1)
    index.note_contact(s.customer.id, NOON_IST - timedelta(hours=3))
    r = G.evaluate(ActionType.NUDGE_SMS, ctx(s, settings, index))
    assert not r.allowed and not r.permanently_blocked and r.earliest_retry


def test_per_case_contact_cap_is_permanent(make_subject, settings, index):
    s = make_subject(contacts_used=settings.max_contacts_per_case)
    r = G.evaluate(ActionType.NUDGE_SMS, ctx(s, settings, index))
    assert not r.allowed and r.permanently_blocked


def test_batch_contacts_are_visible_within_the_same_planning_pass(
    make_subject, settings, index
):
    """the bug this guards: planning 500 actions at once and hitting the same
    customer repeatedly because every one reads an empty history."""
    s = make_subject()
    assert G.evaluate(ActionType.NUDGE_SMS, ctx(s, settings, index)).allowed
    index.note_contact(s.customer.id, NOON_IST)
    assert not G.evaluate(ActionType.NUDGE_SMS, ctx(s, settings, index)).allowed


# --- instrument / downtime --------------------------------------------------

def test_expired_card_is_never_re_presented(make_subject, settings, index):
    s = make_subject(reason="card_expired")
    r = G.evaluate(ActionType.RETRY_NOW, ctx(s, settings, index))
    assert not r.allowed and r.permanently_blocked and "terminal" in r.reason
    # switching method is exactly what should be allowed instead
    assert G.evaluate(ActionType.SWITCH_METHOD, ctx(s, settings, index)).allowed


def test_active_downtime_suppresses_retry_now_and_nudges(make_subject, settings, index):
    s = make_subject(reason="bank_technical_decline")
    c = ctx(s, settings, index, instrument_down=True)
    assert not G.evaluate(ActionType.RETRY_NOW, c).allowed
    assert not G.evaluate(ActionType.NUDGE_SMS, c).allowed
    # waiting is always fine - it's the correct move during an incident
    assert G.evaluate(ActionType.WAIT, c).allowed
    assert G.evaluate(ActionType.RETRY_DELAYED, c).allowed


def test_risk_blocked_never_automated(make_subject, settings, index):
    s = make_subject(reason="risk_threshold_exceeded")
    for a in (ActionType.RETRY_NOW, ActionType.NUDGE_SMS, ActionType.PAYMENT_LINK):
        assert not G.evaluate(a, ctx(s, settings, index)).allowed
    assert G.evaluate(ActionType.HUMAN_REVIEW, ctx(s, settings, index)).allowed


def test_unknown_reason_codes_never_automated(make_subject, settings, index):
    s = make_subject(reason="some_code_invented_in_2027")
    assert not G.evaluate(ActionType.RETRY_NOW, ctx(s, settings, index)).allowed


def test_report_keeps_every_gate_not_just_the_first_failure(make_subject, settings, index):
    r = G.evaluate(ActionType.NUDGE_SMS, ctx(make_subject(), settings, index))
    assert len(r.verdicts) == len(G.GATES)
    assert all(v.rule for v in r.verdicts)
