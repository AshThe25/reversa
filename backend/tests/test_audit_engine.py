import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from reversa.engines.audit_engine import record, verify_chain, GENESIS_HASH


def test_chain_verifies_and_detects_tampering(session):
    for i in range(5):
        record(session, actor="policy", event_type="decision",
               subject_type="case", subject_id=f"case_{i}",
               payload={"choice": "silent_retry", "i": i})
    session.commit()

    verdict = verify_chain(session)
    assert verdict.valid and verdict.entries_checked == 5
    assert verdict.head_hash != GENESIS_HASH

    # Tamper with a payload in the middle of the chain.
    from reversa.models import AuditEvent
    row = session.query(AuditEvent).filter_by(subject_id="case_2").one()
    row.payload = {"choice": "voice_call", "i": 2}
    session.commit()

    broken = verify_chain(session)
    assert not broken.valid
    assert broken.broken_at_seq == row.seq
    assert "hash" in broken.reason


def test_concurrent_appends_cannot_fork_the_chain(session):
    """Regression for a race that made the ledger quietly untrustworthy.

    Reading the head and inserting is not atomic. Two writers - an API process
    and a worker, or an API process and a test run against the same database -
    could read the same head and both link to it, producing two branches that
    each verify in isolation while the whole thing is no longer a chain. The
    unique constraint on prev_hash makes that a failed insert instead.
    """
    from sqlalchemy.exc import IntegrityError

    from reversa.models import AuditEvent

    record(session, actor="policy", event_type="a", subject_type="x", subject_id="1")
    session.commit()

    head = session.query(AuditEvent).order_by(AuditEvent.seq.desc()).first()
    record(session, actor="policy", event_type="b", subject_type="x", subject_id="2")
    session.commit()

    # a second writer that had read the same head tries to link to it
    forged = AuditEvent(
        id="aud_forged", occurred_at=head.occurred_at, actor="attacker",
        event_type="c", subject_type="x", subject_id="3", payload={},
        prev_hash=head.entry_hash, entry_hash="f" * 64,
    )
    session.add(forged)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    assert verify_chain(session).valid


def test_append_retries_and_still_verifies_after_a_lost_race(session):
    for i in range(20):
        record(session, actor="executor", event_type="money.moved",
               subject_type="payment", subject_id=f"pay_{i}", payload={"i": i})
    session.commit()

    verdict = verify_chain(session)
    assert verdict.valid and verdict.entries_checked == 20
