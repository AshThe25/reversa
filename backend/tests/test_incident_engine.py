"""Detector tests.

Mostly built on a hand-made stream rather than the full world, so each one pins
a single behaviour and the suite stays fast.
"""

import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.config import IST
from reversa.engines import incident_engine as IE

T0 = datetime(2026, 8, 26, 12, 0, tzinfo=IST).astimezone(timezone.utc)


def _stream(spec):
    """spec: list of (offset_min, method, instrument, n, fail_rate, amount)."""
    rows = []
    for offset, method, instrument, n, fail_rate, amount in spec:
        n_fail = int(round(n * fail_rate))
        for i in range(n):
            rows.append((
                T0 + timedelta(minutes=offset, seconds=(i % 60)),
                method, instrument, i < n_fail,
                "bank_technical_decline" if i < n_fail else None,
                amount,
            ))
    rows.sort(key=lambda r: r[0])
    return IE.StreamBuffer(rows)


def _baseline(rate=0.92, kappa=800.0, slices=("*/*", "upi/*", "upi/okhdfcbank")):
    b = IE.BaselineModel()
    b.global_level = (rate, 50_000.0)
    b.slice_level = {k: (rate, 20_000.0) for k in slices}
    b.cell = {(k, h): (rate, 5_000.0) for k in slices for h in range(24)}
    b.kappa = {k: kappa for k in slices}
    return b


# --- multiple comparisons ---------------------------------------------------

def test_bh_matches_hand_computation():
    q = IE._benjamini_hochberg([0.001, 0.02, 0.3, 0.7])
    assert q == pytest.approx([0.004, 0.04, 0.4, 0.7], rel=1e-6)


def test_bh_is_monotone_in_p():
    """Without the running-minimum step-up you can get a larger p with a smaller
    q, which reads as nonsense in the UI."""
    ps = [0.001, 0.009, 0.011, 0.04, 0.2, 0.9]
    qs = IE._benjamini_hochberg(ps)
    assert all(a <= b + 1e-12 for a, b in zip(qs, qs[1:]))


def test_bh_of_pure_noise_alerts_on_almost_nothing():
    import numpy as np
    rng = np.random.default_rng(3)
    ps = list(rng.uniform(size=500))          # null is true everywhere
    qs = IE._benjamini_hochberg(ps)
    assert sum(q <= 0.05 for q in qs) <= 2


# --- overdispersion ---------------------------------------------------------

def test_beta_binomial_is_more_forgiving_than_binomial_on_a_jumpy_slice():
    """The whole reason for the beta-binomial. Same observation, same baseline:
    a slice known to wander should not be flagged as hard as a stable one."""
    from scipy import stats
    k, n, rate = 820, 1000, 0.92
    binom_p = float(stats.binomtest(k, n, rate, alternative="less").pvalue)
    jumpy = IE._beta_binomial_tail(k, n, rate, kappa=30.0)
    stable = IE._beta_binomial_tail(k, n, rate, kappa=1200.0)
    assert jumpy > stable > binom_p / 10
    assert jumpy > binom_p


def test_thin_history_gets_a_conservative_kappa_not_a_confident_one():
    """Regression. First version set kappa to the ceiling whenever it measured
    no excess variance, so the slices with the least evidence were treated as the
    most trustworthy. That was most of the false-positive rate."""
    daily = {
        f"2026-08-{d:02d}": {("upi/rare", 12): [20.0, 19.0]}
        for d in range(1, 5)   # only 4 cells, below DISPERSION_MIN_CELLS
    }
    kappa = IE._fit_dispersion(daily, {"upi/rare": (0.95, 80.0)})
    assert kappa["upi/rare"] == IE.KAPPA_UNKNOWN
    assert kappa["upi/rare"] < IE.KAPPA_MAX


