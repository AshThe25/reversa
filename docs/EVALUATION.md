# EVALUATION.md

Reversa graded against the simulator's hidden answer key. Every number here comes
from `engines/evaluation_engine.py`, the only module permitted to read
`GroundTruth`; an import-graph test fails the build if any other module names it.

Figures below are from the committed demo world (seed 20260826, scale `demo`).
Regenerate with `python -m scripts.run_demo --fresh --commit` and open
`/evaluation`.

---

## Detection

| Metric | Value |
|---|---|
| Recall | 3 of 4 injected incidents |
| Precision | 100% — no alert outside a true incident window |
| Median latency | 15 min |
| Fastest | **3 min**, the high-volume UPI slice |
| Missed | `single_bank_outage` |

The miss is honest and structural: netbanking is 10% of volume and the affected
bank is 23% of that, so the slice accumulates evidence slowly. A merchant-side
detector on 2% of traffic is genuinely slower than one at platform scale — which
is the argument for Razorpay building this rather than a merchant.

Detection is a live tick-by-tick scan, never a batch query over the range. A window
that could see the future would make every latency figure meaningless.

## Measurement — the one that matters

The experiment estimates incremental revenue from a randomised holdout with a
customer-level bootstrap. The simulator knows the exact answer from each payment's
latent resolve and both potential outcomes.

| | |
|---|---|
| Measured from holdout | ₹1.90L |
| 90% interval | [−₹0.32L, ₹3.97L] |
| **True incremental** | **₹1.35L** |
| Interval contains truth | **yes** |
| Point estimate error | +41% |

The point estimate is noisy — that is what the interval is for. The claim being
tested is that the *design* recovers the real effect, and it does. If it did not,
every headline figure elsewhere in the product would be worthless, and the page
says so.

Results also carry a minimum detectable effect and the holdout size that would
resolve the observed effect, because "not significant" and "no effect" are
different claims.

## Calibration

Scored on the holdout only. Nothing was done to those payments, so their realised
outcome *is* the natural outcome by definition — scoring on the treated group
would be measuring something else.

| Metric | Value |
|---|---|
| Brier | 0.114 |
| Expected calibration error | 0.064 |
| Bias | −3.3% |

Slightly under-confident about natural recovery, which errs toward intervening
more than necessary rather than less. The reliability curve is on `/evaluation`.

## Decision quality

| Metric | Value |
|---|---|
| Genuinely effective actions | ~72% (true uplift above zero) |
| Picked the best *available* action | ~11% |
| Mean regret | 0.035 uplift points |

Top-1 accuracy is low, and the reason is worth stating rather than hiding.
Separating the best action from the second-best usually means resolving a
difference of two or three percentage points, which observational merchant history
cannot support — the actions were not randomly assigned, so the estimates carry
selection bias. This is precisely why the system runs a permanent exploration arm,
and why mean regret and the genuinely-harmful count matter more than top-1.

Scoring is against the best action that was *available*. Grading the optimiser
against an option a compliance gate had already removed would measure the gates.

## Cohort

Precision ~93%: that share of cohort members were genuinely inside a true incident
window. The remainder are ordinary baseline failures the window swept up, which is
exactly what the attribution weight discounts for when reporting exposure.

## What is not measured

Root-cause classification accuracy, because root-cause *narratives* are generated
and the only structured claim the system makes is attributable-vs-not — which is
scored via the diffuse-cluster path. Anything else would be grading prose.
