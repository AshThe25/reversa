"""World physics — every constant that shapes the synthetic world, in one file.

Keeping these together so you can audit the data-generating process without
reading the generator, and see that I didn't tune anything to make Reversa look
clever.

Two rules I held myself to:

Nothing here is fitted. These are the *true* parameters. Reversa's estimator
never sees them; it re-learns what it can from the observable log and
evaluation_engine scores how close it got.

Nothing here is picked to flatter the product. Where a parameter makes the job
harder — infra failures mostly self-heal, retrying into a live outage has
negative uplift, contact fatigue is real — that's deliberate. A world where every
intervention helps makes the optimizer trivial and the whole thesis vacuous.
"""

from __future__ import annotations

from reversa.taxonomy import RecoveryClass

# ===========================================================================
# scale
# ===========================================================================

# The live era is a sale day: a mid-size Indian D2C merchant during a festival
# push. High volume is what makes a 19-minute rail degradation cost lakhs, and
# it is the regime where recovery decisions actually matter.
SCALE_PRESETS: dict[str, dict] = {
    "small":  {"customers": 1_200, "training_days": 14, "live_orders": 6_000},
    "demo":   {"customers": 4_000, "training_days": 28, "live_orders": 45_000},
    "large":  {"customers": 9_000, "training_days": 28, "live_orders": 90_000},
}
DEFAULT_SCALE = "demo"

TRAINING_ORDERS_PER_DAY_PER_1K_CUSTOMERS = 340


# ===========================================================================
# payment mix
# ===========================================================================

# Method share approximates the Indian online mix, where UPI dominates volume
# and cards dominate ticket size.
METHOD_SHARE: dict[str, float] = {
    "upi": 0.62,
    "card": 0.21,
    "netbanking": 0.10,
    "wallet": 0.07,
}

# Instruments per method, with share. Names are generic stand-ins for issuers
# and PSP handles; nothing here asserts anything about a real institution's
# reliability.
INSTRUMENTS: dict[str, dict[str, float]] = {
    "upi": {
        "okhdfcbank": 0.26, "oksbi": 0.22, "okicici": 0.16, "okaxis": 0.13,
        "paytm": 0.11, "ybl": 0.07, "okbizaxis": 0.05,
    },
    "card": {"VISA": 0.42, "MASTERCARD": 0.31, "RUPAY": 0.21, "AMEX": 0.06},
    "netbanking": {
        "HDFC": 0.24, "SBIN": 0.23, "ICIC": 0.18, "UTIB": 0.14,
        "KKBK": 0.11, "BARB": 0.10,
    },
    "wallet": {"paytm_wallet": 0.48, "phonepe_wallet": 0.31, "amazonpay": 0.21},
}

# Baseline per-method failure rates in normal operation. UPI's headline
# technical-decline rate is well under 1%, but *business* declines -- wrong
# PIN, insufficient balance, app timeouts -- push the observed end-to-end
# checkout failure rate far higher. These are end-to-end rates.
BASE_FAILURE_RATE: dict[str, float] = {
    "upi": 0.078,
    "card": 0.121,
    "netbanking": 0.147,
    "wallet": 0.064,
}

# Per-instrument multipliers on the base rate. Spread is intentional: a
# detector that only works when every instrument behaves identically is not a
# detector.
INSTRUMENT_FAILURE_MULTIPLIER: dict[str, float] = {
    "okhdfcbank": 0.94, "oksbi": 1.18, "okicici": 0.97, "okaxis": 1.05,
    "paytm": 1.02, "ybl": 1.11, "okbizaxis": 1.24,
    "VISA": 0.92, "MASTERCARD": 0.98, "RUPAY": 1.14, "AMEX": 1.31,
    "HDFC": 0.96, "SBIN": 1.22, "ICIC": 1.01, "UTIB": 1.07,
    "KKBK": 1.09, "BARB": 1.28,
    "paytm_wallet": 0.98, "phonepe_wallet": 0.95, "amazonpay": 1.06,
}

