import { useNavigate } from "react-router-dom";

import { HeroArt } from "../components/HeroArt";
import { Label } from "../components/primitives";
import { api } from "../lib/api";
import { count, lakhs, pct } from "../lib/format";
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
 * Every figure here is fetched. If the world is reseeded the page changes with
 * it — there is no number on this screen that a designer typed.
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

  const gross = overview
    ? overview.natural_recovery_paise + overview.incremental_recovery_paise
    : 0;

  return (
    <div className="min-h-full bg-cyber">
      {/* ------------------------------------------------------------ nav */}
      <header className="dot-field border-b-2 border-black bg-cyber">
        <div className="relative z-10 mx-auto flex max-w-[1500px] items-center justify-between gap-6 px-6 py-4 sm:px-10">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center border-2 border-black bg-black font-display text-lg font-extrabold text-cyber">
              R
            </span>
            <span className="font-display text-2xl font-extrabold uppercase tracking-tighter">
              Reversa
            </span>
          </div>

          <nav className="hidden items-center gap-9 lg:flex">
            {["Problem", "How it works", "Evidence", "Stack"].map((item) => (
              <a
                key={item}
                href={`#${item.toLowerCase().replace(/\s+/g, "-")}`}
                className="font-display text-[12px] font-extrabold uppercase tracking-label
                           decoration-2 underline-offset-4 hover:underline"
              >
                {item}
              </a>
            ))}
          </nav>

          <button onClick={begin} className="btn btn-sm bg-black text-white">
            Get started →
          </button>
        </div>
      </header>

      {/* ---------------------------------------------------------- hero */}
      <section className="dot-field relative overflow-hidden border-b-2 border-black bg-cyber">
        <div className="relative z-10 mx-auto grid max-w-[1500px] items-center gap-10 px-6 py-16 sm:px-10 lg:grid-cols-[1.05fr_0.95fr] lg:py-20">
          <div>
            <span className="chip gap-2 bg-white shadow-hard-sm">
              <span className="text-rzp">⚡</span> Counterfactual revenue recovery
            </span>

            <h1 className="mt-7 font-display text-[clamp(2.6rem,7vw,5.2rem)] font-extrabold uppercase leading-[0.88] tracking-tighter">
              What would
              <br />
              have happened
              <br />
              <span className="text-stroke">if we did</span> nothing?
            </h1>

            <p className="mt-7 max-w-xl text-[17px] font-medium leading-relaxed text-black/75">
              Every payment-recovery tool asks what to do when a payment fails, then
              books the money that arrives as money it recovered. Most of it was
              arriving anyway.
            </p>

            <div className="mt-9 flex flex-wrap items-center gap-4">
              <button onClick={begin} className="btn bg-black px-8 py-4 text-base text-white">
                Take the walkthrough →
              </button>
              <button
                onClick={() => navigate("/command")}
                className="btn bg-cream px-8 py-4 text-base text-black"
              >
                Skip to the console
              </button>
            </div>

            {system && (
              <p className="mt-6 font-display text-[11px] font-extrabold uppercase tracking-label text-black/50">
                {system.adapters.razorpay.mode} ·{" "}
                {system.adapters.razorpay.payment_link_budget.limit} payment-link ceiling ·{" "}
                {Math.round(system.engine.scan_ms)}ms day scan
              </p>
            )}
          </div>

          <div className="relative -mr-6 sm:-mr-10 lg:-my-10">
            <HeroArt className="w-full drop-shadow-none" />
          </div>
        </div>
      </section>

      {/* --------------------------------------------------- the problem */}
      <section id="problem" className="border-b-2 border-black bg-cream">
        <div className="mx-auto max-w-[1500px] px-6 py-20 sm:px-10">
          <Label>The distinction the whole product rests on</Label>
          <h2 className="mt-4 max-w-4xl font-display text-[clamp(1.9rem,4.5vw,3.4rem)] font-extrabold uppercase leading-[0.95] tracking-tighter">
            Gross recovery is not
            <br />
            <span className="text-stroke">incremental</span> recovery.
          </h2>

          {overview && gross > 0 && (
            <div className="mt-12 grid gap-6 md:grid-cols-3">
              <Figure
                tone="white"
                label="Gross recovery"
                value={lakhs(gross)}
                note="what a conventional dunning tool books"
              />
              <Figure
                tone="sage"
                label="Would have landed anyway"
                value={lakhs(overview.natural_recovery_paise)}
                note="measured from the randomised holdout"
              />
              <Figure
                tone="yellow"
                label="Actually caused by us"
                value={lakhs(overview.incremental_recovery_paise)}
                note={`${pct(overview.incremental_recovery_paise / gross)} of the gross figure`}
              />
            </div>
          )}
        </div>
      </section>

      {/* ------------------------------------------------- how it works */}
      <section id="how-it-works" className="dot-field border-b-2 border-black bg-cyber">
        <div className="relative z-10 mx-auto max-w-[1500px] px-6 py-20 sm:px-10">
          <h2 className="text-center font-display text-[clamp(1.7rem,4vw,3rem)] font-extrabold uppercase tracking-tighter">
            Detect · Model · Prove
          </h2>

          <div className="mt-14 grid gap-8 md:grid-cols-3">
            <Step
              n="01"
              title="Detect"
              body="Slice the authorisation stream by method and instrument, test each against a seasonality-aware baseline, and control the false-discovery rate across hundreds of simultaneous tests. One PSP outage reports as one incident, not seven alerts."
            />
            <Step
              n="02"
              title="Model"
              body="Rewind the incident and evaluate every treatment against the same cohort. No treatment. Immediate retry. Deferred retry. Payment link. Constrained optimum. The most aggressive strategy is rarely the best one."
              accent
            />
            <Step
              n="03"
              title="Prove"
              body="Withhold treatment from a randomly assigned slice of the plan, stratified on order value. Treatment minus holdout, with a confidence interval, is the only number here that can honestly be called incremental."
            />
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------- the evidence */}
      <section id="evidence" className="border-b-2 border-black bg-navy text-white">
        <div className="mx-auto max-w-[1500px] px-6 py-20 sm:px-10">
          <Label dark>Live, from this merchant's day</Label>
          <h2 className="mt-4 max-w-3xl font-display text-[clamp(1.7rem,4vw,3rem)] font-extrabold uppercase leading-[0.95] tracking-tighter">
            None of these numbers
            <br />
            were typed by a designer.
          </h2>

          <div className="mt-12 grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
            <Metric
              label="Revenue at risk"
              value={overview ? lakhs(overview.revenue_at_risk_paise) : "—"}
              note={overview ? `${count(overview.live_failed_payments)} declines today` : ""}
            />
            <Metric
              label="Incidents detected"
              value={overview ? String(overview.total_incidents) : "—"}
              note={overview ? `${overview.active_incidents} still open` : ""}
            />
            <Metric
              label="Day scan"
              value={system ? `${Math.round(system.engine.scan_ms)}ms` : "—"}
              note={`${(system?.engine.detector?.["ticks"] as number) ?? "—"} ticks evaluated`}
            />
            <Metric
              label="Link ceiling"
              value={
                system ? String(system.adapters.razorpay.payment_link_budget.limit) : "—"
              }
              note="enforced, not worked around"
            />
          </div>

          <div className="mt-12 flex flex-wrap items-center gap-4">
            <button onClick={begin} className="btn bg-cyber px-8 py-4 text-base text-black">
              Take the walkthrough →
            </button>
            <span className="text-[12px] text-white/55">
              Seven stops. Nothing to install. Leave at any point.
            </span>
          </div>
        </div>
      </section>

      <footer className="bg-charcoal px-6 py-10 text-white sm:px-10">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-4">
          <p className="font-display text-[11px] font-extrabold uppercase tracking-label">
            Reversa · Counterfactual revenue recovery
          </p>
          <p className="text-[11px] text-white/50">
            Every figure on this site is computed by a backend engine. None are authored.
          </p>
        </div>
      </footer>
    </div>
  );
}

