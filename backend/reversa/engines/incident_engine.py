"""Incident detection over the payment stream.

The job: notice that a slice of payments started failing, before anyone
complains and before the platform publishes a downtime notice.

Four things make this harder than a threshold, and the first version of this
module got three of them wrong before the numbers made it obvious.

**Seasonality.** UPI's failure rate at 03:00 is genuinely worse than at 15:00 -
batch windows, bank maintenance, a different customer mix. A fixed threshold
either screams all night or sleeps through a real 15:00 degradation. Baselines
are per (slice, hour), EWMA'd across days, shrunk toward coarser cells when a
cell is thin.

**Overdispersion.** This is the one that hurt. A plain binomial test assumes the
baseline rate is exact and the only variation is sampling noise. Real success
rates wander - customer mix, day of month, which cohort happens to be shopping -
so once n gets moderate a binomial test flags ordinary wander as significant.
First pass fired 30 incidents against 4 real ones. The fix is a beta-binomial
test whose concentration is estimated from how much each slice's rate actually
moves across historical windows, after subtracting the binomial component. A
slice that is naturally jumpy has to move further before we believe it.

**Onset latency.** A single 15-minute window dilutes a sharp onset: three
minutes into an outage, twelve minutes of the window are still healthy. So each
tick runs a small scan statistic - several window lengths ending at the same
instant - and keeps the most significant. Short windows catch cliffs, long
windows catch slow bleeds. The extra tests are absorbed by the FDR correction.

**Multiplicity.** ~25 slices x 3 windows every tick, ~290 ticks a day. At p<0.05
that is a thousand false alarms a day from noise alone. Every tick's p-values go
through Benjamini-Hochberg and we alert on q, never p.

One more thing that is about reporting rather than statistics: when a PSP goes
down, every UPI handle breaks at once. Reporting seven instrument-level
incidents is both noise and triple-counted revenue. `_rollup` walks the slice
hierarchy and keeps the coarsest slice that actually explains its children -
which is also precisely the scope evidence root-cause analysis needs.

Detection stays separate from attribution. This module says "this slice broke,
here is how confident I am". It never says why. That is evidence_engine's job,
and keeping them apart is what lets the system detect something it cannot
explain and refuse to act on it.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy import stats
from sqlalchemy import case, func, literal_column, select
from sqlalchemy.orm import Session

from reversa.config import IST, get_settings
from reversa.models import Payment, PaymentStatus

GLOBAL = "*"

# Significance is necessary but not sufficient. With 4,000 payments in a window
# a 1.2pp drop is significant and operationally meaningless.
MIN_ABSOLUTE_DROP = 0.06
MIN_RELATIVE_DROP = 0.25

CELL_SHRINKAGE = 40.0
EWMA_ALPHA = 0.35

# Window lengths tried at every tick, minutes. Short one is what makes onset
# detection fast; long one is what catches a slow bleed that never trips a
# short window.
SCAN_WINDOWS_MIN = (5, 15, 45)

# Bounds on the fitted beta-binomial concentration. Low kappa = jumpy slice =
# has to move further before we believe it. The ceiling matters: let kappa run to
# 4000 and the test collapses back to the binomial case we were trying to escape.
KAPPA_MIN, KAPPA_MAX = 25.0, 1200.0

# What we assume when we cannot measure dispersion. First version used KAPPA_MAX
# here, which meant the slices with the least evidence got treated as the most
# trustworthy - exactly backwards, and it was most of the false-positive rate.
KAPPA_UNKNOWN = 150.0
DISPERSION_MIN_CELL_N = 15
DISPERSION_MIN_CELLS = 12

# Operational floors. Statistical significance is not the same as "worth waking
# someone up". A 20-payment slice moving 30pp is noise; a genuine incident on a
# slice that thin will show up at its parent, where the volume is.
MIN_WINDOW_VOLUME = 150
MIN_REVENUE_EXPOSED_PAISE = 50_00_000   # Rs 50,000. paise, so 1L rupees = 1e7.


@dataclass(frozen=True, slots=True)
class Slice:
    method: str
    instrument: str

    @property
    def key(self) -> str:
        return f"{self.method}/{self.instrument}"

    @property
    def is_global(self) -> bool:
        return self.method == GLOBAL and self.instrument == GLOBAL

    @property
    def is_method_level(self) -> bool:
        return self.method != GLOBAL and self.instrument == GLOBAL

    def label(self) -> str:
        if self.is_global:
            return "all payments"
        if self.is_method_level:
            return f"{self.method.upper()} (all instruments)"
        return f"{self.method.upper()} / {self.instrument}"


@dataclass(slots=True)
class SliceObservation:
    slice: Slice
    window_start: datetime
    window_end: datetime
    n: int
    successes: int
    failures_by_reason: dict[str, int]
    amount_failed_paise: int

    @property
    def success_rate(self) -> float:
        return self.successes / self.n if self.n else 0.0

    @property
    def window_minutes(self) -> int:
        return int((self.window_end - self.window_start).total_seconds() // 60)


@dataclass(slots=True)
class Signal:
    slice: Slice
    observation: SliceObservation
    baseline_rate: float
    baseline_n: float
    kappa: float
    p_value: float
    q_value: float = 1.0
    ewma_deviation: float = 0.0
    volume_ratio: float = 1.0
    top_reason: str | None = None
    top_reason_share: float = 0.0
    rolled_up_from: tuple[str, ...] = ()

    @property
    def absolute_drop(self) -> float:
        return self.baseline_rate - self.observation.success_rate

    @property
    def relative_drop(self) -> float:
        return self.absolute_drop / self.baseline_rate if self.baseline_rate > 0 else 0.0

    def severity(self, revenue_exposed_paise: int) -> str:
        # magnitude sets the floor, money decides escalation
        if self.absolute_drop >= 0.25 or revenue_exposed_paise >= 20_00_00_00:
            return "critical"
        if self.absolute_drop >= 0.15 or revenue_exposed_paise >= 5_00_00_00:
            return "high"
        if self.absolute_drop >= 0.09:
            return "medium"
        return "low"

    def rationale(self) -> str:
        o = self.observation
        parts = [
            f"{o.slice.label()}: success rate {self.baseline_rate:.1%} -> "
            f"{o.success_rate:.1%} over {o.window_minutes}m ({o.successes}/{o.n}).",
            f"Absolute drop {self.absolute_drop:.1%}, relative {self.relative_drop:.0%}.",
            f"One-sided beta-binomial tail p={self.p_value:.2e}, "
            f"Benjamini-Hochberg q={self.q_value:.2e} across every slice x window "
            f"tested this tick.",
            f"Baseline is the EWMA of this slice at hour "
            f"{o.window_start.astimezone(IST).hour:02d} IST over prior days "
            f"(effective n={self.baseline_n:.0f}), with fitted concentration "
            f"k={self.kappa:.0f} - a slice this jumpy historically needs a move "
            f"this large before it counts.",
        ]
        if self.top_reason:
            parts.append(
                f"{self.top_reason_share:.0%} of failures in the window carry a "
                f"single reason code ({self.top_reason})."
            )
        if self.rolled_up_from:
            parts.append(
                "Reported at this level because "
                f"{len(self.rolled_up_from)} child slices broke together: "
                + ", ".join(self.rolled_up_from) + "."
            )
        return " ".join(parts)


@dataclass(slots=True)
class DetectedIncident:
    slice: Slice   # mutable: consolidate() may promote this to the wider slice
    first_seen: datetime
    last_seen: datetime
    signals: list[Signal] = field(default_factory=list)
    diffuse_members: tuple[str, ...] = ()
    """Set when this is a cluster of unrelated slices degrading together. Its
    presence means the scope is NOT contained - see `cluster_diffuse`."""

    @property
    def is_diffuse(self) -> bool:
        return bool(self.diffuse_members)

    @property
    def peak(self) -> Signal:
        return min(self.signals, key=lambda s: s.q_value)

    @property
    def worst(self) -> Signal:
        return max(self.signals, key=lambda s: s.absolute_drop)


def _slices_for(method: str, instrument: str) -> tuple[Slice, ...]:
    return (Slice(GLOBAL, GLOBAL), Slice(method, GLOBAL), Slice(method, instrument))


def _ist_day_hour(session: Session):
    """SQL expression bucketing created_at into an IST 'YYYY-MM-DDTHH' string.

    Baselines are per hour-of-day *local time*, because that is what drives the
    seasonality - Indian evening peak, bank batch windows. Doing the conversion
    in SQL is what keeps the aggregation server-side. IST has no DST, so a fixed
    +5:30 offset is exact rather than an approximation.
    """
    dialect = session.get_bind().dialect.name
    col = Payment.created_at
    if dialect == "sqlite":
        return func.strftime("%Y-%m-%dT%H", func.datetime(col, "+330 minutes"))
    if dialect in ("postgresql", "postgres"):
        return func.to_char(
            func.timezone("Asia/Kolkata", col), literal_column("'YYYY-MM-DD\"T\"HH24'")
        )
    raise NotImplementedError(
        f"baseline bucketing not implemented for dialect {dialect!r}"
    )


# ---------------------------------------------------------------------------
# stream buffer
# ---------------------------------------------------------------------------


class StreamBuffer:
    """The scan range held in memory, sorted by time.

    Success means CAPTURED - first presentment worked. A payment that failed at
    18:05 and was recovered at 19:30 was still a failure at 18:05, and the
    detector must see it that way. The first version keyed on `status != FAILED`,
    so recovering a cohort silently rewrote the history the detector had already
    reasoned about: re-running detection after an execution showed the UPI
    incident being caught 33 minutes late instead of 3, because 570 of the
    failures it had detected were now marked recovered.

    The scan runs ~230 ticks x 3 window lengths. Doing that as 690 SQL windows
    worked but spent most of the wall clock in the driver, and this has to feel
    instant in front of a judge. One query, then bisect.
    """

    def __init__(self, rows: list[tuple]):
        self.rows = rows
        self.times = [r[0] for r in rows]

    @classmethod
    def load(cls, session: Session, start: datetime, end: datetime) -> "StreamBuffer":
        raw = session.execute(
            select(
                Payment.created_at, Payment.method, Payment.instrument,
                Payment.status, Payment.failure_reason, Payment.amount_paise,
            )
            .where(Payment.created_at >= start, Payment.created_at < end)
            .order_by(Payment.created_at)
        ).all()
        rows = [
            (
                (t if t.tzinfo else t.replace(tzinfo=timezone.utc)),
                m, i, st != PaymentStatus.CAPTURED, fr, amt,
            )
            for t, m, i, st, fr, amt in raw
        ]
        return cls(rows)

    def window(self, start: datetime, end: datetime) -> dict[str, SliceObservation]:
        lo = bisect.bisect_left(self.times, start)
        hi = bisect.bisect_left(self.times, end)
        obs: dict[str, SliceObservation] = {}
        for _, method, instrument, failed, reason, amount in self.rows[lo:hi]:
            for sl in _slices_for(method, instrument):
                o = obs.get(sl.key)
                if o is None:
                    o = obs[sl.key] = SliceObservation(
                        slice=sl, window_start=start, window_end=end, n=0,
                        successes=0, failures_by_reason={}, amount_failed_paise=0,
                    )
                o.n += 1
                if failed:
                    o.amount_failed_paise += amount
                    if reason:
                        o.failures_by_reason[reason] = o.failures_by_reason.get(reason, 0) + 1
                else:
                    o.successes += 1
        return obs


# ---------------------------------------------------------------------------
# baselines
# ---------------------------------------------------------------------------


class BaselineModel:
    """Per (slice, hour) baseline rates plus a per-slice dispersion estimate."""

    def __init__(self) -> None:
        self.cell: dict[tuple[str, int], tuple[float, float]] = {}
        self.slice_level: dict[str, tuple[float, float]] = {}
        self.global_level: tuple[float, float] = (0.9, 1.0)
        self.kappa: dict[str, float] = {}

    @classmethod
    def build(cls, session: Session, *, until: datetime) -> "BaselineModel":
        """Fit baselines from history.

        Success is CAPTURED only - see StreamBuffer. Baselines have to be built
        on first-attempt outcomes or a merchant who recovers well appears to have
        had no incidents at all.

        Aggregated in SQL, not in Python. The first version pulled every
        historical payment into memory - 60k rows cost 33MB, which extrapolates
        to about 5.5GB on a merchant with 10M payments, i.e. it would simply
        fall over. Grouping by (method, instrument, IST day-hour) in the database
        turns that into ~13k rows regardless of how much history exists, because
        the cell count is bounded by instruments x days x hours.
        """
        model = cls()
        bucket = _ist_day_hour(session)

        rows = session.execute(
            select(
                Payment.method,
                Payment.instrument,
                bucket.label("bucket"),
                func.count().label("n"),
                func.sum(
                    case((Payment.status == PaymentStatus.CAPTURED, 1), else_=0)
                ).label("ok"),
            )
            .where(Payment.created_at < until)
            .group_by(Payment.method, Payment.instrument, bucket)
        ).all()

        daily: dict[str, dict[tuple[str, int], list[float]]] = defaultdict(
            lambda: defaultdict(lambda: [0.0, 0.0])
        )
        slice_tot: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        g_tot = [0.0, 0.0]

        for method, instrument, bucket_str, n, ok in rows:
            day, _, hour_s = str(bucket_str).partition("T")
            hour = int(hour_s)
            n, ok = float(n), float(ok or 0)
            cellday = daily[day]
            for sl in _slices_for(method, instrument):
                cell = cellday[(sl.key, hour)]
                cell[0] += n
                cell[1] += ok
                slice_tot[sl.key][0] += n
                slice_tot[sl.key][1] += ok
            g_tot[0] += n
            g_tot[1] += ok

        # EWMA across days, recent days weighted heaviest
        acc: dict[tuple[str, int], list[float]] = {}
        for day in sorted(daily):
            for cell, (n, s) in daily[day].items():
                if n <= 0:
                    continue
                rate = s / n
                if cell not in acc:
                    acc[cell] = [rate, n]
                else:
                    acc[cell][0] = EWMA_ALPHA * rate + (1 - EWMA_ALPHA) * acc[cell][0]
                    acc[cell][1] = EWMA_ALPHA * n + (1 - EWMA_ALPHA) * acc[cell][1]

        model.cell = {k: (v[0], v[1]) for k, v in acc.items()}
        model.slice_level = {k: (v[1] / v[0], v[0]) for k, v in slice_tot.items() if v[0]}
        model.global_level = (g_tot[1] / g_tot[0], g_tot[0]) if g_tot[0] else (0.9, 1.0)
        model.kappa = _fit_dispersion(daily, model.slice_level)
        return model

    def rate_for(self, sl: Slice, hour: int) -> tuple[float, float]:
        g_rate, _ = self.global_level
        s_rate, s_n = self.slice_level.get(sl.key, (g_rate, 0.0))
        s_rate = (s_rate * s_n + g_rate * CELL_SHRINKAGE) / (s_n + CELL_SHRINKAGE)

        c_rate, c_n = self.cell.get((sl.key, hour), (s_rate, 0.0))
        rate = (c_rate * c_n + s_rate * CELL_SHRINKAGE) / (c_n + CELL_SHRINKAGE)
        return float(np.clip(rate, 0.01, 0.999)), c_n + CELL_SHRINKAGE

    def concentration(self, sl: Slice) -> float:
        return self.kappa.get(sl.key, 200.0)


def _fit_dispersion(
    daily: dict[str, dict[tuple[str, int], list[float]]],
    slice_level: dict[str, tuple[float, float]],
) -> dict[str, float]:
    """Method-of-moments beta concentration per slice.

    Total spread of a slice's historical window rates is binomial sampling plus
    genuine wander. Subtract the binomial part; what's left is the wander we have
    to price in. kappa = mu(1-mu)/var_extra - 1. Slices with no measurable
    wander keep a high kappa and behave close to the old binomial test, which is
    correct - some slices really are that stable.
    """
    per_slice: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for cells in daily.values():
        for (skey, _hour), (n, s) in cells.items():
            if n >= DISPERSION_MIN_CELL_N:
                per_slice[skey].append((n, s / n))

    out: dict[str, float] = {}
    for skey, obs in per_slice.items():
        if len(obs) < DISPERSION_MIN_CELLS:
            # not enough history to claim this slice is stable
            out[skey] = KAPPA_UNKNOWN
            continue
        mu = float(np.clip(slice_level.get(skey, (0.9, 0.0))[0], 0.01, 0.99))
        rates = np.array([r for _, r in obs])
        ns = np.array([n for n, _ in obs], dtype=float)

        total_var = float(np.mean((rates - mu) ** 2))
        binomial_var = float(np.mean(mu * (1 - mu) / ns))
        extra = total_var - binomial_var

        # We cannot resolve dispersion below the sampling error of the variance
        # estimate itself, which for m cells is roughly var*sqrt(2/m). Clamping
        # to that floor is what stops a slice that merely *looks* perfectly
        # stable on a handful of windows from claiming infinite confidence.
        floor = binomial_var * float(np.sqrt(2.0 / len(obs)))
        extra = max(extra, floor)

        raw = mu * (1 - mu) / extra - 1.0
        # shrink toward the conservative default by how much history backs it
        w = len(obs) / (len(obs) + DISPERSION_MIN_CELLS)
        out[skey] = float(np.clip(w * raw + (1 - w) * KAPPA_UNKNOWN, KAPPA_MIN, KAPPA_MAX))
    return out


# ---------------------------------------------------------------------------
# testing
# ---------------------------------------------------------------------------


def _benjamini_hochberg(pvals: list[float]) -> list[float]:
    """BH-adjusted q-values, input order preserved.

    Step-up with the running-minimum monotonicity fix - without it a larger p can
    come back with a smaller q, which reads as nonsense in the UI.
    """
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [1.0] * m
    running = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        running = min(running, pvals[i] * m / (rank + 1))
        q[i] = min(1.0, running)
    return q


def _beta_binomial_tail(successes: int, n: int, rate: float, kappa: float) -> float:
    """P(K <= successes) under BetaBinom(n, rate*kappa, (1-rate)*kappa)."""
    a = max(rate * kappa, 1e-3)
    b = max((1.0 - rate) * kappa, 1e-3)
    return float(stats.betabinom.cdf(successes, n, a, b))


def test_tick(
    buffer: StreamBuffer,
    baseline: BaselineModel,
    tick_end: datetime,
    *,
    min_volume: int,
    fdr_q: float,
    windows: tuple[int, ...] = SCAN_WINDOWS_MIN,
) -> tuple[list[Signal], list[str]]:
    """Scan statistic at one instant: every slice x every window length."""
    candidates: list[Signal] = []
    skipped: list[str] = []
    best_by_slice: dict[str, Signal] = {}
    obs_by_window: dict[int, dict[str, SliceObservation]] = {}

    for minutes in windows:
        w_start = tick_end - timedelta(minutes=minutes)
        obs = buffer.window(w_start, tick_end)
        obs_by_window[minutes] = obs
        hour = w_start.astimezone(IST).hour

        for o in obs.values():
            if o.n < min_volume:
                skipped.append(f"{o.slice.key}@{minutes}m (n={o.n})")
                continue
            rate, base_n = baseline.rate_for(o.slice, hour)
            kappa = baseline.concentration(o.slice)
            p = _beta_binomial_tail(o.successes, o.n, rate, kappa)

            top_reason, top_share = None, 0.0
            failed = o.n - o.successes
            if o.failures_by_reason and failed:
                top_reason, cnt = max(o.failures_by_reason.items(), key=lambda kv: kv[1])
                top_share = cnt / failed

            sig = Signal(
                slice=o.slice, observation=o, baseline_rate=rate, baseline_n=base_n,
                kappa=kappa, p_value=p, ewma_deviation=o.success_rate - rate,
                volume_ratio=o.n / base_n if base_n else 1.0,
                top_reason=top_reason, top_reason_share=top_share,
            )
            candidates.append(sig)
            prev = best_by_slice.get(o.slice.key)
            if prev is None or sig.p_value < prev.p_value:
                best_by_slice[o.slice.key] = sig

    # FDR over every test performed at this tick, not just the winners
    qs = _benjamini_hochberg([c.p_value for c in candidates])
    for c, q in zip(candidates, qs):
        c.q_value = q

    alerting = [
        s for s in best_by_slice.values()
        if s.q_value <= fdr_q
        and s.absolute_drop >= MIN_ABSOLUTE_DROP
        and s.relative_drop >= MIN_RELATIVE_DROP
        and s.observation.amount_failed_paise >= MIN_REVENUE_EXPOSED_PAISE
    ]
    return _rollup(alerting, obs_by_window), skipped


def _rollup(alerting: list[Signal], obs_by_window: dict[int, dict[str, SliceObservation]]) -> list[Signal]:
    """Report the coarsest slice that explains its children.

    A PSP outage breaks every UPI handle at once. Seven instrument-level
    incidents is noise, and summing their revenue exposure across the parent and
    the children double-counts the money. So: if a method-level slice is alerting
    and its alerting children cover most of that method's volume, keep the
    method and drop the children. Same one level up for global.

    The children aren't thrown away - they're recorded on the surviving signal as
    `rolled_up_from`, because "all seven handles, not one" is exactly the scope
    evidence that separates a PSP problem from a single-bank problem.
    """
    by_key = {s.slice.key: s for s in alerting}
    dropped: set[str] = set()

    def volume(key: str, minutes: int) -> int:
        o = obs_by_window.get(minutes, {}).get(key)
        return o.n if o else 0

    # instrument -> method
    for sig in list(alerting):
        if not sig.slice.is_method_level:
            continue
        minutes = sig.observation.window_minutes
        children = [
            s for s in alerting
            if s.slice.method == sig.slice.method and not s.slice.is_method_level
            and not s.slice.is_global
        ]
        if len(children) < 2:
            continue
        parent_n = volume(sig.slice.key, minutes) or 1
        covered = sum(volume(c.slice.key, minutes) for c in children)
        if covered / parent_n >= 0.5:
            sig.rolled_up_from = tuple(sorted(c.slice.instrument for c in children))
            dropped.update(c.slice.key for c in children)

    # method -> global
    g = by_key.get(Slice(GLOBAL, GLOBAL).key)
    if g is not None:
        methods = [s for s in alerting if s.slice.is_method_level and s.slice.key not in dropped]
        if len(methods) >= 2:
            g.rolled_up_from = tuple(sorted(s.slice.method for s in methods))
            dropped.update(s.slice.key for s in methods)
        else:
            # a global alert that's really just one method breaking is not a
            # global incident, it's that method's incident
            dropped.add(g.slice.key)

    return [s for s in alerting if s.slice.key not in dropped]


def _is_ancestor(parent: Slice, child: Slice) -> bool:
    if parent.key == child.key:
        return False
    if parent.is_global:
        return True
    return parent.is_method_level and parent.method == child.method


def consolidate(incidents: list[DetectedIncident]) -> list[DetectedIncident]:
    """Merge parent/child incidents whose windows overlap.

    `_rollup` works within a single tick, which is not enough: a card degradation
    can surface at card/* on one tick and at card/MASTERCARD three ticks later,
    once the narrower slice has accumulated volume. Those are one incident, and
    reporting both also double-counts the revenue.

    Keeps whichever side carries the larger drop, absorbs the other's signals,
    and widens the window to cover both.
    """
    incidents = sorted(incidents, key=lambda i: i.first_seen)
    out: list[DetectedIncident] = []

    for inc in incidents:
        merged = False
        for kept in out:
            overlap = not (inc.last_seen < kept.first_seen or inc.first_seen > kept.last_seen)
            related = (
                inc.slice.key == kept.slice.key
                or _is_ancestor(kept.slice, inc.slice)
                or _is_ancestor(inc.slice, kept.slice)
            )
            if not (overlap and related):
                continue
            if inc.worst.absolute_drop > kept.worst.absolute_drop:
                kept.slice = inc.slice
            kept.signals.extend(inc.signals)
            kept.first_seen = min(kept.first_seen, inc.first_seen)
            kept.last_seen = max(kept.last_seen, inc.last_seen)
            merged = True
            break
        if not merged:
            out.append(inc)

    return sorted(out, key=lambda i: i.first_seen)


# A degradation touching this many unrelated slices at once has no containable
# scope. Three is the point at which "one bank" stops being a plausible story.
DIFFUSE_MIN_SLICES = 3
DIFFUSE_WINDOW = timedelta(minutes=20)


def cluster_diffuse(incidents: list[DetectedIncident]) -> list[DetectedIncident]:
    """Group simultaneous degradations across unrelated slices into one finding.

    When a PSP breaks, every UPI handle goes with it and `consolidate` folds
    them into UPI/*, because they share a parent. When something upstream of
    everything degrades - merchant-side latency, a shared gateway hop - the
    damage lands on slices with no common parent at all: some UPI handles, some
    netbanking, some cards. Those refuse to consolidate, and reporting them as
    five separate incidents is both noisy and actively misleading, because the
    interesting fact about them is precisely that they have no shared scope.

    So they become one incident carrying every member slice. Downstream, an
    incident with `diffuse_members` is one whose root cause the evidence cannot
    attribute - which is exactly the case where automation should stop and ask
    for a human.
    """
    if len(incidents) < DIFFUSE_MIN_SLICES:
        return incidents

    remaining = sorted(incidents, key=lambda i: i.first_seen)
    out: list[DetectedIncident] = []

    while remaining:
        seed = remaining.pop(0)
        window_end = seed.first_seen + DIFFUSE_WINDOW
        cluster = [seed]
        rest = []
        for other in remaining:
            related = (
                _is_ancestor(seed.slice, other.slice)
                or _is_ancestor(other.slice, seed.slice)
                or seed.slice.method == other.slice.method
            )
            if not related and other.first_seen <= window_end:
                cluster.append(other)
            else:
                rest.append(other)
        remaining = rest

        if len(cluster) < DIFFUSE_MIN_SLICES:
            out.extend(cluster)
            continue

        merged = DetectedIncident(
            slice=Slice(GLOBAL, GLOBAL),
            first_seen=min(c.first_seen for c in cluster),
            last_seen=max(c.last_seen for c in cluster),
            signals=[s for c in cluster for s in c.signals],
            diffuse_members=tuple(sorted(c.slice.key for c in cluster)),
        )
        out.append(merged)

    return sorted(out, key=lambda i: i.first_seen)


def scan(
    session: Session,
    start: datetime,
    end: datetime,
    *,
    tick_minutes: int = 5,
    baseline: BaselineModel | None = None,
    buffer: StreamBuffer | None = None,
) -> tuple[list[DetectedIncident], dict]:
    """Walk a range tick by tick, exactly as a live detector would.

    Deliberately not one batch query over the whole range - that leaks the future
    into detection and makes any latency claim meaningless. Each tick sees only
    its trailing windows, so "caught it N minutes after onset" is a real number.
    """
    s = get_settings()
    baseline = baseline or BaselineModel.build(session, until=start)
    # windows reach back before `start`, so the buffer has to as well
    buffer = buffer or StreamBuffer.load(
        session, start - timedelta(minutes=max(SCAN_WINDOWS_MIN)), end
    )

    open_incidents: dict[str, DetectedIncident] = {}
    closed: list[DetectedIncident] = []
    skipped_counts: dict[str, int] = defaultdict(int)
    ticks = 0

    close_after = timedelta(minutes=tick_minutes * 2)
    cursor = start + timedelta(minutes=tick_minutes)
    while cursor <= end:
        alerting, skipped = test_tick(
            buffer, baseline, cursor,
            min_volume=max(s.sentinel_min_volume, MIN_WINDOW_VOLUME),
            fdr_q=s.sentinel_fdr_q,
        )
        ticks += 1
        for sk in skipped:
            skipped_counts[sk.split("@")[0]] += 1

        hot = set()
        for sig in alerting:
            key = sig.slice.key
            hot.add(key)
            inc = open_incidents.get(key)
            if inc is None:
                open_incidents[key] = DetectedIncident(sig.slice, cursor, cursor, [sig])
            else:
                inc.last_seen = cursor
                inc.signals.append(sig)

        for key in list(open_incidents):
            if key not in hot and cursor - open_incidents[key].last_seen > close_after:
                closed.append(open_incidents.pop(key))

        cursor += timedelta(minutes=tick_minutes)

    closed.extend(open_incidents.values())
    closed = cluster_diffuse(consolidate(closed))

    return closed, {
        "ticks": ticks,
        "tick_minutes": tick_minutes,
        "scan_windows_min": list(SCAN_WINDOWS_MIN),
        "fdr_q": s.sentinel_fdr_q,
        "min_volume": s.sentinel_min_volume,
        "slices_skipped_thin": dict(skipped_counts),
        "incidents": len(closed),
    }
