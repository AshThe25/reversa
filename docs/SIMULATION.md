# SIMULATION.md — the generative world and the counterfactual model

This is the most important document in the repository. Every revenue number
Reversa displays is derived from the model specified here, and the honesty of
the product rests on the boundary this document draws between:

- **the world** — a generative simulator that holds *hidden ground truth*, and
- **the system** — Reversa, which sees only what a real merchant integration
  would see and must *estimate* everything else.

If those two ever touch, the evaluation numbers become meaningless. The
separation is enforced structurally (§5), not by convention.

---

## 1. Why a simulator at all

Reversa's central claim is causal: *this intervention produced this much
incremental revenue*. Causal claims need counterfactuals, and in the real world
a counterfactual is unobservable — you cannot both contact a customer and not
contact them.

Two mechanisms give us counterfactuals here, and they check each other:

1. **A randomized holdout.** This is what a real merchant would run, and it is
   what Reversa reports as its headline number. It yields an *estimate* with a
   confidence interval.
2. **The simulator's hidden ground truth.** Because we generated the world, we
   know each payment's true potential outcomes. This yields the *exact* answer.

The evaluation harness compares (1) against (2). A holdout estimate whose
confidence interval contains the true incremental revenue is evidence that the
experiment design is sound. This is the strongest honesty check in the project:
we do not merely claim our measurement works, we test the measurement itself
against a known answer.

---

## 2. Potential outcomes: the core formalism

For each failed payment `i` we define binary potential outcomes:

```
Y_i(a) = 1  if the payment is eventually recovered when intervention a is applied
         0  otherwise
```

where `a = ∅` denotes *no intervention*.

The world draws, for each payment, a single latent uniform:

```
U_i ~ Uniform(0, 1)          # the customer's "resolve", fixed across futures
```

and a set of true recovery probabilities `p_i(a)` — one per candidate
intervention, plus `p_i(∅)` for the do-nothing baseline. The outcome is then

```
Y_i(a) = 1[ U_i < p_i(a) ]
```

**This single shared `U_i` is the whole trick.** Because the same draw is
thresholded for every intervention, the model is a *monotone single-index
potential-outcomes model*, which has three properties we need:

- **No defiers.** If `p_i(a) ≥ p_i(∅)`, then `Y_i(a) ≥ Y_i(∅)` pointwise. An
  intervention never *causes* a customer who would have paid to not pay.
- **Redundancy is explicit.** If `U_i < p_i(∅)`, the customer recovers on their
  own and the intervention changes nothing — it is pure waste. The individual
  treatment effect is
  ```
  τ_i(a) = Y_i(a) − Y_i(∅) = 1[ p_i(∅) ≤ U_i < p_i(a) ]
  ```
  Non-zero only in the band between the two probabilities. This is the
  mathematical statement of the product's central business insight: **the
  customers worth intervening on are the ones in the band, not the ones with
  the biggest invoices.**
- **Ground truth is exactly computable.** True incremental revenue over any set
  of assignments is `Σ_i amount_i · τ_i(a_i)`, with no sampling error at all.

### Correlated futures, not independent coin flips

A naive simulator would re-roll a random number for every scenario. That would
be wrong and it would flatter us: it would make every intervention look like it
adds independent probability mass, and "retry everyone" would always win.
Fixing `U_i` across all counterfactual branches is what makes the Wind Tunnel's
comparisons meaningful — the same customers are being helped or wasted on in
every branch.

---

## 3. How the world computes `p_i(a)`

`p_i(∅)` (natural recovery) and `p_i(a)` (with intervention) are built from
interpretable factors. Nothing here is fitted; this *is* the data-generating
process.

### 3.1 Natural recovery

```
logit p_i(∅) = β_class[failure_class]        # dominant term
             + β_intent · intent_i            # customer resolve
             + β_hist  · prior_recovery_rate_i
             + β_amt   · f_amount(amount_i)
             + β_sub   · is_subscription_i
             + β_tod   · f_time_of_day(t_i)
             + ε_i
```

