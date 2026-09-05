import os
import pathlib
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# Pin the signing secret for the whole run, before anything can read settings.
#
# Unset, the secret is generated per process, so any test that clears the
# settings cache to rebuild the app under different configuration silently
# invalidates every token issued before it. That is invisible on a machine with
# a .env pinning the secret and fails only where there is none - which is to say
# it passed here and broke in CI, eleven tests at once, all of them 401.
os.environ.setdefault("REVERSA_SESSION_SECRET", "test-only-secret-not-used-anywhere-real")

from reversa.config import Settings  # noqa: E402
from reversa.db import Base  # noqa: E402
from reversa.engines.policy_gates import ComplianceIndex, GateSubject  # noqa: E402
from reversa.models import Customer, Merchant  # noqa: E402
from reversa.taxonomy import classify  # noqa: E402


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    s.add(Merchant(id="mer_test", name="Test Merchant", category="d2c"))
    s.flush()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def settings():
    return Settings(_env_file=None)


@pytest.fixture()
def make_customer(session):
    def _make(**kw):
        c = Customer(
            id=kw.pop("id", f"cus_{uuid.uuid4().hex[:10]}"),
            merchant_id="mer_test",
            name=kw.pop("name", "Asha Menon"),
            email=kw.pop("email", "asha@example.com"),
            phone=kw.pop("phone", "+919812345670"),
            city=kw.pop("city", "Bengaluru"),
            tier=kw.pop("tier", "regular"),
            preferred_method=kw.pop("preferred_method", "upi"),
            **kw,
        )
        session.add(c)
        session.flush()
        return c

    return _make


@pytest.fixture()
def make_subject(make_customer):
    def _make(customer=None, reason="invalid_otp", **kw):
        customer = customer or make_customer()
        failed_at = kw.pop("failed_at", datetime.now(timezone.utc) - timedelta(hours=2))
        return GateSubject(
            payment_id=kw.pop("payment_id", f"pay_{uuid.uuid4().hex[:10]}"),
            customer=customer,
            amount_paise=kw.pop("amount_paise", 249900),
            failure_reason=reason,
            failure_class=kw.pop("failure_class", classify(reason).recovery_class.value),
            method=kw.pop("method", "card"),
            instrument=kw.pop("instrument", "VISA"),
            failed_at=failed_at,
            deadline_at=kw.pop("deadline_at", failed_at + timedelta(days=14)),
            **kw,
        )

    return _make


@pytest.fixture()
def index():
    return ComplianceIndex()
