# ARCHITECTURE.md

A modular monolith. One FastAPI process, one database, domain services with hard
edges between them. No message broker and no service mesh, because the problem
does not have a distributed-systems shape and pretending otherwise would cost
clarity for nothing.

```
                                   frontend (React)
                                          │  every figure fetched, none computed here
                                     ─────┼─────
                                   api/routes.py
                        auth · scopes · rate limit · CSP · validation
                                          │
   ┌──────────────┬───────────────┬───────┴────────┬─────────────────┬──────────────┐
   │              │               │                │                 │              │
incident_     cohort_       counterfactual_   simulation_      portfolio_      experiment_
 engine        engine           engine          engine         optimizer         engine
   │              │               │                │                 │              │
   └──────────────┴───────────────┴────────┬───────┴─────────────────┴──────────────┘
                                           │
                              policy_gates · policy_engine
                                           │
                                     audit_engine
                                           │
                                      SQLAlchemy
                                           │
                                  SQLite / PostgreSQL

   adapters/razorpay_adapter        ai/client · ai/policy_compiler
   real test-mode or simulation     Claude, or deterministic fallback

   world/            evaluation_engine
   the simulator     the only reader of ground truth
```

## Why each boundary exists

**Detection is separate from attribution.** `incident_engine` says *this slice
broke and here is how confident I am*. It never says why. That separation is what
lets the system detect something it cannot explain and refuse to act on it — the
`*/*` case in the demo, where six unrelated slices degrade together and no root
cause is supportable.

**Estimation is separate from optimisation.** `counterfactual_engine` produces
`P(recovers anyway)` and per-action uplift with intervals.
`portfolio_optimizer` consumes them and knows nothing about where they came from.
So the estimator can be replaced — with Vulcan embeddings, with anything — without
touching the allocation, and the optimiser can be tested against synthetic
candidates without a model.

**Gates run before policy, and both run before the optimiser.** Compliance
produces the set of legal actions; merchant policy narrows that set; the optimiser
chooses within what survives. A merchant cannot create a compliance hole because
policy never sees the actions the gates removed.

**The world is not a service.** `world/` generates reality and resolves outcomes,
including reading hidden potential outcomes. `engines/` is the product.
`evaluation_engine` is the only module permitted to bridge them, and
`test_ground_truth_isolation.py` walks the AST of every other module to enforce it.

## Where the AI is, precisely

| Component | Model involved | Fallback |
|---|---|---|
| Incident detection | no | — |
| Natural-recovery estimation | no | — |
| Uplift estimation | no | — |
| Portfolio optimisation | no | — |
| Compliance gates | no | — |
| Experiment assignment | no | — |
| Incremental measurement | no | — |
| Root-cause narrative | yes | deterministic template from evidence |
| Policy compilation | yes | rule-based compiler |

Nothing in the top block can be influenced by a model. That is the architecture,
not a policy — the money paths have no code path that reaches `ai/`.

## State

Two pieces of process state, both deliberate:

`api/state.py` holds the fitted estimator and the day's scan behind a lock. Fitting
costs ~1.8s and scanning ~1.9s; doing either per request would make the dashboard
feel broken, and doing them concurrently on first load would have several requests
fitting the same model.

`RateLimiter` and `SeenEvents` hold token buckets and delivered event ids. Correct
for one process, wrong for a fleet, and the modules say so.

## Performance

Measured on the demo world (301,017 payments, 43,112 failures):

| Operation | Cost |
|---|---|
| World generation | 27s, one-off |
| Estimator fit | 1.8s, cached |
| Day scan, 226 ticks × 3 windows | 1.9s, cached |
| Cohort build, 1,190 candidates | ~700ms |
| Wind tunnel, 6 branches | ~20ms |
| Optimiser, 2,000 candidates | <1s |

Two things that mattered: baselines aggregate in SQL rather than loading rows
(33MB → 10MB, and bounded by cell count rather than history length), and the scan
holds its range in memory rather than issuing 690 windowed queries.
