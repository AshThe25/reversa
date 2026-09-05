# Backend image for Render.
#
# The world is seeded during the build rather than on boot. Seeding takes about
# thirty seconds and the free tier's disk does not survive a restart, so seeding
# at start would make every cold wake a thirty-second wait for whoever happened
# to open the link. Baked in, a cold start is the container coming up plus the
# ~4s estimator fit, and the fit already runs on a background thread.
#
# The cost is image size - the demo world is a 320MB SQLite file. That is the
# right trade here: the numbers on screen are the argument, and shrinking the
# world to save a layer would change them.

FROM python:3.11-slim AS build

WORKDIR /app

# Build-time only. scipy and scikit-learn ship wheels for this platform, so
# nothing here needs a compiler, but SQLAlchemy's C extensions do.
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY .env.example ./.env.example

# reversa.db lands at the repo root, which is where config.py anchors it - the
# path is derived from the package location, not the working directory, so this
# is the same file the app opens at runtime.
# Render's free instance is 512MB of RAM and imports alone cost about 125MB
# before a single row is read. `demo` is the scale the README's figures and the
# test suite are pinned to, so it is the default. If the instance is OOM-killed
# on boot, set WORLD_SCALE=test_live in the service's environment and redeploy -
# 4,000 customers instead of 6,000, still enough traffic for the detector to
# fire, smaller numbers on screen.
ARG WORLD_SCALE=demo
RUN cd backend && PYTHONPATH=. python -m scripts.seed_world --scale "${WORLD_SCALE}"

# --- runtime ---------------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=build /usr/local/bin /usr/local/bin
COPY --from=build /app /app

# Render provides PORT. Single worker on purpose: the rate limiter is an
# in-memory token bucket and the session secret is per process, so a second
# worker would make the limiter twice as loose and break sessions across
# workers. Both are documented in the README as the first things to replace
# behind a load balancer.
CMD ["sh", "-c", "cd backend && exec python -m uvicorn reversa.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
