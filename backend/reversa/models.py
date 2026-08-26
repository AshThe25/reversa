"""Domain model.

Roughly follows the pipeline: reality -> detection -> reasoning -> control ->
measurement -> audit.

One table needs care: GroundTruth is the simulator's answer key. Only
evaluation_engine is allowed to touch it. There's a test that walks the import
graph and fails the build if anything else does — I did not want that to rely on
me remembering.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reversa.db import Base

_TS = DateTime(timezone=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ===========================================================================
# enums
# ===========================================================================


class PaymentStatus(StrEnum):
    CREATED = "created"
    CAPTURED = "captured"
    FAILED = "failed"
    RECOVERED = "recovered"
    """Failed, then a later attempt succeeded. The outcome Reversa exists for."""
    ABANDONED = "abandoned"


class Method(StrEnum):
    UPI = "upi"
    CARD = "card"
    NETBANKING = "netbanking"
    WALLET = "wallet"


class ActionType(StrEnum):
    NO_ACTION = "no_action"
    RETRY_NOW = "retry_now"
    RETRY_DELAYED = "retry_delayed"
    SWITCH_METHOD = "switch_method"
    PAYMENT_LINK = "payment_link"
    NUDGE_SMS = "nudge_sms"
    NUDGE_WHATSAPP = "nudge_whatsapp"
    NUDGE_EMAIL = "nudge_email"
    VOICE_CALL = "voice_call"
    HUMAN_REVIEW = "human_review"
    WAIT = "wait"


class ActionResult(StrEnum):
    PLANNED = "planned"
    EXECUTED = "executed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPPRESSED = "suppressed"
    WITHHELD_HOLDOUT = "withheld_holdout"


class Arm(StrEnum):
    TREATMENT = "treatment"
    HOLDOUT = "holdout"


class IncidentSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(StrEnum):
    OPEN = "open"
    MITIGATING = "mitigating"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class RunEra(StrEnum):
    TRAINING = "training"
    LIVE = "live"


# ===========================================================================
# reality
# ===========================================================================


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(48))
    mcc: Mapped[str] = mapped_column(String(8), default="5399")
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class Customer(Base):
    """A payer, with the observable history the estimator is allowed to use.

    Latent traits that drive the simulator (liquidity tightness, true intent
    propensity) live in `GroundTruth`-adjacent simulator state, not here.
    Everything on this table is something a merchant genuinely knows.
    """

    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)

    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(20))
    city: Mapped[str] = mapped_column(String(60))
    language: Mapped[str] = mapped_column(String(12), default="en")
    tier: Mapped[str] = mapped_column(String(16), index=True)  # new|casual|regular|vip

    preferred_method: Mapped[str] = mapped_column(String(16))
    salary_day: Mapped[int] = mapped_column(Integer, default=1)

    # Consent, per channel. Default-off for intrusive channels.
    sms_consent: Mapped[bool] = mapped_column(Boolean, default=True)
    whatsapp_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    email_consent: Mapped[bool] = mapped_column(Boolean, default=True)
    voice_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    opted_out_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)

    # Realised history, maintained by the generator as the world advances.
    lifetime_orders: Mapped[int] = mapped_column(Integer, default=0)
    lifetime_value_paise: Mapped[int] = mapped_column(Integer, default=0)
    prior_failures: Mapped[int] = mapped_column(Integer, default=0)
    prior_natural_recoveries: Mapped[int] = mapped_column(Integer, default=0)
    prior_contacts: Mapped[int] = mapped_column(Integer, default=0)
    last_contacted_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)

    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)

    @property
    def prior_recovery_rate(self) -> float:
        """Observable recovery propensity. Falls back to a neutral prior."""
        if self.prior_failures < 2:
            return 0.42
        return self.prior_natural_recoveries / self.prior_failures

    def channel_consent(self, action: str) -> bool:
        return {
            ActionType.NUDGE_SMS: self.sms_consent,
            ActionType.NUDGE_WHATSAPP: self.whatsapp_consent,
            ActionType.NUDGE_EMAIL: self.email_consent,
            ActionType.VOICE_CALL: self.voice_consent,
            ActionType.PAYMENT_LINK: self.sms_consent or self.email_consent,
        }.get(action, True)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)

    amount_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    category: Mapped[str] = mapped_column(String(32))
    is_subscription: Mapped[bool] = mapped_column(Boolean, default=False)

    rzp_order_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    adapter_mode: Mapped[str] = mapped_column(String(20), default="simulation")
    """`razorpay_test` when this order exists in Razorpay, else `simulation`.
    Surfaced in the UI so no one mistakes a fixture for a live object."""

    created_at: Mapped[datetime] = mapped_column(_TS, index=True)


class Payment(Base):
    """One checkout intent. The unit of revenue that can be lost or recovered."""

    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)

    amount_paise: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(16), index=True)
    instrument: Mapped[str] = mapped_column(String(48), index=True)
    """Bank / issuer / wallet handle, e.g. `HDFC`, `okaxis`, `VISA`."""

    status: Mapped[str] = mapped_column(String(16), index=True)
    era: Mapped[str] = mapped_column(String(12), index=True)

    failure_reason: Mapped[str | None] = mapped_column(String(48), index=True)
    failure_class: Mapped[str | None] = mapped_column(String(32), index=True)
    error_source: Mapped[str | None] = mapped_column(String(24))
    error_step: Mapped[str | None] = mapped_column(String(32))

    incident_id: Mapped[str | None] = mapped_column(
        ForeignKey("incidents.id"), nullable=True, index=True
    )
    """Set by the *world* to mark true incident membership only when the
    generator also writes ground truth; the detector's own cohort membership
    lives on `RecoveryCandidate`, never here."""

    created_at: Mapped[datetime] = mapped_column(_TS, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    recovered_amount_paise: Mapped[int] = mapped_column(Integer, default=0)
    recovered_via: Mapped[str | None] = mapped_column(String(24), nullable=True)

    __table_args__ = (
        Index("ix_payment_stream", "created_at", "method", "instrument"),
        Index("ix_payment_status_era", "status", "era"),
    )


class PaymentAttempt(Base):
    """One presentment on the rails. A payment may have several."""

    __tablename__ = "payment_attempts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)

    method: Mapped[str] = mapped_column(String(16))
    instrument: Mapped[str] = mapped_column(String(48))
    succeeded: Mapped[bool] = mapped_column(Boolean, default=False)
    error_reason: Mapped[str | None] = mapped_column(String(48))

    origin: Mapped[str] = mapped_column(String(24), default="customer")
    """`customer` (self-retry), `legacy_policy`, `reversa`."""

    rzp_payment_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    adapter_mode: Mapped[str] = mapped_column(String(20), default="simulation")
    created_at: Mapped[datetime] = mapped_column(_TS, index=True)


class PaymentEvent(Base):
    """Append-only event stream over a payment's life."""

    __tablename__ = "payment_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(_TS, index=True)


