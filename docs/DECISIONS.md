# Decisions, bugs and deliberate omissions

A record of what went wrong while building this, what was traded away, and what
was left out on purpose. Written because the interesting part of a system is
rarely the parts that worked first time.

---

## Bugs the evaluation harness found

Running the system against the simulator's hidden answer key was worth more than
any amount of re-reading the code. Each of these produced plausible output.

**The detector was reading final payment status.** Recovering a payment rewrites
`FAILED` to `RECOVERED`, so recovering a cohort retroactively erased the incident
that caused it. Re-running detection showed the UPI outage caught 33 minutes late
instead of 3. Success is now `CAPTURED` — the first presentment.

**Hierarchical shrinkage fell back to the global rate.** The running prior and the
chosen cell shared a variable, so by the last iteration they were equal and the
final shrinkage used the grand mean. `infra_transient` came out at 0.433 against a
true 0.77 — a 34-point error on exactly the class where over-intervening is most
wasteful.

**Uplift was confounded by population mix.** Backing off to a coarser *treated*
cell while keeping a class-keyed control compared the global SMS-treated pool
(mostly `auth_friction`, recovering at 0.47) against an `instrument_invalid`
control at 0.06, and reported large credible uplift for sending SMS about a
cancelled card. Treated and control now back off together, level for level.

**Shrinkage made thin evidence look precise.** Both the point estimate and the
interval were multiplied by `n/(n+κ)`, so an arm appeared *more* certain the less
data backed it — twelve observations could report credible uplift. Replaced with a
conjugate update against a zero-centred prior.

**The in-incident feature was structurally unlearnable.** It was derived from the
Razorpay downtime feed, which publishes 4–11 minutes after onset and not for every
event, so it was false exactly when it mattered. Then it turned out the training
era only carried ~2,000 orders/day against a 120,000-order live day, leaving every
per-slice time bucket with 2–9 payments — nothing could be labelled at all.

**Experiment arms were assigned across the whole cohort** while the plan touched
122 of 950 payments, so treatment and holdout were near-identical populations and
the measured lift was noise.

**The audit chain was forkable.** Appending is read-the-head-then-insert, which is
not atomic. Two writers could read the same head and both link to it, splitting
the log into branches that each verify perfectly in isolation. A tamper-evident
ledger that silently isn't one is worse than none.

---

## Tradeoffs taken

**Retrying into a just-degraded rail is a gate, not a hypothesis.** The true harm
is about three percentage points — real money at scale and completely undetectable
from ordinary merchant history. An estimator fed that history would keep choosing
RETRY NOW and keep being mildly wrong forever. Some things you encode.

**Action cost is netted off the objective, not imposed as a budget row.** A budget
constraint is a knapsack row and destroys the total unimodularity the exact solve
depends on. Same economics, and the solve stays exact.

**One contact per customer is enforced when candidates are built**, not as a third
constraint in the optimiser — which would put variables in three rows and break
the same property.

**A minimum expected value per action.** Free actions with any positive uplift
clear a naive EV test, and 332 of 711 chosen actions were worth under ₹50 each
while contributing 9% of the plan's value. They aren't free: they burn capacity,
spend customer patience, and dilute the treatment arm into noise.

**SQLite by default, Postgres supported.** A judge clones the repo and runs it.
The dialect-specific code is two functions and both have Postgres branches.

**In-memory rate limiting and idempotency.** Correct for one process, wrong for a
fleet — and said so in the modules rather than left to be discovered. Both have
the same interface as their Redis equivalents.

---

## Deliberately not built

**Webhook ingestion.** The verifier is complete and tested — signature over raw
bytes with `compare_digest`, freshness window, event-id idempotency — but there is
no route consuming it, because the simulator resolves outcomes directly and a
webhook endpoint would have been ceremony.

**A real LLM in the demo path.** Everything runs deterministically without a key
and the AI paths are additive. This is a choice: a demo that only works with
credentials is not demonstrable.

**Alembic migrations.** The schema is created from the models and the world is
regenerated rather than migrated. Correct for a project whose database is
disposable; the first thing to add if it stopped being.

**Multi-tenancy.** `merchant_id` is on every table and no query filters by it.
The scoping is a dependency away, but claiming tenancy isolation without enforcing
it would be worse than not claiming it.