# Failure-reason mix per method in *normal* conditions. During an incident the
# generator overrides this with an incident-specific concentration, which is
# precisely the signal the error-concentration detector keys on.
NORMAL_REASON_MIX: dict[str, dict[str, float]] = {
    "upi": {
        "incorrect_upi_pin": 0.22, "payment_timeout": 0.19,
        "insufficient_funds": 0.20, "upi_app_not_responding": 0.12,
        "payment_cancelled_by_user": 0.10, "invalid_vpa": 0.06,
        "transaction_limit_exceeded": 0.05, "bank_technical_decline": 0.04,
        "risk_threshold_exceeded": 0.02,
    },
    "card": {
        "invalid_otp": 0.20, "insufficient_funds": 0.17,
        "3ds_authentication_failed": 0.15, "card_expired": 0.11,
        "incorrect_cvv": 0.09, "payment_cancelled_by_user": 0.09,
        "card_blocked_by_issuer": 0.07, "daily_limit_exceeded": 0.05,
        "gateway_technical_error": 0.04, "suspected_fraud_issuer": 0.03,
    },
    "netbanking": {
        "payment_timeout": 0.26, "insufficient_funds": 0.18,
        "bank_technical_decline": 0.16, "issuer_down": 0.12,
        "payment_cancelled_by_user": 0.11, "account_closed": 0.06,
        "daily_limit_exceeded": 0.06, "network_error": 0.05,
    },
    "wallet": {
        "insufficient_balance_wallet": 0.38, "payment_timeout": 0.19,
        "payment_cancelled_by_user": 0.16, "gateway_technical_error": 0.12,
        "transaction_limit_exceeded": 0.09, "network_error": 0.06,
    },
}


# ===========================================================================
# temporal structure
# ===========================================================================

# Share of a day's orders by IST hour. Two peaks: a lunch-break bump and a
# dominant 20:00-22:00 evening block, which is when Indian consumer checkout
# volume actually concentrates.
HOURLY_SHARE: tuple[float, ...] = (
    0.004, 0.002, 0.001, 0.001, 0.002, 0.006, 0.013, 0.023,
    0.033, 0.041, 0.047, 0.051, 0.055, 0.049, 0.042, 0.043,
    0.048, 0.057, 0.071, 0.082, 0.096, 0.098, 0.079, 0.056,
)

# Day-of-week multiplier, Monday=0. Weekends run hotter.
WEEKDAY_MULTIPLIER: tuple[float, ...] = (0.92, 0.95, 0.97, 1.01, 1.12, 1.24, 1.18)

# Failure rates rise at peak load and in the small hours (batch windows, bank
# maintenance). Multiplier on the base rate, by IST hour.
HOURLY_FAILURE_MULTIPLIER: tuple[float, ...] = (
    1.34, 1.41, 1.38, 1.29, 1.18, 1.05, 0.96, 0.92,
    0.90, 0.91, 0.93, 0.95, 0.98, 0.96, 0.94, 0.95,
    0.99, 1.04, 1.09, 1.14, 1.21, 1.19, 1.12, 1.26,
)


# ===========================================================================
# customers
# ===========================================================================

CUSTOMER_TIERS: dict[str, dict] = {
    # share, order-rate multiplier, ticket multiplier, base intent
    "new":     {"share": 0.34, "rate": 0.45, "ticket": 0.82, "intent": 0.44},
    "casual":  {"share": 0.37, "rate": 0.85, "ticket": 0.95, "intent": 0.55},
    "regular": {"share": 0.22, "rate": 1.90, "ticket": 1.14, "intent": 0.71},
    "vip":     {"share": 0.07, "rate": 3.60, "ticket": 2.35, "intent": 0.84},
}

# Order value: log-normal, in rupees, before tier multiplier.
TICKET_LOGNORMAL_MU = 7.45      # ~ Rs 1,720 median
TICKET_LOGNORMAL_SIGMA = 0.95
TICKET_MIN_PAISE = 9_900
TICKET_MAX_PAISE = 24_00_000

ORDER_CATEGORIES: dict[str, float] = {
    "apparel": 0.26, "electronics": 0.14, "grocery": 0.19, "beauty": 0.13,
    "home": 0.11, "subscription": 0.09, "travel": 0.05, "gifting": 0.03,
}
SUBSCRIPTION_CATEGORIES = frozenset({"subscription"})

# Latent trait distributions (Beta), never exposed to the estimator.
INTENT_CONCENTRATION = 9.0
LIQUIDITY_TIGHTNESS_BETA = (2.2, 4.4)
INSTRUMENT_STABILITY_BETA = (7.5, 1.9)
CHANNEL_RESPONSIVENESS_BETA = (2.8, 4.2)


# ===========================================================================
# natural recovery -- p_i(no intervention)
# ===========================================================================