Sign and magnitude of each term is grounded in how the failure classes actually
behave:

| Failure class | Natural recovery | Why |
|---|---|---|
| `INFRA_TRANSIENT` | **high** (~0.55–0.75) | Nothing is wrong with the customer. They retry in minutes and it works. Intervening here is mostly waste — the single most important fact the optimizer must learn. |
| `AUTH_FRICTION` | moderate (~0.35–0.50) | Customer was present and willing; they often just try again. |
| `LIQUIDITY` | low now, **time-dependent** | Recovers sharply around the customer's salary day. Timing is the whole intervention. |
| `INSTRUMENT_INVALID` | **very low** (~0.05) | The instrument is dead. Only a method switch can work. |
| `LIMIT_BREACH` | moderate, next-day | Limits reset. |
| `INTENT_ABSENT` | **very low** (~0.08) | They chose not to buy. |
| `RISK_BLOCKED` | ~0 | Blocked by design. |

`f_amount` is decreasing: large amounts are reconsidered, small ones are
re-attempted casually. `f_time_of_day` encodes that a 02:00 failure has a lower
same-session retry rate than an 19:00 one.

### 3.2 Intervention response

```
p_i(a) = clip( p_i(∅) + Δ_i(a), 0, 0.98 )
```

`Δ_i(a)` is the *true uplift*, and it is deliberately non-uniform across the
population — a flat uplift would make the optimizer trivial and the product
pointless. Key structure:

- **Uplift shrinks as `p_i(∅)` rises.** Modelled as
  `Δ_i(a) = δ_base(a, class) · (1 − p_i(∅))^γ`. You cannot add much to someone
  already at 0.8. This is what makes "target the high-natural-recovery
  customers" actively bad.
- **`RETRY_NOW` during an active incident has *negative* base uplift.** The rail
  is still down; re-presenting burns the attempt and can harden a decline. This
  is why `RETRY_+15M` beats `RETRY_NOW` in the demo, and it comes out of the
  world model rather than being asserted.
- **`SWITCH_METHOD` is the only action with positive uplift on
  `INSTRUMENT_INVALID`.** Retries there are structurally worthless.
- **`PAYMENT_LINK` uplift decays with delay** from the failure (`exp(-t/τ_a)`),
  strongly for impulse categories.
- **Contact fatigue.** Each prior contact to the same customer multiplies
  subsequent uplift by `φ < 1`, and past a threshold turns it negative
  (annoyance). Capacity is not the only reason to send fewer messages.

### 3.3 Time-to-recovery

Recovery is not instantaneous. Conditional on `Y_i(a) = 1`, the delay is drawn
from a class-specific distribution (log-normal for `AUTH_FRICTION`, a
salary-day-anchored spike for `LIQUIDITY`). This drives the autopsy timeline
and makes "did we recover it *before the deadline*" a real question.

---

## 4. Temporal and behavioural coherence

Rows are **not** independent draws. The generator runs a customer-level process:

- Each customer has persistent latent traits: `intent_propensity`,
  `instrument_stability`, `liquidity_tightness`, `channel_responsiveness`,
  `salary_day`, `preferred_method`.
- A customer's order stream is a thinned Poisson process with their own rate,
  modulated by a global daily/weekly seasonality curve.
- **Failure probability depends on history**: a customer whose card is drifting
  toward expiry accumulates `INSTRUMENT_INVALID` risk; a liquidity-tight
  customer fails more as the month progresses and recovers on salary day.
- **`prior_recovery_rate_i` is computed from that customer's own realised
  history**, so the feature the estimator later uses is genuinely predictive
  rather than noise.

### The two eras

