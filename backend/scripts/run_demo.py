"""Run the whole loop against the seeded world and print what happened.

`python -m scripts.run_demo`. This is the deterministic scenario the pitch
follows, and it is also the smoke test - if this prints clean numbers, detection
through measurement is working end to end.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.db import session_scope
from reversa.engines import incident_engine as IE
from reversa.engines import pipeline as PL
from reversa.engines import simulation_engine as SIM
from reversa.engines.audit_engine import verify_chain
from reversa.engines.cohort_engine import build_cohort
from reversa.engines.counterfactual_engine import CounterfactualModel
from reversa.world.generator import MERCHANT_ID

IST_FMT = "%H:%M"


def L(paise: int) -> str:
    return f"Rs {paise / 1e7:>7.2f}L"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true",
                    help="persist the run (default rolls back so it is repeatable)")
    args = ap.parse_args()

    from reversa.config import IST

    with session_scope() as s:
        ck = PL.clock(s)
        print(f"world clock: {ck.now.astimezone(IST):%Y-%m-%d %H:%M} IST\n")

        model = CounterfactualModel.fit(s, until=ck.live_day)
        print(f"[estimator] {model.summary()['fit_rows']} historical failures, "
              f"{model.summary()['natural_cells']} cells, "
              f"actions seen: {len(model.summary()['actions_observed'])}")

        detected, diag = IE.scan(s, ck.live_day, ck.now)
        incidents = PL.persist_incidents(s, detected, merchant_id=MERCHANT_ID, now=ck.now)
        print(f"[detector]  {diag['ticks']} ticks, {len(incidents)} incidents\n")
        for inc in incidents:
            print(f"   {inc.severity.upper():8s} {inc.slice_key:16s} "
                  f"{inc.detected_at.astimezone(IST):%H:%M}  "
                  f"{inc.baseline_success_rate:5.1%} -> {inc.observed_success_rate:5.1%}  "
                  f"{L(inc.revenue_exposed_paise)}  q={inc.q_value:.0e}")

        hero = max(incidents, key=lambda i: i.revenue_exposed_paise)
        detected_hero = max(detected, key=lambda d: d.worst.observation.amount_failed_paise)
        print(f"\n[cohort]    building for {hero.slice_key}")

        build = build_cohort(s, detected_hero, model, now=ck.now)
        cohort = PL.persist_cohort(s, hero, build, now=ck.now)
        print(f"   members            {len(build.candidates)}")
        print(f"   revenue exposed   {L(build.revenue_exposed_paise)}")
        print(f"   would self-recover{L(build.natural_recovery_paise)}  "
              f"({build.natural_recovery_paise / max(build.revenue_exposed_paise, 1):.0%})")
        print(f"   ADDRESSABLE       {L(build.addressable_paise)}")
        print(f"   exceptions         {len(build.exceptions)} {build.exceptions_by_reason()}")

        run = SIM.run(build.candidates)
        sim = PL.persist_simulation(s, cohort, run, now=ck.now, seed=20260826)
        print(f"\n[wind tunnel] {run.candidate_count} candidates, {run.total_ms:.0f}ms\n")
        print(f"   {'SCENARIO':16s} {'GROSS':>10s} {'INCREMENTAL':>12s} "
              f"{'ACTIONS':>8s} {'COST':>9s} {'NET':>10s} {'WASTE':>6s}")
        for sc in run.scenarios:
            mark = "  <-- best" if sc.key == run.best.key else ""
            print(f"   {sc.label:16s} {L(sc.gross_recovery_paise):>10s} "
                  f"{L(sc.incremental_recovery_paise):>12s} {sc.action_count:8d} "
                  f"Rs{sc.cost_paise / 100:7.0f} {L(sc.net_incremental_paise):>10s} "
                  f"{sc.wasted_actions:6d}{mark}")

        report = PL.execute_and_measure(
            s, cohort, sim, run.best, build.candidates, now=ck.now,
        )
        r = report.result
        print(f"\n[experiment] {report.experiment_id}")
        print(f"   arms {report.arms}   balanced="
              f"{report.balance['_balance']['balanced']} "
              f"(mean-ticket ratio {report.balance['_balance']['mean_ticket_ratio']})")
        for arm, a in r.arms.items():
            print(f"   {arm:11s} n={a.payments:5d} recovered={a.recovered:4d} "
                  f"({a.recovery_rate:6.1%})  {L(a.recovered_paise)} of {L(a.exposure_paise)}")

        print(f"\n   gross recovery      {L(r.gross_recovery_paise)}")
        print(f"   natural (holdout)   {L(r.natural_recovery_paise)}")
        print(f"   INCREMENTAL         {L(r.incremental_paise)}   "
              f"90% CI [{L(r.incremental_lo_paise)}, {L(r.incremental_hi_paise)}]")
        print(f"   rate lift           {r.rate_lift:+.2%} "
              f"[{r.rate_lift_lo:+.2%}, {r.rate_lift_hi:+.2%}]")
        print(f"   revenue lift sig.   {r.significant}")
        print(f"   rate lift sig.      {r.rate_significant}")
        print(f"   intervention cost   Rs {r.cost_paise / 100:,.0f}   ROI {r.roi:.0f}x" if r.roi else "   intervention cost   Rs 0")
        print(f"   measurement cost    {L(r.measurement_cost_paise)}  "
              f"(holdout revenue deliberately not chased)")
        if r.warnings:
            print(f"   warnings            {r.warnings}")
        print(f"\n   projected {L(report.projected_incremental_paise)} "
              f"-> measured {L(r.incremental_paise)}")

        chain = verify_chain(s)
        print(f"\n[audit] {chain.entries_checked} entries, chain valid={chain.valid}")

        if not args.commit:
            s.rollback()
            print("\n(rolled back - pass --commit to persist)")


if __name__ == "__main__":
    main()
