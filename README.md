# Reversa

**Counterfactual revenue recovery.** Test recovery strategies against a simulation
of the affected cohort *before* spending a customer interaction — then prove which
one actually created incremental revenue.

Built for the Razorpay AI Buildathon 2026, Track 03.

---

## The problem this exists for

A payment fails. Every recovery tool asks *what should we do about it*, retries or
messages the customer, and reports the money that arrives as money it recovered.

On the incident this repo simulates, **58% of the exposed revenue comes back with
no intervention at all.** A tool that retries everything and quotes the gross
figure is claiming credit for money that was arriving regardless — and it has
spent scarce contact capacity on the customers least likely to need it.

Reversa asks a different question first: **what would have happened if we did
nothing?**

```
₹23.77L   exposed by the incident
₹12.34L   arrives on its own            <- a conventional tool reports this as recovered
₹11.43L   addressable                   <- the only part worth spending on
₹ 1.83L   projected incremental         <- optimiser, 500 actions
₹ 1.90L   measured against a holdout    <- 90% CI [-₹0.32L, ₹3.97L]
```

---

## What it does

```
payment stream
    ↓  incident_engine      beta-binomial detection, FDR-controlled, slice rollup
detected incident
    ↓  cohort_engine        membership + attribution + compliance gates
recovery candidates
    ↓  counterfactual_engine  P(recovers anyway) and uplift per action
    ↓  simulation_engine    alternative futures over one cohort
    ↓  portfolio_optimizer  exact assignment under capacity, by incremental value
    ↓  policy_engine        merchant rules, tighten-only
bounded execution
    ↓  experiment_engine    treatment / holdout / exploration, stratified
measured incremental revenue
    ↓  evaluation_engine    scored against the simulator's hidden answer key
    ↓  audit_engine         hash-chained, tamper-evident
```

**AI proposes. Deterministic systems decide.** The language model writes root-cause
narratives and compiles merchant policy. It never computes a rupee figure, never
assigns an experiment arm, and never authorises an action.

---

## Running it

Nothing is required beyond Python and Node. No API keys.

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/python -m scripts.seed_world --scale demo   # ~30s
../.venv/bin/python -m scripts.run_demo                                 # the whole loop
../.venv/bin/python -m uvicorn reversa.main:app --port 8000
```

```bash
cd frontend && npm install && npm run dev     # http://localhost:5173
```

Optional, and the product is honest about which is which:

| Variable | Effect when set |
|---|---|
| `REVERSA_RAZORPAY_KEY_ID` / `_SECRET` | Orders, Downtime and Payment Links hit the real test-mode API. **`rzp_live_` keys are rejected outright.** |
| `REVERSA_ANTHROPIC_API_KEY` | The policy compiler and incident investigator use Claude. Without it, deterministic implementations run — not stubs. |
| `REVERSA_SESSION_SECRET` | Sessions survive a restart. Generated per process otherwise. |

The `/api/system` route and the dashboard both state which mode every adapter is
in, because a payments demo that doesn't say which numbers came from a live API
is doing the thing this project argues against.

---

## What makes it different

**It measures, it doesn't claim.** Every recovery run withholds treatment from a
randomly assigned slice. The headline number is treatment minus holdout with a
bootstrap interval — and the interval is reported even when it contains zero.

**The randomisation is stratified.** Recovered amounts are skewed enough that a
plain hash routinely produced arms 35% apart on mean ticket, which was enough to
flip the sign of a result. Arms are now allocated within order-value strata.

**It knows when it doesn't know.** A degradation that lands on slices with no
common parent has no containable scope, so no root cause is supportable from the
evidence. Reversa detects it, sizes it at ₹10.40L, and refuses to plan.

**Compliance is graded by authority.** Every gate verdict carries a basis:
statutory (TRAI TCCCPR, DPDP), an adopted standard (RBI recovery conduct, which
binds directly only when the payment is credit-linked), a product invariant, or a
merchant setting. Only the last is tunable.

**Merchant policy can only tighten.** There is no effect in the rule vocabulary
that permits anything. "Contact everyone regardless of consent" compiles to
nothing, because the output language cannot express it.

**It is scored against an answer key it cannot see.** The simulator holds every
payment's latent resolve and both potential outcomes. An import-graph test fails
the build if any engine reads them. The Evaluation page shows detection recall,
calibration, decision quality, and — the one that matters — whether the holdout
estimate's interval contained the true incremental revenue.

---

## Docs

| | |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Services, boundaries, and why each one is separate |
| [SIMULATION.md](docs/SIMULATION.md) | The potential-outcomes model and the ground-truth boundary |
| [EVALUATION.md](docs/EVALUATION.md) | What is measured, how, and what the numbers currently are |
| [DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | The 90-second walkthrough, and the 5-minute pitch |
| [DECISIONS.md](docs/DECISIONS.md) | Bugs found, tradeoffs taken, things deliberately not built |

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest tests/ -q     # 215
cd frontend && npm run typecheck && npm run lint && npm run build
```

The tests worth reading are the ones that encode the argument rather than the
code: `test_portfolio_optimizer.py` asserts that a large payment likely to
recover anyway loses to a small one that won't, and `test_policy.py` asserts that
no merchant sentence can widen what the system may do.
