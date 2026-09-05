/** Shapes returned by the Reversa API. Kept in one place so a backend rename
 *  breaks the typecheck rather than a screen at demo time. */

export interface SessionInfo {
  subject: string;
  scopes: string[];
  session_id: string;
  expires_at: number;
  expires_in: number;
}

export interface AuthResponse {
  token: string;
  session: SessionInfo;
  role: "demo" | "operator";
}

export interface Overview {
  as_of: string;
  revenue_at_risk_paise: number;
  live_failed_payments: number;
  live_failed_amount_paise: number;
  natural_recovery_paise: number;
  incremental_recovery_paise: number;
  active_incidents: number;
  total_incidents: number;
  experiments_concluded: number;
  capacity: { used: number; total: number; by_action: Record<string, number> };
  detector: Record<string, unknown>;
}

export interface Incident {
  id: string;
  label: string;
  slice: string;
  method: string | null;
  instrument: string | null;
  severity: "low" | "medium" | "high" | "critical";
  status: string;
  detected_at: string;
  window_start: string;
  window_end: string;
  resolved_at: string | null;
  baseline_success_rate: number;
  observed_success_rate: number;
  observed_volume: number;
  affected_payment_count: number;
  revenue_exposed_paise: number;
  p_value: number;
  q_value: number;
  detection_rationale: string;
  ambiguous: boolean;
  rca_class: string | null;
  rca_confidence: number;
  rca_evidence: { diffuse_members?: string[] } & Record<string, unknown>;
}

export interface IncidentSignal {
  at: string;
  window_minutes: number;
  n: number;
  success_rate: number;
  baseline_rate: number;
  q_value: number;
  top_reason: string | null;
  top_reason_share: number;
  rolled_up_from: string[];
}

export interface FailureMixRow {
  reason: string | null;
  failure_class: string | null;
  count: number;
  amount_paise: number;
}

export interface IncidentDetail extends Incident {
  signals: IncidentSignal[];
  failure_mix: FailureMixRow[];
}

export interface UpliftCell {
  delta: number;
  credible: boolean;
  ev_paise: number;
}

export interface CandidateRow {
  payment_id: string;
  customer_id: string;
  amount_paise: number;
  failure_class: string;
  method: string;
  p_natural: number;
  confidence: number;
  eligible: string[];
  uplift: Record<string, UpliftCell>;
  would_recover_anyway: boolean;
}

export interface CohortException {
  payment_id: string;
  amount_paise: number;
  reason: string;
  detail: string;
}

export interface Cohort {
  incident_id: string;
  slice: string;
  window_start: string;
  window_end: string;
  in_window_payments: number;
  member_count: number;
  attribution_weight: number;
  rail_down_now: boolean;
  revenue_exposed_paise: number;
  attributable_exposure_paise: number;
  natural_recovery_paise: number;
  addressable_paise: number;
  exceptions: number;
  exceptions_by_reason: Record<string, number>;
  build_ms: number;
  exception_sample: CohortException[];
  candidates: CandidateRow[];
}

export interface CapacityCell {
  used: number;
  limit: number;
  exhausted: boolean;
}

export interface Scenario {
  key: string;
  label: string;
  description: string;
  natural_recovery_paise: number;
  gross_recovery_paise: number;
  incremental_recovery_paise: number;
  action_count: number;
  by_action: Record<string, number>;
  capacity_used: Record<string, CapacityCell>;
  exhausted: string[];
  cost_paise: number;
  net_incremental_paise: number;
  friction: number;
  wasted_actions: number;
  contacted_customers: number;
  confidence: number;
  risk_score: number;
  policy_violations: number;
  violation_detail: { count: number; sample: { payment_id: string; action: string }[] };
  cost_per_incremental_rupee: number | null;
  solver: string;
  solve_ms: number;
  notes: string[];
}

export interface WindTunnel {
  incident_id: string;
  cohort: Omit<Cohort, "candidates" | "exception_sample" | "incident_id">;
  candidate_count: number;
  capacity: Record<string, number>;
  total_ms: number;
  best_scenario: string;
  scenarios: Scenario[];
  stages?: RunStage[];
}

