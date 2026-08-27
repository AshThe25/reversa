import { useNavigate } from "react-router-dom";

import {
  Bar, Button, ErrorNote, Label, Money, Panel, Severity, Skeleton, Tag,
} from "../components/primitives";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { count, dateTimeIST, lakhs, pct, sci, timeIST } from "../lib/format";

export function CommandCentre() {
  const navigate = useNavigate();
  const overview = useAsync(() => api.overview(), []);
  const incidents = useAsync(() => api.incidents(), []);
  const system = useAsync(() => api.system(), []);

  const o = overview.data;
  const grossSoFar = o ? o.natural_recovery_paise + o.incremental_recovery_paise : 0;

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
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

      {/* ------------------------------------------------- headline tiles */}
      <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <div className="hero-loss p-6">
          <Label>Revenue at risk</Label>
          <div className="mt-2 text-[34px] font-bold leading-none tracking-tight">
            {o ? <Money paise={o.revenue_at_risk_paise} tone="loss" /> : "—"}
          </div>
          <p className="mt-2 text-xs text-white/40">
            {o ? `${count(o.live_failed_payments)} declined authorisations today` : ""}
          </p>
        </div>

        <div
          className="hero-neutral p-6"
          title="Revenue that lands with no treatment at all. Conventional dunning tools book this as recovered."
        >
          <Label>Baseline recovery</Label>
          <div className="mt-2 text-[34px] font-bold leading-none tracking-tight">
            {o ? <Money paise={o.natural_recovery_paise} tone="muted" /> : "—"}
          </div>
          <p className="mt-2 text-xs text-white/40">observed in the holdout arm</p>
        </div>

        <div
          className="hero-accent p-6"
          title="Treatment minus holdout. The only figure attributable to the intervention."
        >
          <Label>Incremental lift</Label>
          <div className="mt-2 text-[34px] font-bold leading-none tracking-tight">
            {o ? <Money paise={o.incremental_recovery_paise} tone="yellow" /> : "—"}
          </div>
          <p className="mt-2 text-xs text-white/40">
            {o && grossSoFar > 0
              ? `${pct(o.incremental_recovery_paise / grossSoFar)} of gross recovery`
              : "no concluded test yet"}
          </p>
        </div>

        <div className="hero-neutral p-6">
          <Label>Open incidents</Label>
          <div className="tnum mt-2 text-[34px] font-bold leading-none tracking-tight">
            {o ? o.active_incidents : "—"}
          </div>
          <p className="mt-2 text-xs text-white/40">
            {o ? `${o.total_incidents} detected today` : ""}
          </p>
        </div>

        <div className="hero-neutral p-6">
          <Label>Treatment capacity</Label>
          <div className="tnum mt-2 text-[34px] font-bold leading-none tracking-tight">
            {o ? count(o.capacity.used) : "—"}
            <span className="text-white/35">
              {o ? ` / ${count(o.capacity.total)}` : ""}
            </span>
          </div>
          <div className="mt-3">
            <Bar value={o?.capacity.used ?? 0} max={o?.capacity.total ?? 1} />
          </div>
          <p className="mt-2 text-xs text-white/40">consumed this session</p>
        </div>
      </div>

      {/* --------------------------------------------------- revenue flow */}
      {o && grossSoFar > 0 && (
        <Panel
          className="mt-6"
          title="Recovery attribution"
          hint="Exposure decomposed into baseline recovery and incremental lift. Sourced from concluded tests, not projections."
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
              <Legend swatch="bg-white/[0.15]" label="Baseline (would have landed anyway)" value={lakhs(o.natural_recovery_paise)} />
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
          hint="Auth-rate breaks by slice, after Benjamini-Hochberg correction across every slice and window tested."
          action={
            <Button variant="ghost" onClick={() => navigate("/incidents")}>
              All incidents →
            </Button>
          }
        >
          {incidents.loading && <Skeleton rows={4} />}
          {incidents.data && (
            <div className="divide-y divide-white/[0.05]">
              {incidents.data.slice(0, 5).map((inc) => (
                <button
                  key={inc.id}
                  onClick={() => navigate(`/incidents/${inc.id}`)}
                  className="row-hover flex w-full items-center gap-4 px-6 py-4 text-left"
                >
                  <Severity level={inc.severity} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">{inc.slice}</p>
                    <p className="mt-0.5 text-[11px] text-white/35">
                      {timeIST(inc.window_start)}–{timeIST(inc.window_end)} IST ·{" "}
                      {pct(inc.baseline_success_rate)} → {pct(inc.observed_success_rate)} ·{" "}
                      q={sci(inc.q_value)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="tnum text-sm font-bold text-signal-loss">
                      {lakhs(inc.revenue_exposed_paise)}
                    </p>
                    <p className="text-[11px] text-white/30">
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
                  <p className="mt-3 text-[11px] leading-relaxed text-white/30">
                    {system.data.adapters.razorpay.note}
                  </p>
                </div>

                <div className="border-t border-white/[0.06] pt-5">
                  <Label>Payment-link budget</Label>
                  <div className="tnum mt-2 text-2xl font-bold">
                    {system.data.adapters.razorpay.payment_link_budget.remaining}
                    <span className="text-white/25">
                      {" "}/ {system.data.adapters.razorpay.payment_link_budget.limit}
                    </span>
                  </div>
                </div>

                <div className="border-t border-white/[0.06] pt-5 space-y-2">
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
      {/* Recessed track, lit segments. Same inversion as the segmented control:
          the channel sits below the surface and each segment catches the top
          light, so the bar reads as filled rather than painted. */}
      <div
        className="flex h-14 w-full overflow-hidden rounded-full p-1"
        style={{
          background: "rgba(0,0,0,0.5)",
          border: "1px solid rgba(255,255,255,0.06)",
          boxShadow: "inset 0 2px 8px rgba(0,0,0,0.7)",
        }}
      >
        <FlowSegment
          width={naturalPct}
          label="natural"
          className="text-white/60"
          fill="linear-gradient(180deg, rgba(255,255,255,0.14), rgba(255,255,255,0.07))"
          highlight="rgba(255,255,255,0.14)"
          first
        />
        <FlowSegment
          width={incrementalPct}
          label="incremental"
          className="font-bold text-onyx"
          fill="linear-gradient(180deg, #fde047, #eab308)"
          highlight="rgba(255,255,255,0.5)"
        />
        <FlowSegment
          width={lostPct}
          label="still lost"
          className="text-signal-loss"
          fill="linear-gradient(180deg, rgba(255,93,93,0.20), rgba(255,93,93,0.10))"
          highlight="rgba(255,93,93,0.25)"
          last
        />
      </div>
      {incremental < 0 && (
        <p className="mt-3 text-[12px] leading-relaxed text-signal-loss">
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
  width, label, className, fill, highlight, first, last,
}: {
  width: number;
  label: string;
  className: string;
  fill: string;
  highlight: string;
  first?: boolean;
  last?: boolean;
}) {
  if (width < 0.4) return null;
  const radius = "9999px";
  return (
    <div
      className={`flex items-center justify-center overflow-hidden whitespace-nowrap text-[11px] font-semibold transition-[width] duration-700 ease-liquid ${className}`}
      style={{
        width: `${width}%`,
        background: fill,
        boxShadow: `inset 0 1px 0 ${highlight}`,
        borderTopLeftRadius: first ? radius : 4,
        borderBottomLeftRadius: first ? radius : 4,
        borderTopRightRadius: last ? radius : 4,
        borderBottomRightRadius: last ? radius : 4,
        marginRight: last ? 0 : 2,
      }}
    >
      {width > 11 ? label : ""}
    </div>
  );
}

function Legend({ swatch, label, value }: { swatch: string; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className={`h-3 w-3 shrink-0 rounded-full ${swatch}`} />
      <span className="text-xs text-white/40">{label}</span>
      <span className="tnum ml-auto text-sm font-semibold">{value}</span>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[11px] text-white/35">{label}</span>
      <span className="tnum text-[12px] font-medium">{value}</span>
    </div>
  );
}
