import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  Bar, Button, ErrorNote, Label, Money, Panel, Severity, Skeleton, StatSkeleton, Tag,
} from "../components/primitives";
import { NeedsYou } from "../components/NeedsYou";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { count, dateTimeIST, lakhs, pct, sci, timeIST } from "../lib/format";
import { STEPS, useTour } from "../lib/tour";

export function CommandCentre() {
  const navigate = useNavigate();
  const overview = useAsync(() => api.overview(), []);
  const incidents = useAsync(() => api.incidents(), []);
  const system = useAsync(() => api.system(), []);
  const attention = useAsync(() => api.attention(), []);

  const o = overview.data;
  const grossSoFar = o ? o.natural_recovery_paise + o.incremental_recovery_paise : 0;

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      <FirstRun />

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Revenue recovery control system</Label>
          <h1 className="mt-2 text-4xl font-bold tracking-tight">Command Centre</h1>
        </div>
        <div className="flex items-center gap-3">
          {o && (
            <Tag tone="neutral">
              as of {dateTimeIST(o.as_of)} IST
            </Tag>
          )}
          <Tag tone={o && o.active_incidents > 0 ? "bad" : "good"}>
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-70" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
            </span>
            {o && o.active_incidents > 0 ? `${o.active_incidents} ACTIVE` : "OPERATIONAL"}
          </Tag>
        </div>
      </div>

      {overview.error && (
        <div className="mt-6">
          <ErrorNote message={overview.error.message} requestId={overview.error.requestId} />
        </div>
      )}

      <div className="mt-8">
        <NeedsYou state={attention} />
      </div>

      {/* ------------------------------------------------- headline tiles */}
      <div className="mt-2 flex items-baseline justify-between gap-4">
        <Label>Today</Label>
      </div>

      {overview.loading ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-3 xl:grid-cols-5">
          {["Revenue at risk", "Baseline recovery", "Incremental lift",
            "Open incidents", "Treatment capacity"].map((l) => (
            <StatSkeleton key={l} label={l} />
          ))}
        </div>
      ) : (
      <div data-tour="overview-tiles" className="stagger mt-3 grid gap-3 sm:grid-cols-3 xl:grid-cols-5">
        <div className="card p-4">
          <Label>Revenue at risk</Label>
          <div className="mt-1.5 text-[22px] font-bold leading-none tracking-tight">
            {o ? <Money paise={o.revenue_at_risk_paise} tone="loss" /> : "—"}
          </div>
          <p className="mt-1.5 text-[11px] text-black/60">
            {o ? `${count(o.live_failed_payments)} declined authorisations today` : ""}
          </p>
        </div>

        <div
          className="card p-4"
          title="Revenue that lands with no treatment at all. Conventional dunning tools book this as recovered."
        >
          <Label>Baseline recovery</Label>
          <div className="mt-1.5 text-[22px] font-bold leading-none tracking-tight">
            {o ? <Money paise={o.natural_recovery_paise} tone="muted" /> : "—"}
          </div>
          <p className="mt-1.5 text-[11px] text-black/60">observed in the holdout arm</p>
        </div>

        <div
          className="card p-4"
          title="Treatment minus holdout. The only figure attributable to the intervention."
        >
          <Label>Incremental lift</Label>
          <div className="mt-1.5 text-[22px] font-bold leading-none tracking-tight">
            {o ? <Money paise={o.incremental_recovery_paise} tone="yellow" /> : "—"}
          </div>
          <p className="mt-1.5 text-[11px] text-black/60">
            {o && grossSoFar > 0
              ? `${pct(o.incremental_recovery_paise / grossSoFar)} of gross recovery`
              : "no concluded test yet"}
          </p>
        </div>

        <div className="card p-4">
          <Label>Open incidents</Label>
          <div className="tnum mt-1.5 text-[22px] font-bold leading-none tracking-tight">
            {o ? o.active_incidents : "—"}
          </div>
          <p className="mt-1.5 text-[11px] text-black/60">
            {o ? `${o.total_incidents} detected today` : ""}
          </p>
        </div>

        <div className="card p-4">
          <Label>Treatment capacity</Label>
          <div className="tnum mt-1.5 text-[22px] font-bold leading-none tracking-tight">
            {o ? count(o.capacity.used) : "—"}
            <span className="text-black/60">
              {o ? ` / ${count(o.capacity.total)}` : ""}
            </span>
          </div>
          <div className="mt-3">
            <Bar value={o?.capacity.used ?? 0} max={o?.capacity.total ?? 1} />
          </div>
          <p className="mt-1.5 text-[11px] text-black/60">consumed this session</p>
        </div>
      </div>
      )}

      {/* --------------------------------------------------- revenue flow */}
      {o && grossSoFar > 0 && (
        <Panel
          className="mt-6"
          title="Recovery attribution"
          hint="Where the money actually went. These come from tests that finished, not forecasts."
          action={
            <Button variant="ghost" onClick={() => navigate("/autopsy")}>
              Full autopsy →
            </Button>
          }
        >
          <div className="p-6">
            <FlowBar
              exposed={o.revenue_at_risk_paise}
              natural={o.natural_recovery_paise}
              incremental={o.incremental_recovery_paise}
            />
            <div className="mt-4 grid gap-4 text-sm sm:grid-cols-3">
              <Legend swatch="bg-sage" label="Baseline (would have landed anyway)" value={lakhs(o.natural_recovery_paise)} />
              <Legend swatch="bg-cyber" label="Incremental lift (attributable)" value={lakhs(o.incremental_recovery_paise)} />
              <Legend
                swatch="bg-signal-loss/40"
                label="Unrecovered"
                value={lakhs(Math.max(0, o.revenue_at_risk_paise - grossSoFar))}
              />
            </div>
          </div>
        </Panel>
      )}

      <div className="mt-6 grid gap-6 xl:grid-cols-[1.4fr_0.6fr]">
        {/* -------------------------------------------------- incidents */}
        <Panel
          title="Detected incidents"
          hint="Success rates that broke. Corrected for the hundreds of slices we check at once, so we are not crying wolf."
          action={
            <Button variant="ghost" onClick={() => navigate("/incidents")}>
              All incidents →
            </Button>
          }
        >
          {incidents.loading && <Skeleton rows={4} />}
          {incidents.data && (
            <div className="divide-y divide-black/10">
              {incidents.data.slice(0, 5).map((inc) => (
                <button
                  key={inc.id}
                  onClick={() => navigate(`/incidents/${inc.id}`)}
                  className="row-hover flex w-full items-center gap-4 px-6 py-4 text-left"
                >
                  <Severity level={inc.severity} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">{inc.slice}</p>
                    <p className="mt-0.5 text-[11px] text-black/60">
                      {timeIST(inc.window_start)}–{timeIST(inc.window_end)} IST ·{" "}
                      {pct(inc.baseline_success_rate)} → {pct(inc.observed_success_rate)} ·{" "}
                      q={sci(inc.q_value)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="tnum text-sm font-bold text-signal-loss-ink">
                      {lakhs(inc.revenue_exposed_paise)}
                    </p>
                    <p className="text-[11px] text-black/60">
                      {count(inc.affected_payment_count)} payments
                    </p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Panel>

        {/* ----------------------------------------------- system status */}
        <Panel title="System" hint="Which numbers came from where.">
          <div className="space-y-5 p-6">
            {system.data && (
              <>
                <div>
                  <Label>Razorpay adapter</Label>
                  <div className="mt-2">
                    <Tag tone={system.data.adapters.razorpay.mode.includes("TEST") ? "yellow" : "neutral"}>
                      {system.data.adapters.razorpay.mode}
                    </Tag>
                  </div>
                  <p className="mt-3 text-[11px] leading-relaxed text-black/60">
                    {system.data.adapters.razorpay.note}
                  </p>
                </div>

                <div className="border-t border-black/15 pt-5">
                  <Label>Payment-link budget</Label>
                  <div className="tnum mt-2 text-2xl font-bold">
                    {system.data.adapters.razorpay.payment_link_budget.remaining}
                    <span className="text-black/60">
                      {" "}/ {system.data.adapters.razorpay.payment_link_budget.limit}
                    </span>
                  </div>
                </div>

                {/* Always present, so the integration is visible whether or not
                    a Payment Link has been created yet. The live call count
                    comes from the boot-time downtime fetch, so it is a fact
                    about this process rather than a claim in a README. */}
                <div className="border-t border-black/15 pt-5">
                  <Label>Razorpay integration</Label>
                  <div className="mt-2 flex flex-wrap items-baseline gap-2">
                    <span className="tnum text-2xl font-bold">
                      {system.data.adapters.razorpay.live_calls}
                    </span>
                    <span className="text-[11px] text-black/60">
                      live API calls this session
                    </span>
                  </div>
                  {!system.data.adapters.razorpay.last_payment_link?.short_url && (
                    <p className="mt-2 text-[11px] leading-relaxed text-black/60">
                      No Payment Link created yet this session. Executing a plan creates
                      one through the real API and the checkout page appears here.
                    </p>
                  )}
                </div>

                {system.data.adapters.razorpay.last_payment_link?.short_url && (
                  <div className="border-t border-black/15 pt-5">
                    <Label>Last Payment Link created</Label>
                    <p className="mt-2 text-[11px] leading-relaxed text-black/60">
                      Created through the Razorpay API by this service. Opens the real
                      test-mode checkout.
                    </p>
                    <a
                      href={system.data.adapters.razorpay.last_payment_link.short_url}
                      target="_blank"
                      rel="noreferrer"
                      className="btn btn-sm mt-3 w-full bg-black text-white"
                    >
                      Open the payment page &rarr;
                    </a>
                    <p className="mt-2 break-all font-mono text-[10px] text-black/60">
                      {system.data.adapters.razorpay.last_payment_link.id}
                    </p>
                  </div>
                )}

                <div className="border-t border-black/15 pt-5 space-y-2">
                  <MetaRow label="Estimator fit" value={`${Math.round(system.data.engine.fit_ms)}ms`} />
                  <MetaRow label="Day scan" value={`${Math.round(system.data.engine.scan_ms)}ms`} />
                  <MetaRow
                    label="Ticks evaluated"
                    value={String(system.data.engine.detector?.["ticks"] ?? "—")}
                  />
                  <MetaRow label="Language model" value={system.data.adapters.llm.mode} />
                </div>
              </>
            )}
            {system.loading && <Skeleton rows={5} />}
          </div>
        </Panel>
      </div>
    </div>
  );
}

/**
 * Exposure split into natural / incremental / lost.
 *
 * Widths are clamped and the labels only render when the segment is wide
 * enough to hold them. A measured incremental CAN come out negative - the
 * treated arm underperforming the holdout is a real outcome, not an error -
 * and the first version passed that straight into a CSS width, which pushed the
 * label out of the bar. A negative result gets its own treatment instead of
 * being drawn as if it were a positive one.
 */
function FlowBar({
  exposed, natural, incremental,
}: {
  exposed: number;
  natural: number;
  incremental: number;
}) {
  const total = Math.max(exposed, 1);
  const naturalPct = Math.max(0, Math.min(100, (natural / total) * 100));
  const incrementalPct = Math.max(0, Math.min(100 - naturalPct, (incremental / total) * 100));
  const lostPct = Math.max(0, 100 - naturalPct - incrementalPct);

  return (
    <>
      {/* Hard segments on a bordered track. The neo-brutalist read is a
          physical bar divided by black rules, not a gradient fill — so each
          segment is separated by a 2px border rather than a colour change. */}
      <div className="flex h-14 w-full overflow-hidden rounded-neo border-2 border-black bg-white">
        <FlowSegment width={naturalPct} label="Baseline" className="bg-sage" />
        <FlowSegment width={incrementalPct} label="Incremental" className="bg-cyber" />
        <FlowSegment width={lostPct} label="Unrecovered" className="bg-signal-loss/25" last />
      </div>

      {incremental < 0 && (
        <p className="mt-3 text-[12px] leading-relaxed text-signal-loss-ink">
          The measured incremental is negative: the treated group recovered less
          than the holdout. That is a real result, not a display error — most
          likely an underpowered run rather than a harmful intervention. The
          Experiments page carries the interval and the sample size needed to
          tell those apart.
        </p>
      )}
    </>
  );
}

function FlowSegment({
  width, label, className, last,
}: {
  width: number;
  label: string;
  className: string;
  last?: boolean;
}) {
  if (width < 0.4) return null;
  return (
    <div
      className={`flex items-center justify-center overflow-hidden whitespace-nowrap
                  font-display text-[10px] font-extrabold uppercase tracking-label
                  transition-[width] duration-500 ${className} ${last ? "" : "border-r-2 border-black"}`}
      style={{ width: `${width}%` }}
    >
      {width > 13 ? label : ""}
    </div>
  );
}

function Legend({ swatch, label, value }: { swatch: string; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className={`h-4 w-4 shrink-0 border-2 border-black ${swatch}`} />
      <span className="text-xs text-black/60">{label}</span>
      <span className="tnum ml-auto font-display text-sm font-extrabold">{value}</span>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[11px] text-black/60">{label}</span>
      <span className="tnum text-[12px] font-medium">{value}</span>
    </div>
  );
}


/**
 * The first thing a stranger sees.
 *
 * Landing on five stat tiles and a list of degraded payment slices tells you
 * nothing about what any of it is for. This says it in one sentence and offers
 * the guided path, once. Dismissal is remembered - being told the same thing on
 * every visit is its own kind of rude.
 *
 * localStorage is right for this and wrong for the session token, which is why
 * the token is not in it: this is a preference, and losing it costs a reader one
 * banner. Reads are wrapped because a private window can throw on access rather
 * than return empty.
 */
const SEEN_KEY = "reversa.intro.dismissed";

function FirstRun() {
  const tour = useTour();
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(SEEN_KEY) === "1";
    } catch {
      return false;
    }
  });

  if (dismissed || tour.active) return null;

  const close = () => {
    setDismissed(true);
    try {
      localStorage.setItem(SEEN_KEY, "1");
    } catch {
      /* a viewer who blocks storage simply sees this again next time */
    }
  };

  return (
    <section className="surface-accent mb-8 flex flex-wrap items-center gap-x-6 gap-y-4 p-6">
      <div className="min-w-0 flex-1">
        <Label>New here</Label>
        <p className="mt-2 max-w-3xl text-[15px] font-medium leading-relaxed">
          When a payment fails, some of that money comes back on its own. Every
          recovery tool counts all of it as money it recovered. Reversa measures the
          difference against a held-out control, so the only number it reports is the
          part your intervention actually caused.
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <Button
          variant="dark"
          onClick={() => {
            close();
            tour.start();
            const first = STEPS[0];
            if (first) navigate(first.path);
          }}
        >
          Show me how &rarr;
        </Button>
        <button onClick={close} className="link-quiet">
          Dismiss
        </button>
      </div>
    </section>
  );
}
