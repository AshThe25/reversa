"""Rebuild the world from scratch. `python -m scripts.seed_world --scale demo`"""

from __future__ import annotations

import argparse
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.db import reset_db, session_scope
from reversa.world import params as P
from reversa.world.generator import generate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default=P.DEFAULT_SCALE, choices=list(P.SCALE_PRESETS))
    ap.add_argument("--seed", type=int, default=20260826)
    args = ap.parse_args()

    reset_db()
    with session_scope() as s:
        stats = generate(s, seed=args.seed, scale=args.scale)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