# Base logit by failure class. The ordering here carries the product's central
# claim: infrastructure failures largely fix themselves, dead instruments
# never do. Intervening on the first group is waste; only a method switch
# helps the second.
NATURAL_RECOVERY_BASE_LOGIT: dict[str, float] = {
    RecoveryClass.INFRA_TRANSIENT.value:   1.15,   # ~0.76
    RecoveryClass.AUTH_FRICTION.value:    -0.30,   # ~0.43
    RecoveryClass.LIMIT_BREACH.value:     -0.55,   # ~0.37
    RecoveryClass.LIQUIDITY.value:        -1.35,   # ~0.21, time-dependent
    RecoveryClass.INTENT_ABSENT.value:    -2.60,   # ~0.07
    RecoveryClass.INSTRUMENT_INVALID.value: -3.00, # ~0.05
    RecoveryClass.RISK_BLOCKED.value:     -4.20,   # ~0.01
    RecoveryClass.UNKNOWN.value:          -1.00,
}

NATURAL_RECOVERY_COEF: dict[str, float] = {
    "intent": 1.65,
    "prior_recovery_rate": 1.10,
    "log_amount": -0.34,        # bigger tickets get reconsidered
    "is_subscription": 0.72,    # renewals retry themselves
    "vip": 0.38,
    "new_customer": -0.29,
    "evening": 0.24,            # a 20:00 failure is retried same-session
    "small_hours": -0.41,
}
NATURAL_RECOVERY_NOISE_SD = 0.42

# Liquidity recovers around payday: a bump centred on the customer's salary
# day, in logit space, decaying with distance in days.
SALARY_DAY_BONUS_LOGIT = 2.05
SALARY_DAY_DECAY_DAYS = 2.4

# Observation horizon. Recovery after this is not counted -- a merchant does
# not get to claim a payment recovered three weeks later.
RECOVERY_HORIZON_HOURS = 72.0

# Time-to-recovery, log-normal (mu, sigma) in hours, by class.
RECOVERY_DELAY_LOGNORMAL: dict[str, tuple[float, float]] = {
    RecoveryClass.INFRA_TRANSIENT.value:   (-0.90, 0.85),  # ~24 min median
    RecoveryClass.AUTH_FRICTION.value:     (-0.30, 1.05),  # ~44 min
    RecoveryClass.LIMIT_BREACH.value:      ( 2.35, 0.80),  # ~10.5 h, limits reset
    RecoveryClass.LIQUIDITY.value:         ( 2.90, 1.10),  # ~18 h, payday-anchored
    RecoveryClass.INTENT_ABSENT.value:     ( 1.70, 1.30),
    RecoveryClass.INSTRUMENT_INVALID.value:( 2.10, 1.20),
    RecoveryClass.RISK_BLOCKED.value:      ( 2.50, 1.00),
    RecoveryClass.UNKNOWN.value:           ( 1.50, 1.20),
}


# ===========================================================================
# intervention response -- the uplift Delta_i(a)
# ===========================================================================

