import { useNavigate } from "react-router-dom";

import {
  Bar, Button, ErrorNote, Label, Panel, Severity, Skeleton, Stat, Tag,
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
        <div className="rounded-[28px] border border-signal-loss/20 bg-signal-loss/[0.04] p-6">
          <Stat
            label="Revenue at risk"
            value={o ? lakhs(o.revenue_at_risk_paise) : "—"}
            sub={o ? `${count(o.live_failed_payments)} failed payments today` : undefined}
            tone="loss"
          />
        </div>
        <div className="panel p-6">
          <Stat
            label="Would self-recover"
            value={o ? lakhs(o.natural_recovery_paise) : "—"}
            sub="measured from the holdout arm"
            tone="muted"
            hint="Revenue that arrives with no intervention at all. Conventional tools count this as recovered."
          />
        </div>
        <div className="rounded-[28px] border border-cyber/25 bg-cyber/[0.05] p-6">
          <Stat
            label="Incremental recovery"
            value={o ? lakhs(o.incremental_recovery_paise) : "—"}
            sub={
              o && grossSoFar > 0
                ? `${pct(o.incremental_recovery_paise / grossSoFar)} of gross`
                : "no concluded experiments yet"
            }
            tone="yellow"
            hint="Treatment minus holdout. The only figure attributable to intervention."
          />
        </div>
        <div className="panel p-6">
          <Stat
            label="Active incidents"
            value={o ? `${o.active_incidents}` : "—"}
            sub={o ? `${o.total_incidents} detected today` : undefined}
          />
        </div>
        <div className="panel p-6">
          <Label>Intervention capacity</Label>
          <div className="tnum mt-2 text-3xl font-bold tracking-tight">
            {o ? `${count(o.capacity.used)} / ${count(o.capacity.total)}` : "—"}
          </div>
          <div className="mt-3">
            <Bar value={o?.capacity.used ?? 0} max={o?.capacity.total ?? 1} />
          </div>
          <p className="mt-2 text-xs text-white/35">consumed this session</p>
        </div>
      </div>

      {/* --------------------------------------------------- revenue flow */}
      {o && grossSoFar > 0 && (
        <Panel
          className="mt-6"
          title="Where the money went"
          hint="Exposure decomposed into what arrived on its own and what we caused. Sourced from concluded experiments, not projections."
          action={
            <Button variant="ghost" onClick={() => navigate("/autopsy")}>
              Full autopsy →
            </Button>
          }
        >
          <div className="p-6">
            <div className="flex h-12 w-full overflow-hidden rounded-full border border-white/10">
              <div
                className="flex items-center justify-center bg-white/[0.09] text-[11px] font-semibold text-white/55"
                style={{ width: `${(o.natural_recovery_paise / Math.max(o.revenue_at_risk_paise, 1)) * 100}%` }}
              >
                natural
              </div>
              <div
                className="flex items-center justify-center bg-cyber text-[11px] font-bold text-onyx"
                style={{ width: `${(o.incremental_recovery_paise / Math.max(o.revenue_at_risk_paise, 1)) * 100}%` }}
              >
                incremental
              </div>
              <div className="flex flex-1 items-center justify-center bg-signal-loss/15 text-[11px] font-semibold text-signal-loss">
                still lost
              </div>
            </div>
            <div className="mt-4 grid gap-4 text-sm sm:grid-cols-3">
              <Legend swatch="bg-white/[0.15]" label="Naturally recovered" value={lakhs(o.natural_recovery_paise)} />
              <Legend swatch="bg-cyber" label="Incremental (attributable)" value={lakhs(o.incremental_recovery_paise)} />
              <Legend
                swatch="bg-signal-loss/40"
                label="Remaining loss"
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
          hint="Slices whose success rate broke, after Benjamini-Hochberg correction across every slice and window tested."
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