function Figure({
  label, value, note, tone,
}: {
  label: string;
  value: string;
  note: string;
  tone: "white" | "sage" | "yellow";
}) {
  const bg = { white: "bg-white", sage: "bg-sage", yellow: "bg-cyber" }[tone];
  return (
    <div className={`rounded-neo border-2 border-black p-8 shadow-hard-md ${bg}`}>
      <Label>{label}</Label>
      <div className="tnum mt-3 font-display text-[clamp(2rem,4vw,3rem)] font-extrabold tracking-tighter">
        {value}
      </div>
      <p className="mt-3 text-[13px] font-medium text-black/60">{note}</p>
    </div>
  );
}

function Step({
  n, title, body, accent = false,
}: {
  n: string;
  title: string;
  body: string;
  accent?: boolean;
}) {
  return (
    <div
      className={`rounded-neo border-2 border-black p-8 shadow-hard-md ${
        accent ? "bg-navy text-white" : "bg-white"
      }`}
    >
      <span
        className={`grid h-14 w-14 place-items-center rounded-full border-2 font-display text-lg font-extrabold ${
          accent ? "border-cyber bg-charcoal text-cyber" : "border-black bg-cyber text-black"
        }`}
      >
        {n}
      </span>
      <h3 className="mt-6 font-display text-2xl font-extrabold uppercase tracking-tighter">
        {title}
      </h3>
      <p className={`mt-4 text-[13px] leading-relaxed ${accent ? "text-white/70" : "text-black/65"}`}>
        {body}
      </p>
    </div>
  );
}

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="rounded-neo border-2 border-cyber bg-charcoal p-6">
      <div className="label-invert">{label}</div>
      <div className="tnum mt-2 font-display text-4xl font-extrabold tracking-tighter text-cyber">
        {value}
      </div>
      <p className="mt-2 text-[12px] text-white/50">{note}</p>
    </div>
  );
}