# Base uplift in probability points, by (action, failure class). Read the
# columns, not the rows: the shape of this table is the product's argument.
#
#   * RETRY_NOW is NEGATIVE during an active incident (see
#     INCIDENT_RETRY_PENALTY) and only mildly positive otherwise -- a
#     re-presentment into a rail that just declined mostly burns an attempt.
#   * RETRY_DELAYED beats RETRY_NOW on infrastructure failures. This is the
#     result the Wind Tunnel is built to surface, and it falls out of the
#     world rather than being asserted by the UI.
#   * SWITCH_METHOD is the ONLY action with real uplift on a dead instrument.
#   * Nothing helps much on INFRA_TRANSIENT, because those customers mostly
#     recover on their own -- the uplift damping term below sees to that.
UPLIFT_BASE: dict[str, dict[str, float]] = {
    "retry_now": {
        RecoveryClass.INFRA_TRANSIENT.value:    0.04,
        RecoveryClass.AUTH_FRICTION.value:      0.11,
        RecoveryClass.LIMIT_BREACH.value:       0.02,
        RecoveryClass.LIQUIDITY.value:          0.01,
        RecoveryClass.INTENT_ABSENT.value:      0.02,
        RecoveryClass.INSTRUMENT_INVALID.value: 0.00,
    },
    "retry_delayed": {
        RecoveryClass.INFRA_TRANSIENT.value:    0.21,
        RecoveryClass.AUTH_FRICTION.value:      0.14,
        RecoveryClass.LIMIT_BREACH.value:       0.24,
        RecoveryClass.LIQUIDITY.value:          0.17,
        RecoveryClass.INTENT_ABSENT.value:      0.03,
        RecoveryClass.INSTRUMENT_INVALID.value: 0.00,
    },
    "switch_method": {
        RecoveryClass.INFRA_TRANSIENT.value:    0.29,
        RecoveryClass.AUTH_FRICTION.value:      0.16,
        RecoveryClass.LIMIT_BREACH.value:       0.22,
        RecoveryClass.LIQUIDITY.value:          0.04,
        RecoveryClass.INTENT_ABSENT.value:      0.03,
        RecoveryClass.INSTRUMENT_INVALID.value: 0.34,
    },
    "payment_link": {
        RecoveryClass.INFRA_TRANSIENT.value:    0.15,
        RecoveryClass.AUTH_FRICTION.value:      0.23,
        RecoveryClass.LIMIT_BREACH.value:       0.19,
        RecoveryClass.LIQUIDITY.value:          0.21,
        RecoveryClass.INTENT_ABSENT.value:      0.12,
        RecoveryClass.INSTRUMENT_INVALID.value: 0.27,
    },
    "nudge_sms": {
        RecoveryClass.INFRA_TRANSIENT.value:    0.06,
        RecoveryClass.AUTH_FRICTION.value:      0.12,
        RecoveryClass.LIMIT_BREACH.value:       0.10,
        RecoveryClass.LIQUIDITY.value:          0.13,
        RecoveryClass.INTENT_ABSENT.value:      0.07,
        RecoveryClass.INSTRUMENT_INVALID.value: 0.09,
    },
    "nudge_whatsapp": {
        RecoveryClass.INFRA_TRANSIENT.value:    0.08,
        RecoveryClass.AUTH_FRICTION.value:      0.17,
        RecoveryClass.LIMIT_BREACH.value:       0.14,
        RecoveryClass.LIQUIDITY.value:          0.18,
        RecoveryClass.INTENT_ABSENT.value:      0.10,
        RecoveryClass.INSTRUMENT_INVALID.value: 0.13,
    },
    "nudge_email": {
        RecoveryClass.INFRA_TRANSIENT.value:    0.03,
        RecoveryClass.AUTH_FRICTION.value:      0.06,
        RecoveryClass.LIMIT_BREACH.value:       0.07,
        RecoveryClass.LIQUIDITY.value:          0.08,
        RecoveryClass.INTENT_ABSENT.value:      0.05,
        RecoveryClass.INSTRUMENT_INVALID.value: 0.06,
    },
    "voice_call": {
        RecoveryClass.INFRA_TRANSIENT.value:    0.05,
        RecoveryClass.AUTH_FRICTION.value:      0.14,
        RecoveryClass.LIMIT_BREACH.value:       0.12,
        RecoveryClass.LIQUIDITY.value:          0.24,
        RecoveryClass.INTENT_ABSENT.value:      0.11,
        RecoveryClass.INSTRUMENT_INVALID.value: 0.16,
    },
}

ACTIONS_WITH_UPLIFT: tuple[str, ...] = tuple(UPLIFT_BASE.keys())

# Damping: uplift shrinks as natural recovery rises. Delta *= (1 - p_nat)^GAMMA.
# You cannot add much to a customer already at 0.8, and this single term is
# what makes "spray the whole cohort" lose to a targeted plan.
UPLIFT_DAMPING_GAMMA = 1.35

# Re-presenting into a rail that is still degraded is worse than waiting.
INCIDENT_RETRY_PENALTY = -0.18

# Payment links and nudges decay in effectiveness with hours since failure.
CONTACT_DECAY_TAU_HOURS: dict[str, float] = {
    "payment_link": 9.0,
    "nudge_sms": 6.5,
    "nudge_whatsapp": 8.0,
    "nudge_email": 14.0,
    "voice_call": 11.0,
}

# Contact fatigue. Multiplier on uplift by number of prior contacts to that
# customer in the trailing week; past three, further contact is counterproductive.
CONTACT_FATIGUE: tuple[float, ...] = (1.0, 0.78, 0.51, 0.22, -0.15, -0.35)

# Responsiveness trait scales contact-channel uplift (not retries).
RESPONSIVENESS_SCALE = 0.85

P_MAX = 0.98


# ===========================================================================
# intervention economics
# ===========================================================================

# Marginal cost per action, in paise. Voice is dominated by agent time.
ACTION_COST_PAISE: dict[str, int] = {
    "no_action": 0,
    "wait": 0,
    "retry_now": 0,
    "retry_delayed": 0,
    "switch_method": 0,
    "payment_link": 120,
    "nudge_sms": 25,
    "nudge_whatsapp": 85,
    "nudge_email": 3,
    "voice_call": 1_450,
    "human_review": 6_000,
}