| Era | Span | Purpose |
|---|---|---|
| **Training era** | days `-28 … -1` | A *legacy* recovery policy runs: a crude "retry everything once, link if over ₹2,000" rule, **with ε = 0.15 random exploration** over actions. |
| **Live era** | day `0` | Demo day. Incidents fire; Reversa operates. |

The exploration in the training era is not decoration — it is what makes uplift
**identifiable**. Under a purely deterministic legacy policy, action assignment
would be a function of the same covariates that drive the outcome, and no
honest uplift estimate would be possible from observational data. The ε-greedy
legacy policy is exactly how a real merchant's historical log would need to look
for this product to work on day one, and saying so is part of the pitch.

---

## 5. The estimator: what Reversa is actually allowed to see

Reversa's `counterfactual_engine` **never reads** `U_i`, `p_i(∅)`, `p_i(a)`,
`τ_i`, or any `true_*` column. Enforcement is structural:

- Ground truth lives in a separate table, `GroundTruth`, keyed by payment id.
- No domain service imports it. The **only** module permitted to is
  `engines/evaluation_engine.py`.
- `tests/test_ground_truth_isolation.py` walks the import graph and fails the
  build if any other module reaches it.

### What it estimates from, and how

The estimator is a **hierarchical empirical-Bayes rate model** — Beta-Binomial
cells with shrinkage toward progressively coarser parents:

```
cell:    (recovery_class, method, amount_bucket, customer_tier, incident_state)
parent:  (recovery_class, method, amount_bucket)
grand:   (recovery_class)
```

For a cell with `s` successes out of `n` historical failures:

```
p̂ = (s + κ · p̂_parent) / (n + κ)
```

with `κ` the shrinkage strength. Uncertainty is the Beta posterior interval.

This is chosen over a black-box learner deliberately, on three grounds:

1. **Explainability is a product requirement, not a nicety.** Every estimate
   traces to "412 comparable historical failures in this cell, shrunk toward a
   parent of 3,880." The Evidence Graph can render that. A gradient-boosted
   score cannot be defended to a merchant who is about to spend contact capacity
   on it.
2. **Calibration over discrimination.** The optimizer needs `p̂` to be *right in
   level*, not merely well-ranked — it subtracts two probabilities. Rate models
   with shrinkage are calibrated by construction; margin-trained classifiers
   are not.
3. **It degrades honestly.** A cell with `n = 3` returns a wide posterior, the
   optimizer sees low confidence, and the policy gate can refuse to act. A
   neural model returns 0.83 with the same confident face either way.

Uplift `Δ̂(a)` is estimated the same way, on the training era's ε-explored
actions, as the difference between the treated and untreated cell rates.

### Calibration is reported, not assumed

`EVALUATION.md` defines the reliability-curve and Brier-score checks that
compare `p̂_i(∅)` against the world's realised `Y_i(∅)`. If the estimator is
miscalibrated, the Evaluation page says so.

---

## 6. What this buys the Wind Tunnel

Given estimated `p̂_i(∅)` and `Δ̂_i(a)`, a scenario's expected incremental
revenue is a deterministic sum:

```
E[incremental | assignment x] = Σ_i Σ_a x_ia · amount_i · Δ̂_i(a)
```

No LLM computes any term of this. The Wind Tunnel evaluates that expression
under each candidate strategy, subject to the capacity and policy constraints
in `ARCHITECTURE.md §Optimizer`, and reports gross, natural and incremental
separately — because conflating them is the failure mode this entire product
exists to correct.

---

## 7. Determinism and reproducibility

- One master seed generates the world; `SimulationRun` stores it alongside the
  world's parameter vector.
- All randomness flows through explicitly-constructed `numpy.random.Generator`
  instances derived from that seed via `SeedSequence.spawn`, never global state.
- Holdout assignment is `sha256(experiment_id ‖ customer_id)`, so arms are
  stable across reruns, restarts and machines, and no random state is consumed.
- Re-running the demo produces byte-identical revenue figures. A live judge
  sees the same numbers as the pitch video.
