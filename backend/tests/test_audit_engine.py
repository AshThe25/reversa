import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

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