class DowntimeRecord(Base):
    """Mirror of a Razorpay payment-downtime entity, or its simulated twin."""

    __tablename__ = "downtime_records"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    method: Mapped[str] = mapped_column(String(16))
    instrument: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(16))
    severity: Mapped[str] = mapped_column(String(16))
    scheduled: Mapped[bool] = mapped_column(Boolean, default=False)
    begin: Mapped[datetime] = mapped_column(_TS, index=True)
    end: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    adapter_mode: Mapped[str] = mapped_column(String(20), default="simulation")


class ComplianceEvent(Base):
    """Anything that must constrain future contact with a customer."""

    __tablename__ = "compliance_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    detail: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(_TS, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# ===========================================================================
# detection
# ===========================================================================


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))

    slice_method: Mapped[str | None] = mapped_column(String(16))
    slice_instrument: Mapped[str | None] = mapped_column(String(48))
    slice_key: Mapped[str] = mapped_column(String(96), index=True)

    detected_at: Mapped[datetime] = mapped_column(_TS, index=True)
    window_start: Mapped[datetime] = mapped_column(_TS)
    window_end: Mapped[datetime] = mapped_column(_TS)
    resolved_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default=IncidentStatus.OPEN, index=True)
    severity: Mapped[str] = mapped_column(String(16))

    baseline_success_rate: Mapped[float] = mapped_column(Float)
    observed_success_rate: Mapped[float] = mapped_column(Float)
    observed_volume: Mapped[int] = mapped_column(Integer)
    baseline_volume: Mapped[float] = mapped_column(Float)

    ewma_deviation: Mapped[float] = mapped_column(Float, default=0.0)
    p_value: Mapped[float] = mapped_column(Float)
    q_value: Mapped[float] = mapped_column(Float)
    """Benjamini-Hochberg adjusted. Hundreds of slices are tested per tick, so
    a raw p-value would be a false-discovery machine."""

    detection_rationale: Mapped[str] = mapped_column(Text, default="")

    rca_class: Mapped[str | None] = mapped_column(String(40))
    rca_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    rca_is_ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)

    revenue_exposed_paise: Mapped[int] = mapped_column(Integer, default=0)
    affected_payment_count: Mapped[int] = mapped_column(Integer, default=0)

    is_chaos_injected: Mapped[bool] = mapped_column(Boolean, default=False)


