import { useNavigate } from "react-router-dom";

import { Glass, Label, Tag } from "../components/primitives";
import { api } from "../lib/api";
import { lakhs, pct } from "../lib/format";
import { useTour } from "../lib/tour";
import { useAsync } from "../hooks/useAsync";

/**
 * The way in.
 *
 * A judge arrives knowing nothing and decides in about ten seconds whether this
 * is another AI dashboard. So the page leads with the question rather than the
 * product, and the first real number it shows is the uncomfortable one: most of
 * the revenue at risk comes back on its own.
 *
 * The figures here are fetched, not written. If the world reseeds, this page
 * changes with it.
 */
export function Landing() {
  const navigate = useNavigate();
  const tour = useTour();
  const { data: overview } = useAsync(() => api.overview(), []);
  const { data: system } = useAsync(() => api.system(), []);

  const begin = () => {
    tour.start();
    navigate("/command");
  };

  return (
    <div className="min-h-full bg-onyx">
      {/* ---------------------------------------------------- liquid hero */}
      <section
        className="relative overflow-hidden bg-cyber px-6 pt-10 text-onyx"
        style={{ borderBottomRightRadius: "120px", borderBottomLeftRadius: "40px" }}
      >
        <div className="mx-auto max-w-[1400px]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="grid h-9 w-9 place-items-center rounded-full bg-onyx text-sm font-black text-cyber">
                R
              </span>
              <span className="text-[15px] font-bold tracking-tight">REVERSA</span>
            </div>
            <span className="label-dark hidden sm:block">
              Razorpay AI Buildathon 2026 · Track 03
            </span>
          </div>

          <div className="grid gap-10 pb-24 pt-20 lg:grid-cols-[1.15fr_0.85fr] lg:pb-32">
            <div>
              <Label dark>Revenue recovery, before reality</Label>
              <h1 className="mt-5 text-5xl font-bold leading-[0.95] tracking-tight sm:text-7xl xl:text-8xl">
                What would
                <br />
                have happened
                <br />
                <span className="text-onyx/45">if we did nothing?</span>
              </h1>

              <p className="mt-8 max-w-xl text-[15px] leading-relaxed text-onyx/70">
                Every payment-recovery tool asks what to do when a payment fails,
                then reports the money that arrived as money it recovered. Most of
                it was arriving anyway.
              </p>
              <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-onyx/70">
                Reversa evaluates every treatment strategy against the affected
                cohort
                <em className="not-italic font-semibold text-onyx"> before </em>
                a single customer is contacted, allocates scarce capacity by
                expected incremental value, then measures what it actually caused
                against a randomised holdout.
              </p>

              <div className="mt-10 flex flex-wrap items-center gap-3">
                <button
                  onClick={begin}
                  className="pill bg-onyx px-6 py-3 text-[15px] font-semibold text-cyber hover:scale-[1.03] hover:shadow-2xl"
                >
                  Take the 90-second walkthrough →
                </button>
                <button
                  onClick={() => navigate("/command")}
                  className="pill border-2 border-onyx/20 px-6 py-3 text-[15px] font-semibold text-onyx hover:border-onyx/40"
                >
                  Skip to the dashboard
                </button>
              </div>
            </div>

            {/* ------------------------------------------ glass data card */}
            <div className="lg:pt-10">
              <Glass onColour float className="p-7 text-white">
                <div className="flex items-start justify-between">
                  <div>
                    <Label>Live incident · this merchant, today</Label>
                    <p className="mt-2 text-[13px] text-white/50">
                      {overview
                        ? `${overview.active_incidents} active · ${overview.total_incidents} detected`
                        : "loading"}
                    </p>
                  </div>
                  <span className="rounded-full bg-cyber px-3 py-1 text-[11px] font-bold text-onyx">
                    LIVE
                  </span>
                </div>

                <div className="mt-7">
                  <Label>Revenue at risk</Label>
                  <div className="tnum mt-1 text-5xl font-bold tracking-tight">
                    {overview ? lakhs(overview.revenue_at_risk_paise) : "—"}
                  </div>
                </div>

                <div className="mt-7 space-y-4 border-t border-white/10 pt-6">
                  <Row
                    label="Failed payments today"
                    value={overview ? overview.live_failed_payments.toLocaleString("en-IN") : "—"}
                  />
                  <Row
                    label="Detection latency"
                    value={system ? `${Math.round(system.engine.scan_ms)}ms scan` : "—"}
                  />
                  <Row
                    label="Payment-link capacity"
                    value={
                      system
                        ? `${system.adapters.razorpay.payment_link_budget.limit} (test mode cap)`
                        : "—"
                    }
                  />
                </div>

                <div className="mt-6 flex flex-wrap gap-2">
                  {system && (
                    <Tag tone={system.adapters.razorpay.mode.includes("TEST") ? "yellow" : "neutral"}>
                      {system.adapters.razorpay.mode}
                    </Tag>
                  )}
                  <Tag tone="neutral">Holdout-measured</Tag>
                  <Tag tone="neutral">Hash-chained audit</Tag>
                </div>
              </Glass>
            </div>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------- the void */}
      <section className="px-6 py-24">
        <div className="mx-auto max-w-[1400px]">
          <Label>The distinction the whole product rests on</Label>
          <h2 className="mt-4 max-w-3xl text-3xl font-bold leading-tight tracking-tight sm:text-5xl">
            Gross recovery is not incremental recovery.
          </h2>

          <div className="mt-14 grid gap-6 md:grid-cols-3">
            <Concept
              step="01"
              title="Detect"
              body="Slice the authorisation stream by method and instrument, test each against a seasonality-aware baseline, and control the false-discovery rate across hundreds of simultaneous tests. One PSP outage reports as one incident, not seven alerts."
            />
            <Concept
              step="02"
              title="Model"
              body="Rewind the incident and evaluate every treatment against the same cohort. No treatment. Immediate retry. Deferred retry. Payment link. Constrained optimum. The most aggressive strategy is rarely the best one."
              accent
            />
            <Concept
              step="03"
              title="Prove"
              body="Withhold treatment from a randomly assigned slice of the plan, stratified on order value. Treatment minus holdout, with a confidence interval, is the only number here that can honestly be called incremental."
            />
          </div>

          {overview && overview.natural_recovery_paise > 0 && (
            <div className="mt-14 rounded-[32px] border border-white/[0.07] bg-charcoal/60 p-8">
              <Label>Measured on this merchant's last recovery run</Label>
              <div className="mt-6 grid gap-8 sm:grid-cols-3">
                <Figure
                  label="Gross recovery"
                  value={lakhs(
                    overview.natural_recovery_paise + overview.incremental_recovery_paise,
                  )}
                  note="what a conventional tool would report"
                  tone="muted"
                />
                <Figure
                  label="Would have arrived anyway"
                  value={lakhs(overview.natural_recovery_paise)}
                  note="measured from the randomised holdout"
                  tone="muted"
                />
                <Figure
                  label="Actually caused by us"
                  value={lakhs(overview.incremental_recovery_paise)}
                  note={`${pct(
                    overview.incremental_recovery_paise /
                      Math.max(
                        overview.natural_recovery_paise + overview.incremental_recovery_paise,
                        1,
                      ),
                  )} of the gross figure`}
                  tone="yellow"
                />
              </div>
            </div>
          )}

          <div className="mt-16 flex flex-wrap items-center gap-3">
            <button
              onClick={begin}
              className="pill-solid px-6 py-3 text-[15px] font-semibold"
            >
              Start the walkthrough →
            </button>
            <span className="text-[12px] text-white/30">
              Seven stops. Nothing to install. You can leave at any point.
            </span>
          </div>
        </div>
      </section>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="text-[12px] text-white/40">{label}</span>
      <span className="tnum text-[13px] font-semibold">{value}</span>
    </div>
  );
}

function Concept({
  step,
  title,
  body,
  accent = false,
}: {
  step: string;
  title: string;
  body: string;
  accent?: boolean;
}) {
  return (
    <div
      className={[
        "rounded-[32px] border p-8 transition-colors duration-300",
        accent
          ? "border-cyber/25 bg-cyber/[0.05]"
          : "border-white/[0.07] bg-charcoal/40 hover:border-white/15",
      ].join(" ")}
    >
      <span className={`text-[11px] font-bold ${accent ? "text-cyber" : "text-white/25"}`}>
        {step}
      </span>
      <h3 className="mt-3 text-2xl font-bold tracking-tight">{title}</h3>
      <p className="mt-4 text-[13px] leading-relaxed text-white/45">{body}</p>
    </div>
  );
}

function Figure({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note: string;
  tone: "muted" | "yellow";
}) {
  return (
    <div>
      <Label>{label}</Label>
      <div
        className={`tnum mt-2 text-4xl font-bold tracking-tight ${
          tone === "yellow" ? "text-cyber" : "text-white/45"
        }`}
      >
        {value}
      </div>
      <p className="mt-2 text-[12px] text-white/30">{note}</p>
    </div>
  );
}
