# DOMAIN_MODEL.md

26 tables, grouped by where they sit in the pipeline. Money is integer paise
everywhere — no floats touch a rupee figure at any point.

## Reality — what a merchant integration can observe

| Table | Notes |
|---|---|
| `merchants` | One, for the demo. |
| `customers` | Consent per channel, and realised history carried forward: `prior_failures`, `prior_recoveries`, `prior_contacts`. Latent traits live in the simulator, never here. |
| `orders`, `payments` | `payments` is the unit of recoverable revenue. `status` is `captured` / `failed` / `recovered`. |
| `payment_attempts` | One row per presentment. `origin` distinguishes a customer self-retry from a policy action. |
| `payment_events` | Append-only stream. Recovery actions are logged whether or not they worked — without the failures, uplift is unidentifiable. |
| `downtime_records` | Mirror of the Razorpay downtime entity, published late and not for every incident. |
| `compliance_events` | Opt-outs, complaints, disputes. Anything that must constrain future contact. |

## Detection

| Table | Notes |
|---|---|
| `incidents` | Detector output. Carries `q_value` (BH-adjusted), the rationale in full, and `rca_is_ambiguous` for degradations with no containable scope. |
| `incident_evidence` | Addressable facts. Every AI claim must cite these by id. |

## Reasoning

| Table | Notes |
|---|---|
| `cohorts` | The set an incident put at risk, with its inclusion rule and attribution weight. |
| `recovery_candidates` | The optimiser's atom: estimated `p_natural` with bounds, uplift per action, eligible actions, and the gate report. |
| `simulation_runs`, `simulation_scenarios` | One wind tunnel execution and its branches. Natural, gross and incremental are three separate columns, deliberately. |

## Control

| Table | Notes |
|---|---|
| `recovery_policies`, `policy_rules` | Compiled rules as structured data — conditions over an allowlisted vocabulary, never a code string. |
| `recovery_strategies` | The plan selected for execution. |
| `recovery_actions` | Every action, including the ones withheld from the holdout. Carries `considered` (the full scored option set) and `gate_verdicts`, so the road not taken is inspectable. |

## Measurement

| Table | Notes |
|---|---|
| `experiments`, `experiment_assignments` | `assignment_hash` is stored so an auditor can recompute an arm by hand. |
| `recovery_outcomes` | The dependent variable. |
| `ai_investigations` | Stored model outputs with schema validity, groundedness, latency and cost. |
| `evaluation_runs` | Scores against ground truth. |
| `audit_events` | Hash-chained. `prev_hash` is unique, which makes a concurrent fork a failed insert rather than a silent branch. |

## The answer key

`ground_truth` holds each failed payment's latent resolve `U`, its true natural
recovery probability, its true probability under every action, and whether the
realised action moved it across the threshold.

**Only `evaluation_engine` and `world/` may read it.**
`tests/test_ground_truth_isolation.py` walks the AST of every other module under
`reversa/` and fails the build if any of them so much as names it. Without that
boundary every metric the product reports would be circular.
