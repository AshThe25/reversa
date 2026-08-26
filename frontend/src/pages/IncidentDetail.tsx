import { useNavigate, useParams } from "react-router-dom";
import {
  Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import {
  Button, ErrorNote, Panel, Severity, Skeleton, Stat, Tag,
} from "../components/primitives";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { count, lakhs, pct, sci, timeIST, titleise } from "../lib/format";

export function IncidentDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const incident = useAsync(() => api.incident(id), [id]);
  const cohort = useAsync(() => api.cohort(id), [id]);

  const inc = incident.data;
  const co = cohort.data;

  const series =
    inc?.signals.map((s) => ({
      t: timeIST(s.at),
      observed: +(s.success_rate * 100).toFixed(1),
      baseline: +(s.baseline_rate * 100).toFixed(1),
      n: s.n,
    })) ?? [];

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      <button
        onClick={() => navigate("/incidents")}
        className="text-[12px] text-white/35 transition-colors hover:text-white/70"
      >
        ← All incidents
      </button>

      {incident.error && (
        <div className="mt-6">
          <ErrorNote message={incident.error.message} requestId={incident.error.requestId} />
        </div>
      )}
      {incident.loading && <Skeleton rows={5} />}

      {inc && (
        <>
          <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-3">
                <Severity level={inc.severity} />
                <span className="font-mono text-[11px] uppercase tracking-label text-white/30">
                  {inc.id}
                </span>
              </div>
              <h1 className="mt-3 text-4xl font-bold tracking-tight">{inc.slice}</h1>
              <p className="mt-2 text-sm text-white/40">
                {timeIST(inc.window_start)} → {timeIST(inc.window_end)} IST · detected{" "}
                {timeIST(inc.detected_at)}
              </p>
            </div>
            <Button onClick={() => navigate(`/futures?incident=${inc.id}`)}>
              Open the wind tunnel →
            </Button>
          </div>

          {/* ------------------------------------------------------ tiles */}
          <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <div className="panel p-6">
              <Stat
                label="Success rate"
                value={
                  <span>
                    <span className="text-white/35">{pct(inc.baseline_success_rate)}</span>
                    <span className="mx-2 text-white/20">→</span>
                    <span className="text-signal-loss">{pct(inc.observed_success_rate)}</span>
                  </span>
                }
                sub={`baseline is this slice at this hour, EWMA'd over prior days`}
              />
            </div>
            <div className="panel p-6">
              <Stat label="Payments affected" value={count(inc.affected_payment_count)} sub={`${count(inc.observed_volume)} in window`} />
            </div>
            <div className="rounded-[28px] border border-signal-loss/20 bg-signal-loss/[0.04] p-6">
              <Stat label="Revenue exposed" value={lakhs(inc.revenue_exposed_paise)} tone="loss" />
            </div>
            <div className="panel p-6">
              <Stat
                label="Would self-recover"
                value={co ? lakhs(co.natural_recovery_paise) : "—"}
                sub={co ? `${pct(co.natural_recovery_paise / Math.max(co.revenue_exposed_paise, 1))} of exposure` : undefined}
                tone="muted"
              />
            </div>
            <div className="rounded-[28px] border border-cyber/25 bg-cyber/[0.05] p-6">
              <Stat
                label="Addressable"
                value={co ? lakhs(co.addressable_paise) : "—"}
                sub="exposure minus what arrives anyway"
                tone="yellow"
              />
            </div>
          </div>

          <div className="mt-6 grid gap-6 xl:grid-cols-[1.5fr_1fr]">
            {/* ------------------------------------------------- chart */}
            <Panel title="Success rate through the incident" hint="Each point is the most significant window ending at that tick.">
              <div className="h-72 p-6">
                {series.length > 1 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={series} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                      <defs>
                        <linearGradient id="obs" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#FF5D5D" stopOpacity={0.35} />
                          <stop offset="100%" stopColor="#FF5D5D" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="#ffffff10" vertical={false} />
                      <XAxis dataKey="t" tick={{ fill: "#ffffff40", fontSize: 11 }} tickLine={false} axisLine={false} />
                      <YAxis domain={[0, 100]} tick={{ fill: "#ffffff40", fontSize: 11 }} tickLine={false} axisLine={false} unit="%" />
                      <Tooltip
                        contentStyle={{
                          background: "#171717", border: "1px solid #ffffff18",
                          borderRadius: 16, fontSize: 12,
                        }}
                        labelStyle={{ color: "#ffffff70" }}
                      />
                      <ReferenceLine
                        y={+(inc.baseline_success_rate * 100).toFixed(1)}
                        stroke="#FDE047" strokeDasharray="4 4"
                        label={{ value: "baseline", fill: "#FDE047", fontSize: 10, position: "right" }}
                      />
                      <Area type="monotone" dataKey="observed" stroke="#FF5D5D" strokeWidth={2} fill="url(#obs)" />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="grid h-full place-items-center text-xs text-white/30">
                    Not enough ticks to plot.
                  </div>
                )}
              </div>
            </Panel>

            {/* --------------------------------------------- error mix */}
            <Panel title="Failure mix in the window" hint="Concentration in one reason code is what separates an infrastructure fault from ordinary noise.">
              <div className="space-y-3 p-6">
                {inc.failure_mix.slice(0, 8).map((row) => {
                  const share = row.count / Math.max(inc.affected_payment_count, 1);
                  return (
                    <div key={`${row.reason}`}>
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="truncate font-mono text-[11px] text-white/70">
                          {row.reason ?? "unknown"}
                        </span>
                        <span className="tnum shrink-0 text-[11px] text-white/40">
                          {count(row.count)} · {pct(share, 0)}
                        </span>
                      </div>
                      <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-white/[0.06]">
                        <div className="h-full rounded-full bg-cyber/70" style={{ width: `${share * 100}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </Panel>
          </div>

          {/* ---------------------------------------------- why detected */}
          <Panel className="mt-6" title="Why this was called an incident" hint="The detector's own reasoning, not a summary of it.">
            <div className="p-6">
              <p className="max-w-5xl text-[13px] leading-relaxed text-white/60">
                {inc.detection_rationale}
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                <Tag tone="neutral">p = {sci(inc.p_value)}</Tag>
                <Tag tone="yellow">q = {sci(inc.q_value)}</Tag>
                {inc.signals[0]?.rolled_up_from.length ? (
                  <Tag tone="info">
                    rolled up from {inc.signals[0].rolled_up_from.length} child slices
                  </Tag>
                ) : null}
              </div>
            </div>
          </Panel>

          {/* ------------------------------------------------ exceptions */}
          {co && co.exceptions > 0 && (
            <Panel
              className="mt-6"
              title="Payments we could not act on"
              hint="Surfaced by name rather than quietly dropped. An honest exception list is worth more than a confident wrong answer."
            >
              <div className="flex flex-wrap gap-3 p-6">
                {Object.entries(co.exceptions_by_reason).map(([reason, n]) => (
                  <div key={reason} className="rounded-[20px] border border-white/[0.08] bg-white/[0.02] px-5 py-3">
                    <div className="tnum text-xl font-bold">{n}</div>
                    <div className="mt-0.5 text-[11px] text-white/40">{titleise(reason)}</div>
                  </div>
                ))}
              </div>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
