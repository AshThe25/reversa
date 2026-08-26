"""Cached engine state.

Fitting the counterfactual model and scanning the day are the two expensive
operations in the system (roughly 0.4s and 1.5s). Doing either per request would
make the dashboard feel broken, and doing them concurrently on first load would
have several requests fitting the same model at once.

So: fit once, behind a lock, hold it until something invalidates it. Not a
general-purpose cache - a deliberately small piece of process state with one
job, which is what a modular monolith should have instead of a Redis dependency
it does not need yet.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from reversa.engines import incident_engine as IE
from reversa.engines import pipeline as PL
from reversa.engines.cohort_engine import CohortBuild, build_cohort
from reversa.engines.counterfactual_engine import CounterfactualModel

log = logging.getLogger(__name__)


@dataclass
class EngineState:
    model: CounterfactualModel | None = None
    detected: list[IE.DetectedIncident] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    clock: PL.DemoClock | None = None
    cohorts: dict[str, CohortBuild] = field(default_factory=dict)
    built_at: float = 0.0
    fit_ms: float = 0.0
    scan_ms: float = 0.0

    @property
    def ready(self) -> bool:
        return self.model is not None and self.clock is not None


_state = EngineState()
_lock = threading.Lock()


def get(session: Session, *, force: bool = False) -> EngineState:
    """Return warm state, building it if needed. Safe under concurrency."""
    if _state.ready and not force:
        return _state

    with _lock:
        if _state.ready and not force:      # another thread got there first
            return _state

        clock = PL.clock(session)

        t0 = time.perf_counter()
        model = CounterfactualModel.fit(session, until=clock.live_day)
        fit_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        detected, diag = IE.scan(session, clock.live_day, clock.now)
        scan_ms = (time.perf_counter() - t1) * 1000

        _state.model = model
        _state.detected = detected
        _state.diagnostics = diag
        _state.clock = clock
        _state.cohorts = {}
        _state.built_at = time.time()
        _state.fit_ms = fit_ms
        _state.scan_ms = scan_ms

        log.info("engine warm: fit %.0fms, scan %.0fms, %d incidents",
                 fit_ms, scan_ms, len(detected))
        return _state


def cohort_for(session: Session, incident_id: str) -> tuple[IE.DetectedIncident, CohortBuild]:
    """Cohort for a persisted incident id, memoised per process."""
    state = get(session)
    detected = detected_by_id(session, incident_id)
    if detected is None:
        raise KeyError(incident_id)

    cached = state.cohorts.get(incident_id)
    if cached is None:
        cached = build_cohort(session, detected, state.model, now=state.clock.now)
        state.cohorts[incident_id] = cached
    return detected, cached


def detected_by_id(session: Session, incident_id: str) -> IE.DetectedIncident | None:
    """Map a persisted incident row back to the detector object behind it.

    Persisted ids are a hash of (slice, first_seen), so this is a lookup rather
    than a search - and it stays correct if the scan order changes.
    """
    state = get(session)
    for d in state.detected:
        if PL._id("inc", f"{d.slice.key}|{d.first_seen.isoformat()}") == incident_id:
            return d
    return None


def invalidate() -> None:
    with _lock:
        _state.model = None
        _state.detected = []
        _state.cohorts = {}
        _state.clock = None