class IncidentEvidence(Base):
    """One addressable fact. Every AI claim must cite these by id."""

    __tablename__ = "incident_evidence"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)

    kind: Mapped[str] = mapped_column(String(40), index=True)
    # success_rate_drop | error_concentration | downtime_corroboration |
    # volume_anomaly | scope_containment | latency_shift | contradiction
    label: Mapped[str] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(48))
    """Where the fact came from: `payment_stream`, `razorpay_downtime_api`, ..."""

    observed_value: Mapped[float | None] = mapped_column(Float)
    baseline_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16), default="ratio")
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    supports: Mapped[str | None] = mapped_column(String(40))
    """Which root-cause hypothesis this points to."""
    contradicts: Mapped[str | None] = mapped_column(String(40))

    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    observed_at: Mapped[datetime] = mapped_column(_TS)


# ===========================================================================
# reasoning
# ===========================================================================


class Cohort(Base):
    """The set of payments an incident put at risk."""

    __tablename__ = "cohorts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    built_at: Mapped[datetime] = mapped_column(_TS)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    revenue_exposed_paise: Mapped[int] = mapped_column(Integer, default=0)
    inclusion_rule: Mapped[dict] = mapped_column(JSON, default=dict)


class RecoveryCandidate(Base):
    """A cohort member with its estimated counterfactuals. The optimizer's atom."""

    __tablename__ = "recovery_candidates"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    cohort_id: Mapped[str] = mapped_column(ForeignKey("cohorts.id"), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)

    amount_paise: Mapped[int] = mapped_column(Integer)
    failure_class: Mapped[str] = mapped_column(String(32), index=True)

    p_natural: Mapped[float] = mapped_column(Float)
    """Estimated P(recovery | no intervention). Never read from ground truth."""
    p_natural_lo: Mapped[float] = mapped_column(Float)
    p_natural_hi: Mapped[float] = mapped_column(Float)
    natural_evidence_n: Mapped[int] = mapped_column(Integer, default=0)

    uplift_by_action: Mapped[dict] = mapped_column(JSON, default=dict)
    """action -> {"delta": float, "p": float, "ev_paise": int, "n": int}"""

    eligible_actions: Mapped[list] = mapped_column(JSON, default=list)
    gate_report: Mapped[dict] = mapped_column(JSON, default=dict)

    best_action: Mapped[str | None] = mapped_column(String(24))
    best_action_ev_paise: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (UniqueConstraint("cohort_id", "payment_id"),)


class SimulationRun(Base):
    """One Wind Tunnel execution: a set of scenarios over one cohort."""

    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    cohort_id: Mapped[str] = mapped_column(ForeignKey("cohorts.id"), index=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(_TS, index=True)

    seed: Mapped[int] = mapped_column(Integer)
    capacity: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    compute_ms: Mapped[float] = mapped_column(Float, default=0.0)


class SimulationScenario(Base):
    """One branch of the Wind Tunnel. All figures are computed, never authored."""

    __tablename__ = "simulation_scenarios"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.id"), index=True)

    key: Mapped[str] = mapped_column(String(40), index=True)
    label: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")

    expected_recovery_paise: Mapped[int] = mapped_column(Integer, default=0)
    natural_recovery_paise: Mapped[int] = mapped_column(Integer, default=0)
    incremental_recovery_paise: Mapped[int] = mapped_column(Integer, default=0)

    action_count: Mapped[int] = mapped_column(Integer, default=0)
    action_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    capacity_used: Mapped[dict] = mapped_column(JSON, default=dict)
    capacity_exhausted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

    intervention_cost_paise: Mapped[int] = mapped_column(Integer, default=0)
    net_incremental_paise: Mapped[int] = mapped_column(Integer, default=0)
    customer_friction_score: Mapped[float] = mapped_column(Float, default=0.0)
    wasted_action_count: Mapped[int] = mapped_column(Integer, default=0)
    """Actions on candidates whose estimated natural recovery already exceeds
    the threshold -- money spent on people who would have paid anyway."""

    policy_violations: Mapped[int] = mapped_column(Integer, default=0)
    violation_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)

    assignment: Mapped[dict] = mapped_column(JSON, default=dict)
    """payment_id -> action. The plan this scenario would execute."""
    optimizer_status: Mapped[str | None] = mapped_column(String(32), nullable=True)


