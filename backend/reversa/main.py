"""Application entry point.

Middleware order is load-bearing and reads bottom-up in Starlette: the last one
added is the outermost. So request context wraps everything (an error inside the
rate limiter still gets a request id and a clean 500), then body limit, then
rate limiting, then CORS, then security headers closest to the response.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from reversa.api.middleware import (
    BodyLimitMiddleware, RateLimitMiddleware, RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from reversa.api.routes import router
from reversa.config import get_settings
from reversa.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("reversa")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    log.info(
        "reversa up | razorpay=%s | llm=%s | demo_sessions=%s",
        "razorpay test" if settings.has_razorpay else "simulation",
        "anthropic" if settings.has_llm else "deterministic",
        settings.allow_demo_sessions,
    )

    if settings.session_secret_is_ephemeral:
        log.warning(
            "session secret generated for this process - sessions will not "
            "survive a restart and will not validate across replicas. Set "
            "REVERSA_SESSION_SECRET before running more than one worker."
        )

    if settings.warm_on_startup:
        # Fitting the estimator and scanning the day costs ~2.3s. Paying it on a
        # background thread means the first person to open the dashboard doesn't,
        # which matters when that person is judging it.
        def _warm() -> None:
            try:
                from reversa.api import state as engine_state
                from reversa.db import session_scope

                with session_scope() as db:
                    engine_state.get(db)
            except Exception:
                log.exception("startup warm-up failed; first request will be slow")

            # Prove the Razorpay connection rather than asserting it.
            #
            # A read-only call to the downtime feed on boot means the System
            # panel can show a live call count that came from the real API,
            # without spending a Payment Link from a budget of twenty-four to
            # do it. If credentials are absent the adapter is in simulation and
            # this is skipped entirely.
            try:
                from reversa.adapters.razorpay_adapter import get_client

                client = get_client()
                if not client.offline:
                    feed = client.fetch_downtimes()
                    log.info("razorpay reachable: %d downtime records", len(feed))
            except Exception:
                log.warning("razorpay verification call failed; adapter still usable",
                            exc_info=True)

        threading.Thread(target=_warm, name="reversa-warm", daemon=True).start()

    yield


def _docs_open(settings) -> bool:
    """Whether to publish the interactive API docs.

    Open on a simulation, because the point of this build is that someone can
    read exactly what it does. Closed the moment real Razorpay credentials are
    configured - at that point the same page is a map of the attack surface -
    unless REVERSA_EXPOSE_DOCS says otherwise on purpose.
    """
    if settings.has_razorpay:
        return settings.model_fields_set.__contains__("expose_docs") and settings.expose_docs
    return settings.expose_docs


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        lifespan=lifespan,
        title="Reversa",
        version="0.1.0",
        description=(
            "Counterfactual revenue recovery. Detect revenue at risk, simulate "
            "alternative futures before touching a customer, allocate scarce "
            "intervention capacity by expected incremental value, and measure "
            "what the intervention actually caused against a randomised holdout."
        ),
        docs_url="/api/docs" if _docs_open(settings) else None,
        openapi_url="/api/openapi.json" if _docs_open(settings) else None,
    )

    # Order matters, and it is the reverse of the reading order: the last one
    # added is the outermost. Security headers go on last so they are outermost,
    # because the responses that most need them are the ones that never reach a
    # route - the limiter's 429, the body cap's 413, and the error boundary's
    # 500. Registered inside those, it decorated only the happy path, and an
    # error body went out with no nosniff and no no-store.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,   # never "*" - see config
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(router)

    @app.exception_handler(404)
    async def not_found(request: Request, exc):  # noqa: ANN001
        return JSONResponse(status_code=404, content={"error": "not_found"})

    return app


app = create_app()
