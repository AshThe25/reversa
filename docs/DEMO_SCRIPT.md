# DEMO_SCRIPT.md

Two things: the walkthrough built into the product, and the five-minute pitch.

Both run against a deterministic world. Same seed, same numbers, every time — a
live demo shows exactly what the pitch video showed.

```bash
cd backend
../.venv/bin/python -m scripts.run_demo --fresh --commit    # ~40s, prints the whole loop
../.venv/bin/python -m uvicorn reversa.main:app --port 8000
cd ../frontend && npm run dev
```

---

## The in-product walkthrough (90 seconds)

Seven docked stops from the landing page. Non-modal, never covers the numbers it
describes, escapable at any point.

| Stop | The point |
|---|---|
| Command Centre | Revenue at risk is not the number. The number is how much comes back on its own. |
| Incidents | Seven UPI handles broke together and report as one incident, not seven alerts. |
| **Futures** | Rewind and run the alternative futures. Watch DO NOTHING. |
| Portfolio | Why this customer, why this action, why not the others. 30 links, because test mode says 30. |
| Experiments | A random slice was deliberately left alone. That difference is the only honest number. |
| Audit | Every decision hash-chained. Edit one row and verification breaks from there on. |
| Evaluation | Scored against an answer key the system cannot see — including where it was wrong. |

---

## The five-minute pitch

### 0:00 — the question

> Most payment recovery asks: what should we do when a payment fails?
>
> We ask: **what would have happened if we did nothing?**

### 0:30 — the incident

Command Centre. UPI degraded at 18:02, detected at 18:05.

> ₹23.77 lakh exposed across 828 recoverable payments. Caught three minutes after
> onset — the platform's own downtime feed published four minutes after onset,
> because it needs signal before it can call it.

### 1:15 — the uncomfortable number

Open Futures, press Simulate.

> **₹12.34 lakh of that comes back on its own.** 51.9% of the exposure. Every
> recovery tool on the market would retry this cohort and report twelve lakh
> recovered. Only the remaining eleven lakh is worth spending anything on.

### 2:00 — the futures

> RETRY NOW places zero actions — a gate refuses immediate re-presentment within
> 45 minutes of a rail clearing, because retrying into a rail that just broke is
> worse than waiting. That is encoded, not learned: the harm is about three
> percentage points, which no amount of merchant history can resolve.
>
> LINK EVERYONE stops at 30, because Razorpay test mode caps a business at 30
> Payment Links and we enforce it rather than working around it.
>
> OPTIMAL: ₹1.83 lakh across 500 actions. Not the most aggressive plan — the
> aggressive plan spends capacity on people who were going to pay anyway.

Point at WASTED.

> The optimiser solves an exact assignment, not a ranked list. Every variable sits
> in one payment row and one action row, so the constraint matrix is totally
> unimodular and the LP relaxation is integral — that is the true integer optimum,
> and there is an assertion on it rather than a comment claiming it.

### 3:00 — proving it

Experiments.

> A randomly assigned slice of the plan was deliberately withheld — stratified on
> order value, because plain randomisation kept producing arms 35% apart on mean
> ticket, enough to flip the sign of a result.
>
> Projected ₹1.83 lakh. **Measured ₹1.90 lakh** against the holdout.
>
> That is not gross recovery. It is the recovery attributable to intervention, and
> the interval is on the page even when it contains zero.

### 3:45 — when it should stop

Futures, the `*/*` incident.

> ₹10.40 lakh exposed and we are not going to guess.
>
> This landed on six slices with no common parent. A PSP fault takes one method
> down together. A single bad bank stays inside one instrument. This did neither,
> so the evidence cannot attribute it — and interventions chosen from a wrong root
> cause spend capacity on the wrong people.
>
> Root-cause confidence: zero. Simulate is disabled. It goes to a human.

### 4:20 — the honesty

Evaluation.

> The simulator knows every payment's true outcome under every action. Reversa
> never reads them; an import-graph test fails the build if any engine tries.
>
> Detection: 3 of 4, no false alarms, and the one it missed is named on the page.
> The holdout estimate was ₹1.90 lakh; the truth was ₹1.35 lakh; the interval
> contained it. The measurement works, and where the system was wrong is on the
> same screen as where it was right.

### 4:45 — close

> Reversa doesn't just recover revenue. It lets a merchant test the future before
> touching a customer, and then prove what actually worked.

---

## If asked

**"Isn't this just another AI agent?"** — Nothing on the money path touches a
model. Detection, estimation, optimisation, gating, assignment and measurement are
deterministic. The model writes narratives and compiles policy.

**"How do you know your intervention caused it?"** — A randomised holdout, and the
Evaluation page checks that estimate against the true value.

**"What if the AI is wrong?"** — Merchant policy compiles into a vocabulary with no
effect that permits anything, so no sentence and no model output can widen what the
system may do. And the ambiguous incident shows it refusing to act.

**"Would this work with Razorpay?"** — Orders, Downtime and Payment Links use the
real test-mode API when keys are present; the adapter enforces the 30-link cap and
rejects `rzp_live_` keys outright. `/api/system` states which mode everything is in.

**"What's genuinely new?"** — Optimising for *incremental* rather than gross
recovery, simulating the alternatives before spending a customer interaction, and
proving the result against a holdout instead of asserting it.