# ===========================================================================
# control
# ===========================================================================


class RecoveryPolicy(Base):
    __tablename__ = "recovery_policies"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1)

    source_text: Mapped[str] = mapped_column(Text, default="")
    """The merchant's natural language. Untrusted input; never executed."""
    compiled_by: Mapped[str] = mapped_column(String(16), default="llm")
    compile_warnings: Mapped[list] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    # draft | validated | deployed | rejected
    validation_report: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    deployed_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)

    rules: Mapped[list["PolicyRule"]] = relationship(
        back_populates="policy", order_by="PolicyRule.priority", cascade="all, delete-orphan"
    )


class PolicyRule(Base):
    """A compiled, deterministic rule. Structured -- never a code string."""

    __tablename__ = "policy_rules"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("recovery_policies.id"), index=True)

    priority: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(80))
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    """[{field, op, value}] over an allowlisted field vocabulary."""
    effect: Mapped[str] = mapped_column(String(24))
    # require_human_review | block | force_action | prefer_action | wait | allow
    effect_arg: Mapped[str | None] = mapped_column(String(32), nullable=True)

    source_span: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The merchant sentence this rule came from, for round-trip review."""

    policy: Mapped[RecoveryPolicy] = relationship(back_populates="rules")


class RecoveryStrategy(Base):
    """A named plan selected for execution against a cohort."""

    __tablename__ = "recovery_strategies"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    cohort_id: Mapped[str] = mapped_column(ForeignKey("cohorts.id"), index=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("simulation_scenarios.id"))
    policy_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    selected_at: Mapped[datetime] = mapped_column(_TS)
    selected_by: Mapped[str] = mapped_column(String(24), default="operator")
    rationale: Mapped[str] = mapped_column(Text, default="")


class RecoveryAction(Base):
    __tablename__ = "recovery_actions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    strategy_id: Mapped[str | None] = mapped_column(String(40), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    experiment_id: Mapped[str | None] = mapped_column(String(40), index=True)

    action_type: Mapped[str] = mapped_column(String(24), index=True)
    result: Mapped[str] = mapped_column(String(24), default=ActionResult.PLANNED, index=True)
    arm: Mapped[str] = mapped_column(String(12), index=True)

    scheduled_at: Mapped[datetime] = mapped_column(_TS, index=True)
    executed_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)

    expected_incremental_paise: Mapped[int] = mapped_column(Integer, default=0)
    p_natural_at_decision: Mapped[float] = mapped_column(Float, default=0.0)
    considered: Mapped[dict] = mapped_column(JSON, default=dict)
    """Full scored option set, so the road not taken is inspectable."""
    gate_verdicts: Mapped[dict] = mapped_column(JSON, default=dict)
    suppressed_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)

    cost_paise: Mapped[int] = mapped_column(Integer, default=0)
    message_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_template_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    adapter_mode: Mapped[str] = mapped_column(String(20), default="simulation")
    adapter_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)


# ===========================================================================
# measurement
# ===========================================================================


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    cohort_id: Mapped[str] = mapped_column(ForeignKey("cohorts.id"), index=True)
    strategy_id: Mapped[str | None] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(80))

    holdout_fraction: Mapped[float] = mapped_column(Float)
    assignment_method: Mapped[str] = mapped_column(
        String(48), default="sha256(experiment_id||customer_id)"
    )
    started_at: Mapped[datetime] = mapped_column(_TS)
    concluded_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)

    results: Mapped[dict] = mapped_column(JSON, default=dict)
    """Computed by `experiment_engine`; every field traceable to counts."""


class ExperimentAssignment(Base):
    __tablename__ = "experiment_assignments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)

    arm: Mapped[str] = mapped_column(String(12), index=True)
    assignment_hash: Mapped[str] = mapped_column(String(16))
    """First 16 hex of the digest, so assignment is reproducible by hand."""
    assigned_at: Mapped[datetime] = mapped_column(_TS)

    __table_args__ = (UniqueConstraint("experiment_id", "payment_id"),)


class RecoveryOutcome(Base):
    """What actually happened to one payment. The dependent variable."""

    __tablename__ = "recovery_outcomes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    experiment_id: Mapped[str | None] = mapped_column(String(40), index=True)
    arm: Mapped[str] = mapped_column(String(12), index=True)

    recovered: Mapped[bool] = mapped_column(Boolean, index=True)
    amount_paise: Mapped[int] = mapped_column(Integer)
    recovered_amount_paise: Mapped[int] = mapped_column(Integer, default=0)
    recovered_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    hours_to_recovery: Mapped[float | None] = mapped_column(Float, nullable=True)

    action_type: Mapped[str | None] = mapped_column(String(24), index=True)
    action_cost_paise: Mapped[int] = mapped_column(Integer, default=0)
    observed_at: Mapped[datetime] = mapped_column(_TS)


class AIInvestigation(Base):
    """A stored, schema-validated LLM output. Never trusted with arithmetic."""

    __tablename__ = "ai_investigations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[str] = mapped_column(String(40), index=True)
    capability: Mapped[str] = mapped_column(String(40), index=True)
    # incident_investigator | recovery_strategist | policy_compiler | explainer

    model: Mapped[str] = mapped_column(String(48))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)

    raw_output: Mapped[str] = mapped_column(Text, default="")
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)
    schema_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    groundedness: Mapped[float] = mapped_column(Float, default=0.0)
    """Share of factual claims whose cited evidence ids actually exist."""

    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    insufficient_evidence: Mapped[bool] = mapped_column(Boolean, default=False)

    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_micro_usd: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str] = mapped_column(String(24), default="anthropic")
    created_at: Mapped[datetime] = mapped_column(_TS, index=True)


class EvaluationRun(Base):
    """Scores the system against the world's hidden answer key."""

    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(_TS, index=True)
    world_seed: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")