def test_a_genuinely_stable_slice_still_earns_a_high_kappa():
    daily = {
        f"2026-08-{d:02d}": {("upi/steady", h): [400.0, 368.0] for h in range(10, 16)}
        for d in range(1, 9)
    }
    kappa = IE._fit_dispersion(daily, {"upi/steady": (0.92, 20_000.0)})
    assert kappa["upi/steady"] > IE.KAPPA_UNKNOWN


# --- detection --------------------------------------------------------------

def test_a_real_collapse_is_detected():
    buf = _stream([
        (m, "upi", "okhdfcbank", 400, 0.08, 250_000) for m in range(-45, 0, 5)
    ] + [
        (m, "upi", "okhdfcbank", 400, 0.55, 250_000) for m in range(0, 20, 5)
    ])
    alerting, _ = IE.test_tick(
        buf, _baseline(), T0 + timedelta(minutes=15),
        min_volume=IE.MIN_WINDOW_VOLUME, fdr_q=0.05,
    )
    assert alerting
    sig = alerting[0]
    assert sig.absolute_drop > 0.2
    assert sig.top_reason == "bank_technical_decline"


def test_normal_variation_does_not_alert():
    buf = _stream([
        (m, "upi", "okhdfcbank", 400, r, 250_000)
        for m, r in zip(range(-45, 20, 5), [.07, .09, .08, .10, .07, .09, .08, .11, .08, .09, .07, .10, .08])
    ])
    alerting, _ = IE.test_tick(
        buf, _baseline(), T0 + timedelta(minutes=15),
        min_volume=IE.MIN_WINDOW_VOLUME, fdr_q=0.05,
    )
    assert not alerting


def test_thin_slices_are_skipped_and_reported_not_silently_passed():
    buf = _stream([(m, "upi", "okhdfcbank", 6, 0.9, 250_000) for m in range(-45, 20, 5)])
    alerting, skipped = IE.test_tick(
        buf, _baseline(), T0 + timedelta(minutes=15),
        min_volume=IE.MIN_WINDOW_VOLUME, fdr_q=0.05,
    )
    assert not alerting
    assert any("upi/okhdfcbank" in s for s in skipped)


def test_significant_but_trivial_drops_are_not_incidents():
    """With enough volume a 2pp move is significant and operationally useless."""
    buf = _stream([
        (m, "upi", "okhdfcbank", 4000, 0.10, 250_000) for m in range(-45, 20, 5)
    ])
    alerting, _ = IE.test_tick(
        buf, _baseline(rate=0.92), T0 + timedelta(minutes=15),
        min_volume=IE.MIN_WINDOW_VOLUME, fdr_q=0.05,
    )
    assert not alerting, "2pp drop on huge n should fail the effect-size floor"


def test_short_window_catches_a_sharp_onset_a_long_one_would_dilute():
    """Why the scan statistic exists: three minutes into an outage, a 45m window
    is still 93% healthy traffic."""
    buf = _stream(
        [(m, "upi", "okhdfcbank", 500, 0.08, 250_000) for m in range(-45, 0, 5)]
        + [(0, "upi", "okhdfcbank", 500, 0.75, 250_000)]
    )
    tick = T0 + timedelta(minutes=5)
    long_only, _ = IE.test_tick(buf, _baseline(), tick, min_volume=IE.MIN_WINDOW_VOLUME,
                                fdr_q=0.05, windows=(45,))
    short_too, _ = IE.test_tick(buf, _baseline(), tick, min_volume=IE.MIN_WINDOW_VOLUME,
                                fdr_q=0.05, windows=(5, 15, 45))
    assert not long_only
    assert short_too


# --- hierarchy --------------------------------------------------------------