export interface ArmResult {
  arm: string;
  customers: number;
  payments: number;
  recovered: number;
  exposure_paise: number;
  recovered_paise: number;
  cost_paise: number;
  recovery_rate: number;
  revenue_rate: number;
}

export interface ExperimentResult {
  experiment_id: string;
  arms: Record<string, ArmResult>;
  gross_recovery_paise: number;
  natural_recovery_paise: number;
  incremental_paise: number;
  incremental_lo_paise: number;
  incremental_hi_paise: number;
  rate_lift: number;
  rate_lift_lo: number;
  rate_lift_hi: number;
  significant: boolean;
  rate_significant: boolean;
  concentrated: boolean;
  cost_paise: number;
  net_paise: number;
  roi: number | null;
  measurement_cost_paise: number;
  mde_rate: number;
  required_holdout: number;
  underpowered: boolean;
  bootstrap_samples: number;
  confidence: number;
  compute_ms: number;
  warnings: string[];
}

export interface ExecutionReport {
  experiment_id: string;
  strategy_id: string;
  scenario_key: string;
  arms: Record<string, number>;
  actions_executed: number;
  projected_incremental_paise: number;
  balance: Record<string, { payments: number; exposure_paise: number; mean_paise: number; median_paise: number } | { mean_ticket_ratio: number; balanced: boolean }>;
  result: ExperimentResult;
}

export interface AuditEntry {
  seq: number;
  id: string;
  at: string;
  actor: string;
  event_type: string;
  subject_type: string;
  subject_id: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  entry_hash: string;
}

export interface ChainVerdict {
  valid: boolean;
  entries_checked: number;
  head_hash: string;
  broken_at_seq: number | null;
  reason: string | null;
}

export interface SystemInfo {
  adapters: {
    razorpay: {
      mode: string;
      live_calls: number;
      payment_link_budget: { limit: number; used: number; remaining: number };
      /** The most recent Payment Link this process created, if any. */
      last_payment_link?: {
        id: string;
        short_url: string;
        amount_paise: number;
        status: string;
      } | null;
      note: string;
    };
    llm: { mode: string; model: string | null };
  };
  world: Record<string, unknown> | null;
  engine: {
    fit_ms: number;
    scan_ms: number;
    incidents_detected: number;
    detector: Record<string, unknown>;
    estimator: Record<string, unknown> | null;
  };
  capacity_defaults: Record<string, number>;
}

export interface ChaosResult {
  incident_id: string;
  volume_multiplier: number;
  capacity_multiplier: number;
  candidates: number;
  baseline: Scenario;
  stressed: Scenario;
  exhaustion_minutes: Record<string, number | null>;
  capacity: Record<string, number>;
}

// --- policies ---------------------------------------------------------------

export interface PolicyCondition {
  field: string;
  op: string;
  value: unknown;
}

export interface PolicyRule {
  priority: number;
  label: string;
  conditions: PolicyCondition[];
  effect: string;
  effect_arg: string | null;
  source_span: string | null;
  describe: string;
}

export interface CompiledPolicy {
  name: string;
  compiled_by: string;
  source_text: string;
  warnings: string[];
  rules: PolicyRule[];
}

export interface PolicyValidation {
  ok: boolean;
  errors: string[];
  warnings: string[];
  rules_checked: number;
  unreachable: string[];
}

export interface PolicyResponse {
  policy: CompiledPolicy;
  path: "llm" | "deterministic";
  injection_signals: string[];
  validation: PolicyValidation;
  llm: Record<string, unknown> | null;
  run?: WindTunnel | null;
}

export interface PolicyCapabilities {
  can: string[];
  cannot: string[];
  tunable_basis: string[];
  fields: string[];
  effects: string[];
}

// --- evaluation -------------------------------------------------------------

