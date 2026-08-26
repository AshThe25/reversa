"""Builds the synthetic world.

Generates a merchant's payment history: customers with persistent traits, an
order stream with real daily/weekly shape, failures driven by method, instrument,
time of day and injected incidents, and - for every failed payment - the hidden
potential outcomes that make causal claims checkable later.

The important structural point: rows are not independent draws. A customer's
liquidity, their instrument going bad, how often they've already been contacted,
their own realised recovery history - all of it feeds forward. If you shuffled
the timestamps the dataset would stop making sense, which is the test I wanted it
to pass.

See docs/SIMULATION.md for the potential-outcomes model. Short version: every
failed payment gets one latent uniform U, and every counterfactual is that same U
thresholded against a different probability. Same customer, same resolve, across
all futures. Re-rolling per scenario would make "retry everyone" look free.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy.orm import Session

from reversa.config import IST
from reversa.models import (
    ComplianceEvent,
    Customer,
    DowntimeRecord,
    GroundTruth,
    Merchant,
    Order,
    Payment,
    PaymentAttempt,
    PaymentEvent,
    PaymentStatus,
    RunEra,
    WorldMeta,
)
from reversa.taxonomy import RecoveryClass, classify
from reversa.world import params as P

MERCHANT_ID = "mer_reversa_demo"


class _Ids:
    """Deterministic id factory.

    First version used uuid4 here and the reproducibility test caught it: same
    seed, different ids, so nothing downstream that hashes an id was stable.
    Counter + seed prefix instead. Ids stay unique across seeds because the
    prefix moves.
    """

    def __init__(self, seed: int):
        self.prefix = f"{seed & 0xFFFF:04x}"
        self.counters: dict[str, int] = {}

    def __call__(self, kind: str) -> str:
        n = self.counters.get(kind, 0)
        self.counters[kind] = n + 1
        return f"{kind}_{self.prefix}{n:09x}"


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _pick(rng: np.random.Generator, mapping: dict[str, float]) -> str:
    """Weighted pick. Normalises, because callers pass filtered sub-dicts."""
    keys = list(mapping)
    w = np.array([mapping[k] for k in keys], dtype=float)
    return keys[rng.choice(len(keys), p=w / w.sum())]


@dataclass(slots=True)
class Trait:
    """Latent per-customer state. Never persisted to an observable table."""

    intent: float
    liquidity_tightness: float
    instrument_stability: float
    responsiveness: float
    salary_day: int
    preferred_method: str
    tier: str
    # forward-carried history
    failures: int = 0
    natural_recoveries: int = 0
    contacts: list[float] = field(default_factory=list)   # epoch seconds
    instrument_dead_from: float | None = None
    instrument_repaired_at: float = 0.0
    lifetime_orders: int = 0
    lifetime_value: int = 0


@dataclass(slots=True)
class TrueIncident:
    id: str
    template: str
    label: str
    root_cause: str
    method: str | None
    instruments: tuple[str, ...] | None
    start: datetime
    end: datetime
    failure_multiplier: float
    reason_mix: dict[str, float]
    severity: str
    downtime_published: bool
    ambiguous: bool
    era: str

    def covers(self, when: datetime, method: str, instrument: str) -> bool:
        if not (self.start <= when < self.end):
            return False
        if self.method is not None and method != self.method:
            return False
        if self.instruments is not None and instrument not in self.instruments:
            return False
        return True

    def as_dict(self) -> dict:
        return {
            "id": self.id, "template": self.template, "label": self.label,
            "root_cause": self.root_cause, "method": self.method,
            "instruments": list(self.instruments) if self.instruments else None,
            "start": self.start.isoformat(), "end": self.end.isoformat(),
            "failure_multiplier": self.failure_multiplier,
            "severity": self.severity, "ambiguous": self.ambiguous,
            "downtime_published": self.downtime_published, "era": self.era,
        }


class WorldGenerator:
    def __init__(self, session: Session, *, seed: int = 20260826, scale: str = P.DEFAULT_SCALE):
        self.session = session
        self.seed = seed
        self.scale = scale
        self.cfg = P.SCALE_PRESETS[scale]

        # every stream gets its own generator off one seed, so adding a stream
        # later doesn't shift the draws of the existing ones
        streams = np.random.SeedSequence(seed).spawn(6)
        self.rng_cust = np.random.default_rng(streams[0])
        self.rng_order = np.random.default_rng(streams[1])
        self.rng_fail = np.random.default_rng(streams[2])
        self.rng_truth = np.random.default_rng(streams[3])
        self.rng_legacy = np.random.default_rng(streams[4])
        self.rng_misc = np.random.default_rng(streams[5])

        # live day is "today" at midnight IST, in UTC
        today = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
        self.live_day = today.astimezone(timezone.utc)
        self.training_days = self.cfg["training_days"]
        self.start = self.live_day - timedelta(days=self.training_days)
        self.demo_clock = (today + timedelta(minutes=P.DEMO_CLOCK_MIN)).astimezone(timezone.utc)

        self.ids = _Ids(seed)
        self.traits: dict[str, Trait] = {}
        self.customer_ids: list[str] = []
        self.incidents: list[TrueIncident] = []
        self.stats: dict = {}

    # -- entry point --------------------------------------------------------

    def run(self) -> dict:
        t0 = time.perf_counter()
        self._merchant()
        self._customers()
        self._schedule_incidents()
        self._downtime_feed()
        self._payments()
        self._compliance_events()
        self._write_meta()
        self.stats["generate_seconds"] = round(time.perf_counter() - t0, 2)
        return self.stats

    # -- merchant / customers ----------------------------------------------

    def _merchant(self) -> None:
        self.session.merge(Merchant(
            id=MERCHANT_ID,
            name="Kanha Living",          # mid-size D2C home & apparel
            category="d2c_retail",
            mcc="5651",
        ))
        self.session.flush()

    def _customers(self) -> None:
        rng = self.rng_cust
        n = self.cfg["customers"]
        tiers = list(P.CUSTOMER_TIERS)
        tier_p = np.array([P.CUSTOMER_TIERS[t]["share"] for t in tiers])
        tier_idx = rng.choice(len(tiers), size=n, p=tier_p)

        first = ["Aarav", "Vihaan", "Ananya", "Diya", "Kabir", "Ishaan", "Meera",
                 "Riya", "Arjun", "Saanvi", "Rohan", "Tara", "Aditya", "Nisha",
                 "Karthik", "Sneha", "Rahul", "Pooja", "Vikram", "Anjali"]
        last = ["Sharma", "Iyer", "Reddy", "Nair", "Patel", "Menon", "Gupta",
                "Bose", "Kulkarni", "Rao", "Singh", "Desai", "Chatterjee", "Pillai"]
        cities = ["Bengaluru", "Mumbai", "Delhi", "Pune", "Hyderabad", "Chennai",
                  "Kolkata", "Ahmedabad", "Jaipur", "Kochi", "Lucknow", "Indore"]
        langs = ["en", "en", "en", "hi", "hi", "ta", "te", "mr", "bn", "kn"]

        rows = []
        for i in range(n):
            tier = tiers[tier_idx[i]]
            spec = P.CUSTOMER_TIERS[tier]
            cid = f"cus_{i:06d}"
            method = _pick(rng, P.METHOD_SHARE)

            intent = float(np.clip(
                rng.beta(spec["intent"] * P.INTENT_CONCENTRATION,
                         (1 - spec["intent"]) * P.INTENT_CONCENTRATION), 0.02, 0.98))
            trait = Trait(
                intent=intent,
                liquidity_tightness=float(rng.beta(*P.LIQUIDITY_TIGHTNESS_BETA)),
                instrument_stability=float(rng.beta(*P.INSTRUMENT_STABILITY_BETA)),
                responsiveness=float(rng.beta(*P.CHANNEL_RESPONSIVENESS_BETA)),
                salary_day=int(rng.choice([1, 1, 1, 2, 5, 7, 10, 25, 28, 30])),
                preferred_method=method,
                tier=tier,
            )
            self.traits[cid] = trait
            self.customer_ids.append(cid)

            name = f"{first[rng.integers(len(first))]} {last[rng.integers(len(last))]}"
            opted_out = rng.random() < P.OPT_OUT_RATE
            rows.append(dict(
                id=cid, merchant_id=MERCHANT_ID, name=name,
                email=f"{cid}@example.invalid",
                phone=f"+9198{rng.integers(10_000_000, 99_999_999)}",
                city=cities[rng.integers(len(cities))],
                language=langs[rng.integers(len(langs))],
                tier=tier, preferred_method=method, salary_day=trait.salary_day,
                sms_consent=bool(rng.random() < 0.93),
                whatsapp_consent=bool(rng.random() < 0.58),
                email_consent=bool(rng.random() < 0.88),
                voice_consent=bool(rng.random() < 0.24),
                opted_out_at=self.start if opted_out else None,
                lifetime_orders=0, lifetime_value_paise=0,
                prior_failures=0, prior_natural_recoveries=0, prior_contacts=0,
                created_at=self.start - timedelta(days=int(rng.integers(1, 400))),
            ))

        self.session.bulk_insert_mappings(Customer, rows)
        self.session.flush()
        self.stats["customers"] = n

    # -- incidents ----------------------------------------------------------

    def _schedule_incidents(self) -> None:
        rng = self.rng_misc

        # training-era incidents: gives the detector history to calibrate on and
        # the evaluation harness more than one positive to score against
        keys = [k for k in P.INCIDENT_TEMPLATES if k != "ambiguous_latency"]
        for _ in range(P.TRAINING_INCIDENT_COUNT):
            tmpl_key = keys[rng.integers(len(keys))]
            day = int(rng.integers(0, self.training_days))
            # bias toward busy hours, that's when degradations actually bite
            start_min = int(rng.choice(
                np.arange(24 * 60),
                p=np.repeat(np.array(P.HOURLY_SHARE), 60) / 60.0,
            ))
            dur = int(rng.integers(*P.TRAINING_INCIDENT_DURATION_RANGE_MIN))
            begin = self.start + timedelta(days=day, minutes=start_min)
            self.incidents.append(self._make_incident(tmpl_key, begin, dur, RunEra.TRAINING))

        for spec in P.LIVE_INCIDENT_SCHEDULE:
            begin = self.live_day + timedelta(minutes=spec["start_min"])
            self.incidents.append(
                self._make_incident(spec["template"], begin, spec["duration_min"], RunEra.LIVE)
            )

        self.incidents.sort(key=lambda i: i.start)
        self.stats["true_incidents"] = len(self.incidents)

    def _make_incident(self, key: str, begin: datetime, dur_min: int, era: str) -> TrueIncident:
        t = P.INCIDENT_TEMPLATES[key]
        return TrueIncident(
            id=self.ids("tinc"),
            template=key,
            label=t["label"],
            root_cause=t["root_cause"],
            method=t["method"],
            instruments=t["instruments"],
            start=begin,
            end=begin + timedelta(minutes=dur_min),
            failure_multiplier=t["failure_multiplier"],
            reason_mix=t["reason_mix"],
            severity=t["severity"],
            downtime_published=t["downtime_published"],
            ambiguous=t.get("ambiguous", False),
            era=era,
        )

    def _downtime_feed(self) -> None:
        """What the Razorpay downtime API would have reported.

        Published late (the platform needs signal before it calls it), and not
        for every incident. Plus some scheduled-maintenance decoys that carry no
        failure impact, so the detector's precision number is earned.
        """
        rng = self.rng_misc
        rows = []
        for inc in self.incidents:
            if not inc.downtime_published:
                continue
            lag = int(rng.integers(*P.DOWNTIME_PUBLISH_LAG_MIN))
            instrument = inc.instruments[0] if inc.instruments else "ALL"
            rows.append(dict(
                id=self.ids("down"),
                method=inc.method or "upi",
                instrument=instrument,
                status="resolved",
                severity=inc.severity if inc.severity in ("low", "medium", "high") else "high",
                scheduled=False,
                begin=inc.start + timedelta(minutes=lag),
                end=inc.end + timedelta(minutes=int(rng.integers(0, 6))),
                adapter_mode="simulation",
            ))

        for _ in range(P.DECOY_DOWNTIME_COUNT):
            method = _pick(rng, P.METHOD_SHARE)
            begin = self.start + timedelta(
                days=int(rng.integers(0, self.training_days)),
                minutes=int(rng.integers(0, 24 * 60)),
            )
            rows.append(dict(
                id=self.ids("down"),
                method=method,
                instrument=_pick(rng, P.INSTRUMENTS[method]),
                status="resolved", severity="low", scheduled=True,
                begin=begin, end=begin + timedelta(minutes=int(rng.integers(10, 40))),
                adapter_mode="simulation",
            ))

        self.session.bulk_insert_mappings(DowntimeRecord, rows)
        self.session.flush()
        self.stats["downtime_records"] = len(rows)

    def _incident_for(self, when: datetime, method: str, instrument: str) -> TrueIncident | None:
        for inc in self.incidents:
            if inc.covers(when, method, instrument):
                return inc
        return None

    # -- the payment stream -------------------------------------------------

    def _payments(self) -> None:
        rng = self.rng_order
        weights = np.array([P.CUSTOMER_TIERS[self.traits[c].tier]["rate"]
                            for c in self.customer_ids])
        weights = weights / weights.sum()
        cust_arr = np.array(self.customer_ids)

        hourly = np.array(P.HOURLY_SHARE)
        per_1k = P.TRAINING_ORDERS_PER_DAY_PER_1K_CUSTOMERS
        base_daily = int(self.cfg["customers"] / 1000 * per_1k)

        orders, payments, attempts, events, truths = [], [], [], [], []
        counters = {"failed": 0, "captured": 0, "recovered": 0}

        for day in range(self.training_days + 1):
            is_live = day == self.training_days
            day_start = self.start + timedelta(days=day)
            if is_live:
                n_orders = self.cfg["live_orders"]
                era = RunEra.LIVE
            else:
                wd = day_start.astimezone(IST).weekday()
                n_orders = int(base_daily * P.WEEKDAY_MULTIPLIER[wd] * rng.uniform(0.9, 1.1))
                era = RunEra.TRAINING

            cust_pick = rng.choice(cust_arr, size=n_orders, p=weights)
            hour_pick = rng.choice(24, size=n_orders, p=hourly)
            minute_pick = rng.integers(0, 60, size=n_orders)
            second_pick = rng.integers(0, 60, size=n_orders)

            for k in range(n_orders):
                cid = str(cust_pick[k])
                trait = self.traits[cid]
                # IST wall clock -> UTC
                when = (day_start.astimezone(IST).replace(
                    hour=int(hour_pick[k]), minute=int(minute_pick[k]),
                    second=int(second_pick[k]),
                )).astimezone(timezone.utc)

                self._one_order(
                    cid, trait, when, era, is_live,
                    orders, payments, attempts, events, truths, counters,
                )

        self.session.bulk_insert_mappings(Order, orders)
        self.session.bulk_insert_mappings(Payment, payments)
        self.session.bulk_insert_mappings(PaymentAttempt, attempts)
        self.session.bulk_insert_mappings(PaymentEvent, events)
        self.session.bulk_insert_mappings(GroundTruth, truths)
        self._flush_customer_history()
        self.session.flush()

        self.stats.update({
            "orders": len(orders),
            "payments": len(payments),
            "attempts": len(attempts),
            "failures": counters["failed"],
            "captured_first_try": counters["captured"],
            "recovered_in_training": counters["recovered"],
            "ground_truth_rows": len(truths),
        })

    def _one_order(self, cid, trait, when, era, is_live,
                   orders, payments, attempts, events, truths, counters) -> None:
        rng = self.rng_fail
        ist = when.astimezone(IST)

        # --- amount & category
        category = _pick(rng, P.ORDER_CATEGORIES)
        tier_mult = P.CUSTOMER_TIERS[trait.tier]["ticket"]
        rupees = float(rng.lognormal(P.TICKET_LOGNORMAL_MU, P.TICKET_LOGNORMAL_SIGMA))
        amount = int(np.clip(rupees * tier_mult, P.TICKET_MIN_PAISE / 100,
                             P.TICKET_MAX_PAISE / 100) * 100)
        amount = int(round(amount / 100) * 100)
        is_sub = category in P.SUBSCRIPTION_CATEGORIES

        # --- instrument. customers mostly stay on their preferred method
        method = trait.preferred_method if rng.random() < 0.78 else _pick(rng, P.METHOD_SHARE)
        instrument = _pick(rng, P.INSTRUMENTS[method])

        oid = self.ids("ord")
        pid = self.ids("pay")

        orders.append(dict(
            id=oid, merchant_id=MERCHANT_ID, customer_id=cid, amount_paise=amount,
            currency="INR", category=category, is_subscription=is_sub,
            rzp_order_id=None, adapter_mode="simulation", created_at=when,
        ))
        trait.lifetime_orders += 1

        # --- does it fail?
        incident = self._incident_for(when, method, instrument)
        p_fail = (P.BASE_FAILURE_RATE[method]
                  * P.INSTRUMENT_FAILURE_MULTIPLIER.get(instrument, 1.0)
                  * P.HOURLY_FAILURE_MULTIPLIER[ist.hour])

        # liquidity-tight customers fail more the further they are from payday
        days_since_pay = (ist.day - trait.salary_day) % 30
        p_fail *= 1.0 + trait.liquidity_tightness * 0.55 * (days_since_pay / 30.0)

        # dead instrument: everything on that method fails until they notice
        dead = False
        if trait.instrument_dead_from is not None and method == trait.preferred_method:
            if when.timestamp() >= trait.instrument_repaired_at:
                # they noticed and moved to something else
                trait.instrument_dead_from = None
                trait.preferred_method = _pick(
                    rng, {m: w for m, w in P.METHOD_SHARE.items() if m != method}
                )
            elif when.timestamp() >= trait.instrument_dead_from:
                dead = True
        if (not dead and trait.instrument_dead_from is None
                and rng.random() < P.INSTRUMENT_DEATH_RATE * (1 - trait.instrument_stability)):
            trait.instrument_dead_from = when.timestamp()
            trait.instrument_repaired_at = when.timestamp() + 86400 * float(
                rng.uniform(*P.INSTRUMENT_REPAIR_DAYS)
            )
            dead = True
        if dead:
            p_fail = 0.92

        if incident is not None:
            p_fail = min(0.97, p_fail * incident.failure_multiplier)

        failed = rng.random() < p_fail

        if not failed:
            counters["captured"] += 1
            trait.lifetime_value += amount
            payments.append(dict(
                id=pid, order_id=oid, customer_id=cid, merchant_id=MERCHANT_ID,
                amount_paise=amount, method=method, instrument=instrument,
                status=PaymentStatus.CAPTURED, era=era, failure_reason=None,
                failure_class=None, error_source=None, error_step=None,
                incident_id=None, created_at=when, resolved_at=when,
                recovered_amount_paise=0, recovered_via=None,
            ))
            attempts.append(dict(
                id=self.ids("att"), payment_id=pid, attempt_no=1,
                method=method, instrument=instrument, succeeded=True,
                error_reason=None, origin="customer", adapter_mode="simulation",
                created_at=when,
            ))
            return

        # --- pick a failure reason
        if dead:
            reason = {"card": "card_expired", "upi": "invalid_vpa",
                      "netbanking": "account_closed",
                      "wallet": "insufficient_balance_wallet"}[method]
        elif incident is not None:
            reason = _pick(rng, incident.reason_mix)
        else:
            mix = dict(P.NORMAL_REASON_MIX[method])
            # tight liquidity late in the month tilts the mix toward funds
            if "insufficient_funds" in mix:
                bump = trait.liquidity_tightness * 0.35 * (days_since_pay / 30.0)
                mix["insufficient_funds"] += bump
                total = sum(mix.values())
                mix = {k: v / total for k, v in mix.items()}
            reason = _pick(rng, mix)

        mode = classify(reason)
        rclass = mode.recovery_class.value
        counters["failed"] += 1
        trait.failures += 1

        payments.append(dict(
            id=pid, order_id=oid, customer_id=cid, merchant_id=MERCHANT_ID,
            amount_paise=amount, method=method, instrument=instrument,
            status=PaymentStatus.FAILED, era=era, failure_reason=reason,
            failure_class=rclass, error_source=mode.source.value,
            error_step=mode.step.value, incident_id=None,
            created_at=when, resolved_at=None,
            recovered_amount_paise=0, recovered_via=None,
        ))
        attempts.append(dict(
            id=self.ids("att"), payment_id=pid, attempt_no=1,
            method=method, instrument=instrument, succeeded=False,
            error_reason=reason, origin="customer", adapter_mode="simulation",
            created_at=when,
        ))
        events.append(dict(
            id=self.ids("pev"), payment_id=pid,
            event_type="payment.failed",
            payload={"reason": reason, "method": method, "instrument": instrument},
            occurred_at=when,
        ))

        truth = self._ground_truth(pid, trait, amount, rclass, reason, when,
                                   is_sub, incident)
        truths.append(truth)

        # training era: the legacy policy gets a go, and we realise the outcome
        if not is_live:
            self._run_legacy(pid, trait, amount, rclass, when, truth,
                             method, instrument, payments, attempts, events, counters)

    # -- hidden ground truth ------------------------------------------------

    def _ground_truth(self, pid, trait, amount, rclass, reason, when,
                      is_sub, incident) -> dict:
        """Potential outcomes for one failed payment.

        The single latent U is the whole point - see docs/SIMULATION.md. It gets
        thresholded against p_natural and against every p(action), so the same
        customer's resolve is held fixed across every future the wind tunnel
        explores. Individual treatment effect is just 1[p_nat <= U < p_action],
        which is why targeting people who'd have paid anyway shows up as
        literally zero.
        """
        rng = self.rng_truth
        ist = when.astimezone(IST)
        C = P.NATURAL_RECOVERY_COEF

        z = P.NATURAL_RECOVERY_BASE_LOGIT.get(rclass, -1.0)
        z += C["intent"] * (trait.intent - 0.5)
        prior_rate = (trait.natural_recoveries / trait.failures) if trait.failures >= 2 else 0.42
        z += C["prior_recovery_rate"] * (prior_rate - 0.42)
        z += C["log_amount"] * (math.log(max(amount, 1) / 100.0) - P.TICKET_LOGNORMAL_MU)
        z += C["is_subscription"] * (1.0 if is_sub else 0.0)
        z += C["vip"] * (1.0 if trait.tier == "vip" else 0.0)
        z += C["new_customer"] * (1.0 if trait.tier == "new" else 0.0)
        if 18 <= ist.hour <= 22:
            z += C["evening"]
        if ist.hour <= 5:
            z += C["small_hours"]

        # liquidity failures resolve around payday, not on a fixed clock
        if rclass == RecoveryClass.LIQUIDITY.value:
            gap = min((trait.salary_day - ist.day) % 30, (ist.day - trait.salary_day) % 30)
            z += P.SALARY_DAY_BONUS_LOGIT * math.exp(-gap / P.SALARY_DAY_DECAY_DAYS)

        z += float(rng.normal(0, P.NATURAL_RECOVERY_NOISE_SD))
        p_nat = float(np.clip(_sig(z), 0.005, P.P_MAX))

        # uplift per action
        p_by_action, uplift = {}, {}
        in_incident = incident is not None
        for action in P.ACTIONS_WITH_UPLIFT:
            base = P.UPLIFT_BASE[action].get(rclass, 0.0)
            if action == "retry_now" and in_incident:
                base += P.INCIDENT_RETRY_PENALTY
            if action in P.CONTACT_DECAY_TAU_HOURS:
                # the wind tunnel varies delay; ground truth is scored at the
                # nominal 1h response point so scenarios stay comparable
                base *= math.exp(-1.0 / P.CONTACT_DECAY_TAU_HOURS[action])
                base *= (1.0 - P.RESPONSIVENESS_SCALE * (0.5 - trait.responsiveness))
                fatigue_idx = min(len(trait.contacts), len(P.CONTACT_FATIGUE) - 1)
                base *= P.CONTACT_FATIGUE[fatigue_idx]
            # you can't add much to someone already at 0.8
            delta = base * (1.0 - p_nat) ** P.UPLIFT_DAMPING_GAMMA
            p_a = float(np.clip(p_nat + delta, 0.0, P.P_MAX))
            p_by_action[action] = round(p_a, 5)
            uplift[action] = round(p_a - p_nat, 5)

        best = max(uplift, key=uplift.get)
        u = float(rng.random())
        recovers_nat = u < p_nat

        delay = None
        if recovers_nat:
            mu, sigma = P.RECOVERY_DELAY_LOGNORMAL.get(rclass, (1.5, 1.2))
            delay = float(rng.lognormal(mu, sigma))
            if delay > P.RECOVERY_HORIZON_HOURS:
                # recovered, but outside the window we're allowed to count
                recovers_nat = False
                delay = None

        return dict(
            payment_id=pid,
            true_incident_id=incident.id if incident else None,
            true_root_cause=incident.root_cause if incident else f"organic:{rclass}",
            true_failure_class=rclass,
            resolve_u=round(u, 6),
            true_p_natural=round(p_nat, 5),
            true_p_by_action=p_by_action,
            true_uplift_by_action=uplift,
            true_best_action=best,
            true_best_action_uplift=uplift[best],
            recovers_naturally=recovers_nat,
            natural_recovery_hours=delay,
            realised_action=None,
            realised_recovered=None,
            realised_incremental=None,
            is_incident_member=incident is not None,
        )

    # -- legacy policy (training era only) ----------------------------------

    def _run_legacy(self, pid, trait, amount, rclass, when, truth,
                    method, instrument, payments, attempts, events, counters) -> None:
        """The merchant's pre-Reversa rule, plus epsilon-random exploration.

        The exploration isn't decoration. Under a purely deterministic legacy
        policy, action assignment is a function of the same covariates that drive
        the outcome, and no honest uplift estimate is possible from the log. This
        epsilon is the reason Reversa can learn anything at all on day one.
        """
        rng = self.rng_legacy
        if rng.random() > P.LEGACY_COVERAGE:
            action = "no_action"
        elif rng.random() < P.LEGACY_EXPLORATION_EPSILON:
            action = str(rng.choice(list(P.ACTIONS_WITH_UPLIFT) + ["no_action"]))
        elif amount >= P.LEGACY_LINK_THRESHOLD_PAISE:
            action = "payment_link"
        else:
            action = "retry_now"

        p = truth["true_p_natural"] if action == "no_action" else truth["true_p_by_action"][action]
        u = truth["resolve_u"]
        recovered = u < p
        incremental = truth["true_p_natural"] <= u < p

        truth["realised_action"] = action
        truth["realised_recovered"] = recovered
        truth["realised_incremental"] = incremental

        if action in P.CONTACT_DECAY_TAU_HOURS:
            trait.contacts.append(when.timestamp())

        if not recovered:
            return

        counters["recovered"] += 1
        mu, sigma = P.RECOVERY_DELAY_LOGNORMAL.get(rclass, (1.5, 1.2))
        hours = min(float(rng.lognormal(mu, sigma)), P.RECOVERY_HORIZON_HOURS)
        at = when + timedelta(hours=hours)

        # only count it as a natural recovery for the customer's own history if
        # nothing was actually done to them
        if action == "no_action":
            trait.natural_recoveries += 1
        trait.lifetime_value += amount

        payments[-1]["status"] = PaymentStatus.RECOVERED
        payments[-1]["resolved_at"] = at
        payments[-1]["recovered_amount_paise"] = amount
        payments[-1]["recovered_via"] = action

        attempts.append(dict(
            id=self.ids("att"), payment_id=pid, attempt_no=2,
            method=method, instrument=instrument, succeeded=True, error_reason=None,
            origin="customer" if action == "no_action" else "legacy_policy",
            adapter_mode="simulation", created_at=at,
        ))
        events.append(dict(
            id=self.ids("pev"), payment_id=pid,
            event_type="payment.recovered",
            payload={"via": action, "hours": round(hours, 2)}, occurred_at=at,
        ))

    def _flush_customer_history(self) -> None:
        """Push the forward-carried history onto the observable customer rows."""
        self.session.bulk_update_mappings(Customer, [
            dict(
                id=cid,
                lifetime_orders=t.lifetime_orders,
                lifetime_value_paise=t.lifetime_value,
                prior_failures=t.failures,
                prior_natural_recoveries=t.natural_recoveries,
                prior_contacts=len(t.contacts),
                last_contacted_at=(
                    datetime.fromtimestamp(max(t.contacts), tz=timezone.utc)
                    if t.contacts else None
                ),
            )
            for cid, t in self.traits.items()
        ])

    # -- compliance state ---------------------------------------------------

    def _compliance_events(self) -> None:
        rng = self.rng_misc
        rows = []
        for cid in self.customer_ids:
            if rng.random() < P.COMPLAINT_RATE:
                rows.append(dict(
                    id=self.ids("ce"), customer_id=cid,
                    event_type="complaint_raised",
                    detail="Customer raised a grievance about repeated payment retries.",
                    occurred_at=self.live_day - timedelta(days=int(rng.integers(0, 9))),
                    active=True,
                ))
        self.session.bulk_insert_mappings(ComplianceEvent, rows)
        self.session.flush()
        self.stats["active_complaints"] = len(rows)

    # -- meta ---------------------------------------------------------------

    def _write_meta(self) -> None:
        param_digest = hashlib.sha256(
            repr(sorted(
                (k, v) for k, v in vars(P).items()
                if not k.startswith("_") and isinstance(v, (int, float, str, tuple, dict))
            )).encode()
        ).hexdigest()[:16]

        self.session.merge(WorldMeta(key="world", value={
            "seed": self.seed,
            "scale": self.scale,
            "param_digest": param_digest,
            "start": self.start.isoformat(),
            "live_day": self.live_day.isoformat(),
            "demo_clock": self.demo_clock.isoformat(),
            "training_days": self.training_days,
            "stats": self.stats,
        }, updated_at=datetime.now(timezone.utc)))
        self.session.merge(WorldMeta(
            key="true_incidents",
            value={"incidents": [i.as_dict() for i in self.incidents]},
            updated_at=datetime.now(timezone.utc),
        ))
        self.session.flush()


def generate(session: Session, *, seed: int = 20260826, scale: str = P.DEFAULT_SCALE) -> dict:
    return WorldGenerator(session, seed=seed, scale=scale).run()