def test_a_psp_wide_outage_reports_once_at_method_level():
    """Seven UPI handles breaking together is one incident, not seven - and
    summing them across parent and children would triple-count the money."""
    handles = ["okhdfcbank", "oksbi", "okicici", "okaxis", "paytm"]
    base = _baseline(slices=["*/*", "upi/*"] + [f"upi/{h}" for h in handles])
    spec = []
    for m in range(-45, 0, 5):
        spec += [(m, "upi", h, 200, 0.08, 250_000) for h in handles]
    for m in range(0, 20, 5):
        spec += [(m, "upi", h, 200, 0.60, 250_000) for h in handles]

    alerting, _ = IE.test_tick(_stream(spec), base, T0 + timedelta(minutes=15),
                               min_volume=IE.MIN_WINDOW_VOLUME, fdr_q=0.05)
    keys = {s.slice.key for s in alerting}
    assert keys == {"upi/*"}, keys
    assert len(alerting[0].rolled_up_from) == len(handles)


def test_one_bad_handle_stays_at_instrument_level():
    """The mirror case. Rolling this up to UPI/* would lose the fact that six
    other handles are fine, which is the whole difference between a PSP problem
    and a single-bank problem."""
    handles = ["okhdfcbank", "oksbi", "okicici", "okaxis", "paytm"]
    base = _baseline(slices=["*/*", "upi/*"] + [f"upi/{h}" for h in handles])
    spec = []
    for m in range(-45, 20, 5):
        for h in handles:
            rate = 0.08 if (h != "oksbi" or m < 0) else 0.75
            spec.append((m, "upi", h, 400, rate, 250_000))

    alerting, _ = IE.test_tick(_stream(spec), base, T0 + timedelta(minutes=15),
                               min_volume=IE.MIN_WINDOW_VOLUME, fdr_q=0.05)
    assert {s.slice.key for s in alerting} == {"upi/oksbi"}


def test_consolidate_merges_parent_and_child_across_ticks():
    """rollup only works within one tick. A card degradation can surface at
    card/* first and card/MASTERCARD three ticks later once the narrow slice has
    volume - those are one incident."""
    def inc(key, start_min, end_min, drop):
        method, instrument = key.split("/")
        sl = IE.Slice(method, instrument)
        obs = IE.SliceObservation(sl, T0, T0 + timedelta(minutes=15), 1000,
                                  int(1000 * (0.9 - drop)), {}, 5_00_00_000)
        sig = IE.Signal(slice=sl, observation=obs, baseline_rate=0.90,
                        baseline_n=5000, kappa=800, p_value=1e-9, q_value=1e-8)
        return IE.DetectedIncident(sl, T0 + timedelta(minutes=start_min),
                                   T0 + timedelta(minutes=end_min), [sig])

    merged = IE.consolidate([
        inc("card/*", 0, 20, 0.30),
        inc("card/MASTERCARD", 15, 35, 0.42),
        inc("upi/oksbi", 200, 210, 0.30),   # unrelated, must survive
    ])
    keys = [i.slice.key for i in merged]
    assert len(merged) == 2
    assert "upi/oksbi" in keys
    # the bigger drop wins the label, and the window covers both
    card = next(i for i in merged if i.slice.key == "card/MASTERCARD")
    assert card.first_seen == T0
    assert card.last_seen == T0 + timedelta(minutes=35)


def test_detection_never_uses_data_from_after_the_tick():
    """If a window could see the future, every latency number in the evaluation
    would be a lie."""
    buf = _stream(
        [(m, "upi", "okhdfcbank", 500, 0.08, 250_000) for m in range(-45, 0, 5)]
        + [(m, "upi", "okhdfcbank", 500, 0.80, 250_000) for m in range(10, 40, 5)]
    )
    quiet, _ = IE.test_tick(buf, _baseline(), T0 + timedelta(minutes=5),
                            min_volume=IE.MIN_WINDOW_VOLUME, fdr_q=0.05)
    assert not quiet, "alerted before the degradation had happened"

    later, _ = IE.test_tick(buf, _baseline(), T0 + timedelta(minutes=25),
                            min_volume=IE.MIN_WINDOW_VOLUME, fdr_q=0.05)
    assert later