export interface DetectionScore {
  true_incidents: number;
  detected: number;
  matched: number;
  missed: string[];
  false_alarms: number;
  recall: number;
  precision: number;
  median_latency_min: number | null;
  latencies_min: number[];
}

export interface CalibrationBin {
  bin_lo: number;
  bin_hi: number;
  n: number;
  predicted: number;
  actual: number;
}

export interface EvaluationExperiment {
  experiment_id: string;
  measurement: {
    estimated_paise: number;
    estimated_lo_paise: number;
    estimated_hi_paise: number;
    true_paise: number;
    treated_payments: number;
    interval_contains_truth: boolean;
    relative_error: number | null;
  };
  calibration: {
    n: number;
    brier: number;
    expected_calibration_error: number;
    mean_predicted: number;
    mean_actual: number;
    bias: number;
    bins: CalibrationBin[];
  } | null;
  decisions: {
    decisions: number;
    top1_accuracy: number;
    chose_positive_uplift_rate: number;
    chose_harmful: number;
    flagged_wasteful: number;
    truly_ineffective: number;
    effective_rate: number;
    mean_regret_uplift_points: number;
    note: string;
  };
  cohort: { members: number; true_incident_members?: number; precision: number | null; note?: string };
}

export interface Evaluation {
  generated_at: string;
  detection: DetectionScore;
  downtime_feed?: DowntimeFeedComparison;
  experiments: EvaluationExperiment[];
  compute_ms: number;
  method_note: string;
}

// --- investigation ----------------------------------------------------------

export interface EvidenceItem {
  id: string;
  kind: string;
  label: string;
  source: string;
  observed: number | null;
  baseline: number | null;
  unit: string;
  sample_size: number;
  confidence: number;
  supports: string | null;
  contradicts: string | null;
  detail: Record<string, unknown>;
}

export interface Investigation {
  incident_id: string;
  root_cause: string;
  root_cause_label: string;
  hypothesis: string;
  confidence: number;
  supporting_evidence: string[];
  contradicting_evidence: string[];
  recommended_next_step: string;
  requires_human_review: boolean;
  insufficient_evidence: boolean;
  actionable: boolean;
  produced_by: "llm" | "deterministic";
  groundedness: number;
  latency_ms: number;
  cost_micro_usd: number;
  validation_errors: string[];
  evidence: EvidenceItem[];
  trace: AgentTrace;
}

/** One question the agent asked, and what came back. */
export interface AgentStep {
  n: number;
  tool: string;
  asks: string;
  rationale: string;
  returned: string[];
  finding: string;
}

export interface AgentTrace {
  steps: AgentStep[];
  budget: number;
  asked: number;
  skipped: string[];
  stopped_because: string;
  produced_by: string;
  latency_ms: number;
}

/** One proposed action awaiting - or not requiring - a human decision. */
export interface ReviewCase {
  payment_id: string;
  customer_id: string;
  action: string;
  amount_paise: number;
  expected_incremental_paise: number;
  baseline_recovery_probability: number;
  decision: "pending" | "approved" | "rejected" | "auto_approved";
  decided_by: string | null;
  note: string | null;
  reason: string;
  needs_human: boolean;
  explanation: string;
}

export interface ReviewQueue {
  incident_id: string;
  cause_resolved: boolean;
  root_cause: string;
  summary: {
    total: number;
    pending: number;
    auto_approved: number;
    pending_value_paise: number;
    auto_value_paise: number;
    by_reason: Record<string, number>;
  };
  cases: ReviewCase[];
  thresholds: { high_value_paise: number };
}

/** How far ahead of the platform's downtime feed the detector was. */
export interface DowntimeFeedComparison {
  incidents_compared: number;
  feed_published: number;
  feed_never_published: number;
  median_lead_minutes: number | null;
  ahead_of_feed: number;
  per_incident: {
    template: string;
    lead_minutes: number | null;
    feed_published: boolean;
  }[];
}

/** What the wind tunnel did, and how long each part actually took. */
export interface RunStage {
  label: string;
  note: string;
  ms: number;
}