# Friction imposed on the customer, arbitrary units, used for the Wind Tunnel's
# friction column. A silent retry is invisible; a phone call is not.
ACTION_FRICTION: dict[str, float] = {
    "no_action": 0.0, "wait": 0.0, "retry_now": 0.05, "retry_delayed": 0.05,
    "switch_method": 0.15, "payment_link": 0.35, "nudge_sms": 0.45,
    "nudge_whatsapp": 0.55, "nudge_email": 0.20, "voice_call": 1.00,
    "human_review": 0.10,
}

# Default per-incident intervention capacity. Payment links are scarce because
# Razorpay test mode caps a business at 30 -- a real constraint, kept real.
DEFAULT_CAPACITY: dict[str, int] = {
    "payment_link": 30,
    "nudge_sms": 400,
    "nudge_whatsapp": 250,
    "nudge_email": 2_000,
    "voice_call": 60,
    "retry_now": 2_500,
    "retry_delayed": 2_500,
    "switch_method": 1_200,
    "human_review": 50,
}


# ===========================================================================
# legacy policy (training era) -- makes uplift identifiable
# ===========================================================================

# The merchant's pre-Reversa rule, and the exploration rate layered on top.
# Without randomised exploration in the historical log, action assignment is a
# deterministic function of the covariates that also drive the outcome, and no
# honest uplift estimate is possible from observational data. This epsilon is
# the reason Reversa can learn anything at all on day one.
LEGACY_EXPLORATION_EPSILON = 0.15
LEGACY_LINK_THRESHOLD_PAISE = 2_00_000
LEGACY_COVERAGE = 0.72   # share of failures the legacy policy touched at all


# ===========================================================================
# incidents
# ===========================================================================

# Injected degradations. `reason_mix` overrides the normal mix inside the
# window, which is what produces the error-concentration signal.
INCIDENT_TEMPLATES: dict[str, dict] = {
    "psp_upi_degradation": {
        "label": "UPI PSP degradation",
        "method": "upi",
        "instruments": None,             # whole method
        "failure_multiplier": 5.4,
        "root_cause": "psp_switch_degradation",
        "reason_mix": {
            "bank_technical_decline": 0.44, "payment_timeout": 0.29,
            "upi_app_not_responding": 0.18, "network_error": 0.09,
        },
        "downtime_published": True,
        "severity": "critical",
    },
    "issuer_timeout_spike": {
        "label": "Issuer authorisation timeouts",
        "method": "card",
        "instruments": ("VISA", "MASTERCARD"),
        "failure_multiplier": 3.8,
        "root_cause": "issuer_authorisation_timeout",
        "reason_mix": {
            "3ds_authentication_failed": 0.41, "payment_timeout": 0.33,
            "gateway_technical_error": 0.16, "invalid_otp": 0.10,
        },
        "downtime_published": True,
        "severity": "high",
    },
    "single_bank_outage": {
        "label": "Bank netbanking outage",
        "method": "netbanking",
        "instruments": ("SBIN",),
        "failure_multiplier": 6.9,
        "root_cause": "bank_core_outage",
        "reason_mix": {"issuer_down": 0.58, "bank_technical_decline": 0.31,
                       "payment_timeout": 0.11},
        "downtime_published": True,
        "severity": "high",
    },
    # The ambiguous one. Deliberately built so evidence CANNOT settle the
    # question: the failure lift is real but modest, it is smeared across two
    # methods rather than concentrated, the error mix splits between a
    # merchant-side signature (timeouts) and an issuer-side one, and Razorpay
    # publishes no downtime. The investigator is expected to return
    # INSUFFICIENT EVIDENCE here, and automation must stay blocked.
    "ambiguous_latency": {
        "label": "Unattributed checkout latency",
        "method": None,
        "instruments": None,
        "failure_multiplier": 2.1,
        "root_cause": "AMBIGUOUS",
        "reason_mix": {
            "payment_timeout": 0.37, "gateway_technical_error": 0.21,
            "network_error": 0.19, "3ds_authentication_failed": 0.13,
            "bank_technical_decline": 0.10,
        },
        "downtime_published": False,
        "severity": "medium",
        "ambiguous": True,
    },
}

# Training-era incidents, so the detector has history to calibrate against and
# the evaluation harness has more than one positive to score.
TRAINING_INCIDENT_COUNT = 11
TRAINING_INCIDENT_DURATION_RANGE_MIN = (8, 46)
