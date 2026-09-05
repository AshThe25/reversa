import { useNavigate } from "react-router-dom";

import { Label } from "../components/primitives";
import { api } from "../lib/api";
import { count, lakhs, pct } from "../lib/format";
import { STEPS, useTour } from "../lib/tour";
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
    <div className="min-h-full bg-plate">
      {/* ------------------------------------------------------------ nav */}
      <header className="bg-plate">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-6 px-6 py-5 sm:px-10">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center border-2 border-black bg-black font-display text-lg font-extrabold text-plate">
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
      <section className="relative overflow-hidden border-b-2 border-black bg-plate">
        {/*
          The plate carries its own dot field, halftone and horizon, so it is the
          background rather than something layered on one — the flat yellow only
          shows where `cover` runs out. `bg-plate` is sampled off the file so the
          two meet without a seam.

          The plate only becomes a background at `lg`, which is exactly where the
          two-column grid opens the right-hand space it needs. Tying it to `md`
          instead put the artwork behind the headline for the whole 768-1024
          range, where the copy still spans the full width. Below `lg` it is a
          full-bleed band under the copy - same artwork, stacked rather than
          alongside - and the CSS dot field stands in behind the text.
        */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 hidden bg-[url('/hero-plate.png')]
                     bg-contain bg-right bg-no-repeat lg:block"
        />
        <div aria-hidden className="dot-field pointer-events-none absolute inset-0 lg:hidden" />

        <div className="relative z-10 mx-auto grid min-h-[560px] max-w-[1500px] items-center gap-10
                        px-6 py-16 sm:px-10 lg:min-h-[720px] lg:grid-cols-[1fr_0.8fr] lg:py-20">
          <div>
            <span className="chip gap-2 bg-white shadow-hard-sm">
              <span className="text-rzp">⚡</span> Counterfactual revenue recovery
            </span>

            <h1 className="mt-7 font-display text-[clamp(2.6rem,6.4vw,4.9rem)] font-extrabold uppercase leading-[0.88] tracking-tighter">
              Recover only
              <br />
              <span className="text-stroke">what</span> wouldn&rsquo;t
              <br />
              come back
            </h1>

            <p className="mt-7 max-w-lg text-[17px] font-medium leading-relaxed text-black/75">
              Every recovery tool books the money that arrives as money it recovered.
              Most of it was arriving anyway. Reversa measures the difference against a
              held-out control, and only spends on the part that moves.
            </p>

            {/* The consequence, not the idea. The headline states a principle;
                this states what it costs you to ignore it, in this merchant's
                own numbers. Hidden until a test has concluded, because before
                that there is no measured figure and a placeholder here would be
                the exact dishonesty the product exists to object to. */}
            {overview && gross > 0 && (
              <dl className="mt-8 inline-flex w-fit max-w-full flex-wrap items-stretch gap-0 border-2 border-black bg-white/70 shadow-hard-sm">
                <div className="border-r-2 border-black px-5 py-3">
                  <dt className="label">Booked as recovered</dt>
                  <dd className="tnum mt-1 font-display text-xl font-extrabold tracking-tighter">
                    {lakhs(gross)}
                  </dd>
                </div>
                <div className="border-r-2 border-black px-5 py-3">
                  <dt className="label">Was arriving anyway</dt>
                  <dd className="tnum mt-1 font-display text-xl font-extrabold tracking-tighter text-black/60">
                    {lakhs(overview.natural_recovery_paise)}
                  </dd>
                </div>
                <div className="bg-cyber px-5 py-3">
                  <dt className="label">Actually caused</dt>
                  <dd className="tnum mt-1 font-display text-xl font-extrabold tracking-tighter">
                    {lakhs(overview.incremental_recovery_paise)}
                  </dd>
                </div>
              </dl>
            )}

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
              <p className="mt-6 font-display text-[11px] font-extrabold uppercase tracking-label text-black/60">
                {system.adapters.razorpay.mode} ·{" "}
                {system.adapters.razorpay.payment_link_budget.limit} payment-link ceiling ·{" "}
                {Math.round(system.engine.scan_ms)}ms day scan
              </p>
            )}
          </div>

          {/* From `lg` the right half of the grid is deliberately empty: it is
              where the background plate's artwork lands. Below `md` the plate
              is a real element here instead, bled to the section edges so its
              horizon meets the bottom border. */}
          <img
            src="/hero-plate.png"
            alt=""
            aria-hidden
            className="-mx-6 -mb-16 mt-12 w-[calc(100%+3rem)] max-w-none border-t-2 border-black
                       sm:-mx-10 sm:w-[calc(100%+5rem)] lg:hidden"
          />
          <div aria-hidden className="hidden lg:block" />
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
              {/* Counted from the tour itself. It said "Seven" for a while after
                  the walkthrough grew to eight. */}
              {STEPS.length} stops. Nothing to install. Leave at any point.
            </span>
          </div>
        </div>
      </section>

      <footer className="bg-charcoal px-6 py-10 text-white sm:px-10">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-4">
          <p className="font-display text-[11px] font-extrabold uppercase tracking-label">
            Reversa · Counterfactual revenue recovery
          </p>
          <p className="text-[11px] text-white/70">
            Built by <span className="font-semibold text-white">Aishwarya Tripathi</span> for the
            Razorpay AI Buildathon 2026
          </p>
          <p className="text-[11px] text-white/70">
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
      <p className="mt-2 text-[12px] text-white/70">{note}</p>
    </div>
  );
}
