import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from reversa.config import Settings
from reversa.adapters.razorpay_adapter import RazorpayClient, RazorpayError


def _client(budget=3):
    return RazorpayClient(Settings(payment_link_budget=budget, _env_file=None))


def test_offline_mode_flags_every_response():
    c = _client()
    order = c.create_order(49900, "rcpt_1")
    assert order["_offline"] is True
    assert c.stats()["mode"] == "offline"
    assert c.stats()["live_api_calls"] == 0


def test_link_budget_is_enforced_and_reports_remaining():
    c = _client(budget=2)
    args = dict(amount_paise=10000, description="d", customer={"name": "A"},
                notify={"sms": True}, reference_id="r")
    c.create_payment_link(**args)
    c.create_payment_link(**args)
    assert c.link_budget.remaining == 0

    with pytest.raises(RazorpayError) as exc:
        c.create_payment_link(**args)
    assert exc.value.status == 429
    assert "budget exhausted" in str(exc.value)