class AuditEvent(Base):
    """Append-only, hash-chained record of every decision and money action."""

    __tablename__ = "audit_events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(40), unique=True)
    occurred_at: Mapped[datetime] = mapped_column(_TS, index=True)
    actor: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    subject_type: Mapped[str] = mapped_column(String(24))
    subject_id: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64))


class WorldMeta(Base):
    """Parameters and seed of the generated world, for reproducibility."""

    __tablename__ = "world_meta"

    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


# ===========================================================================
# HIDDEN GROUND TRUTH -- answer key. Import only from evaluation_engine.
# ===========================================================================


class GroundTruth(Base):
    """The simulator's hidden state for one payment.

    THIS TABLE IS THE ANSWER KEY. Reading it from any engine other than
    `evaluation_engine` invalidates every metric this project reports, so the
    import is enforced by test rather than left to discipline.
    """

    __tablename__ = "ground_truth"

    payment_id: Mapped[str] = mapped_column(
        ForeignKey("payments.id"), primary_key=True
    )

    true_incident_id: Mapped[str | None] = mapped_column(String(40), index=True)
    true_root_cause: Mapped[str] = mapped_column(String(40), index=True)
    true_failure_class: Mapped[str] = mapped_column(String(32))

    resolve_u: Mapped[float] = mapped_column(Float)
    """The latent uniform U_i. Thresholded to produce every potential outcome."""

    true_p_natural: Mapped[float] = mapped_column(Float)
    true_p_by_action: Mapped[dict] = mapped_column(JSON, default=dict)
    true_uplift_by_action: Mapped[dict] = mapped_column(JSON, default=dict)
    true_best_action: Mapped[str] = mapped_column(String(24))
    true_best_action_uplift: Mapped[float] = mapped_column(Float, default=0.0)

    recovers_naturally: Mapped[bool] = mapped_column(Boolean, index=True)
    """Y_i(no intervention) = 1[U_i < p_natural]."""
    natural_recovery_hours: Mapped[float | None] = mapped_column(Float, nullable=True)

    realised_action: Mapped[str | None] = mapped_column(String(24))
    realised_recovered: Mapped[bool | None] = mapped_column(Boolean)
    realised_incremental: Mapped[bool | None] = mapped_column(Boolean)
    """True iff the realised action moved this payment across the U threshold."""

    is_incident_member: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
