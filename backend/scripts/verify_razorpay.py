"""Prove the Razorpay integration end to end, against the real test API.

    cd backend && PYTHONPATH=. python -m scripts.verify_razorpay

Creates an order, reads it back, and creates a Payment Link for a recovery -
three real calls, printing the ids so anyone can find them in the Razorpay
dashboard. This exists because "we integrated with Razorpay" is a claim, and a
claim in a readme is worth less than a command a reader can run.

It refuses to do anything without test credentials, and a `rzp_live_` key cannot
reach this code at all: the adapter rejects one at startup.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from reversa.adapters.razorpay_adapter import get_client


def main() -> int:
    client = get_client()
    stats = client.stats()
    if stats["mode"] != "razorpay_test":
        print(f"adapter is in {stats['mode']!r}, not razorpay_test.")
        print("set REVERSA_RAZORPAY_KEY_ID and REVERSA_RAZORPAY_KEY_SECRET first.")
        return 1

    stamp = int(datetime.now().timestamp())

    order = client.create_order(
        amount_paise=24_000_00,
        receipt=f"reversa-{stamp}",
        notes={"source": "reversa", "purpose": "integration verification"},
    )
    print(f"order created   {order['id']}  {order['status']}  {order['amount']} paise")

    echoed = client.fetch_order(order["id"])
    assert echoed["id"] == order["id"], "Razorpay returned a different order"
    print(f"order read back {echoed['id']}  {echoed['status']}")

    link = client.create_payment_link(
        amount_paise=24_000_00,
        description="Reversa - recovery of a failed UPI authorisation",
        customer={
            "name": "Asha Menon",
            "email": "asha@example.com",
            "contact": "+919812345670",
        },
        notify={"sms": False, "email": False},
        reference_id=f"reversa-verify-{stamp}",
        expire_by=datetime.now(timezone.utc) + timedelta(hours=24),
        notes={"order_id": order["id"]},
    )
    print(f"payment link    {link['id']}  {link['status']}")
    print(f"checkout page   {link['short_url']}")
    print(f"\n{client.stats()['live_api_calls']} live Razorpay calls in this run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
