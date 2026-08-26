"""Failure ontology.

Razorpay tags every failed payment with (source, step, reason). That triple is
what we reason over — not an LLM guess. This maps it to two things the rest of
the system needs: a recovery class (what would have to change for the money to
move) and whether the same instrument is even worth re-presenting.

Anything not in the table falls through to UNKNOWN, which the policy engine
refuses to act on. A new reason code showing up in prod should become an
exception-list row, not a confident wrong decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorSource(StrEnum):
    CUSTOMER = "customer"
    BUSINESS = "business"
    BANK = "bank"
    GATEWAY = "gateway"
    NETWORK = "network"
    ISSUER = "issuer"
    RAZORPAY = "razorpay"


class ErrorStep(StrEnum):
    INITIATION = "payment_initiation"
    AUTHENTICATION = "payment_authentication"
    AUTHORIZATION = "payment_authorization"
    CAPTURE = "payment_capture"


class RecoveryClass(StrEnum):
    """What kind of thing has to change for this payment to succeed."""

    INFRA_TRANSIENT = "infra_transient"
    """The rail was down or degraded. Nothing about the payer is wrong.
    Waiting is the intervention; contacting the payer is actively harmful."""

    LIQUIDITY = "liquidity"
    """The payer has no money right now. Time is the intervention -- and the
    right time is payday, not four hours from now."""

    INSTRUMENT_INVALID = "instrument_invalid"
    """The instrument itself is dead (expired card, closed account, bad VPA).
    No retry on this instrument will ever work; only a switch will."""

    AUTH_FRICTION = "auth_friction"
    """Payer was present and willing but lost the auth step -- OTP timeout,
    wrong PIN, app did not respond. Highest-yield cohort in the corpus."""

    LIMIT_BREACH = "limit_breach"
    """Per-transaction or daily limit. Succeeds later, or on another rail."""

    INTENT_ABSENT = "intent_absent"
    """Payer actively cancelled. Recoverable, but this is a marketing problem,
    not a payments one, and the compliance cost of pestering is real."""

    RISK_BLOCKED = "risk_blocked"
    """Blocked by a risk rule. Never auto-retried. Human review only."""

    UNKNOWN = "unknown"
    """Not in the ontology. Never auto-actioned; lands in the exception list."""


NEVER_AUTO_ACTION = {RecoveryClass.RISK_BLOCKED, RecoveryClass.UNKNOWN}


@dataclass(frozen=True, slots=True)
class FailureMode:
    reason: str
    source: ErrorSource
    step: ErrorStep
    recovery_class: RecoveryClass
    description: str
    same_instrument_viable: bool
    """Can this instrument ever work again? False for dead cards/accounts."""


def _fm(*args, **kwargs) -> FailureMode:
    return FailureMode(*args, **kwargs)


# Reason strings and their (source, step) mirror Razorpay's published payment
# error list. Recovery class and viability are our modelling layer on top.
FAILURE_MODES: dict[str, FailureMode] = {
    fm.reason: fm
    for fm in [
        # --- authentication friction: payer was there, auth fell over -------
        _fm("invalid_otp", ErrorSource.CUSTOMER, ErrorStep.AUTHENTICATION,
            RecoveryClass.AUTH_FRICTION,
            "Payer entered an incorrect OTP.", True),
        _fm("payment_timeout", ErrorSource.CUSTOMER, ErrorStep.AUTHENTICATION,
            RecoveryClass.AUTH_FRICTION,
            "Payer did not complete authentication in time.", True),
        _fm("incorrect_upi_pin", ErrorSource.CUSTOMER, ErrorStep.AUTHENTICATION,
            RecoveryClass.AUTH_FRICTION,
            "Incorrect UPI PIN entered.", True),
        _fm("upi_app_not_responding", ErrorSource.BANK, ErrorStep.AUTHENTICATION,
            RecoveryClass.AUTH_FRICTION,
            "The payer's UPI app did not respond to the collect request.", True),
        _fm("incorrect_cvv", ErrorSource.CUSTOMER, ErrorStep.AUTHENTICATION,
            RecoveryClass.AUTH_FRICTION,
            "Incorrect CVV supplied.", True),
        _fm("3ds_authentication_failed", ErrorSource.ISSUER, ErrorStep.AUTHENTICATION,
            RecoveryClass.AUTH_FRICTION,
            "Issuer 3DS authentication did not complete.", True),

        # --- liquidity ------------------------------------------------------
        _fm("insufficient_funds", ErrorSource.CUSTOMER, ErrorStep.AUTHORIZATION,
            RecoveryClass.LIQUIDITY,
            "Insufficient balance in the payer's account.", True),
        _fm("insufficient_balance_wallet", ErrorSource.CUSTOMER, ErrorStep.AUTHORIZATION,
            RecoveryClass.LIQUIDITY,
            "Wallet balance too low for this amount.", True),

        # --- dead instruments ----------------------------------------------
        _fm("card_expired", ErrorSource.CUSTOMER, ErrorStep.AUTHORIZATION,
            RecoveryClass.INSTRUMENT_INVALID,
            "The card has passed its expiry date.", False),
        _fm("invalid_card_number", ErrorSource.CUSTOMER, ErrorStep.INITIATION,
            RecoveryClass.INSTRUMENT_INVALID,
            "Card number failed validation at the issuer.", False),
        _fm("invalid_vpa", ErrorSource.CUSTOMER, ErrorStep.INITIATION,
            RecoveryClass.INSTRUMENT_INVALID,
            "The UPI VPA does not exist or is no longer active.", False),
        _fm("account_closed", ErrorSource.BANK, ErrorStep.AUTHORIZATION,
            RecoveryClass.INSTRUMENT_INVALID,
            "The underlying bank account is closed or frozen.", False),
        _fm("card_blocked_by_issuer", ErrorSource.ISSUER, ErrorStep.AUTHORIZATION,
            RecoveryClass.INSTRUMENT_INVALID,
            "Issuer has blocked the card for online use.", False),
        _fm("mandate_revoked", ErrorSource.CUSTOMER, ErrorStep.AUTHORIZATION,
            RecoveryClass.INSTRUMENT_INVALID,
            "The UPI Autopay / eNACH mandate was revoked by the payer.", False),

        # --- limits ---------------------------------------------------------
        _fm("transaction_limit_exceeded", ErrorSource.BANK, ErrorStep.AUTHORIZATION,
            RecoveryClass.LIMIT_BREACH,
            "Per-transaction ceiling on this instrument was exceeded.", True),
        _fm("daily_limit_exceeded", ErrorSource.BANK, ErrorStep.AUTHORIZATION,
            RecoveryClass.LIMIT_BREACH,
            "Payer's daily transaction limit was exhausted.", True),

        # --- infrastructure -------------------------------------------------
        _fm("issuer_down", ErrorSource.ISSUER, ErrorStep.AUTHORIZATION,
            RecoveryClass.INFRA_TRANSIENT,
            "Issuing bank was unavailable.", True),
        _fm("gateway_technical_error", ErrorSource.GATEWAY, ErrorStep.AUTHORIZATION,
            RecoveryClass.INFRA_TRANSIENT,
            "The acquiring gateway returned a technical error.", True),
        _fm("npci_unavailable", ErrorSource.NETWORK, ErrorStep.AUTHORIZATION,
            RecoveryClass.INFRA_TRANSIENT,
            "NPCI switch did not respond within the timeout.", True),
        _fm("bank_technical_decline", ErrorSource.BANK, ErrorStep.AUTHORIZATION,
            RecoveryClass.INFRA_TRANSIENT,
            "Bank returned a technical decline (NPCI 'TD' class).", True),
        _fm("network_error", ErrorSource.NETWORK, ErrorStep.INITIATION,
            RecoveryClass.INFRA_TRANSIENT,
            "Connection to the payer's app or bank dropped mid-flow.", True),

        # --- intent ---------------------------------------------------------
        _fm("payment_cancelled_by_user", ErrorSource.CUSTOMER, ErrorStep.AUTHENTICATION,
            RecoveryClass.INTENT_ABSENT,
            "Payer explicitly cancelled at the authentication screen.", True),
        _fm("checkout_abandoned", ErrorSource.CUSTOMER, ErrorStep.INITIATION,
            RecoveryClass.INTENT_ABSENT,
            "Payer left checkout without attempting a payment.", True),

        # --- risk -----------------------------------------------------------
        _fm("risk_threshold_exceeded", ErrorSource.RAZORPAY, ErrorStep.AUTHORIZATION,
            RecoveryClass.RISK_BLOCKED,
            "Blocked by risk engine. Requires human review.", True),
        _fm("suspected_fraud_issuer", ErrorSource.ISSUER, ErrorStep.AUTHORIZATION,
            RecoveryClass.RISK_BLOCKED,
            "Issuer flagged the transaction as suspected fraud.", True),
    ]
}


UNKNOWN_MODE = FailureMode(
    reason="unknown",
    source=ErrorSource.RAZORPAY,
    step=ErrorStep.AUTHORIZATION,
    recovery_class=RecoveryClass.UNKNOWN,
    description="Reason code not present in the Reversa ontology.",
    same_instrument_viable=True,
)


def classify(reason: str | None) -> FailureMode:
    """Map a Razorpay reason string to a failure mode.

    Unrecognised reasons return `UNKNOWN_MODE` rather than a best guess. The
    policy engine treats UNKNOWN as un-actionable, so a new reason code
    appearing in production degrades into an exception-list entry instead of a
    wrong automated money action.
    """
    if not reason:
        return UNKNOWN_MODE
    return FAILURE_MODES.get(reason.strip().lower(), UNKNOWN_MODE)
