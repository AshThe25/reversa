import { useNavigate, useParams } from "react-router-dom";
import {
  Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import {
  Button, ErrorNote, Label, Money, Panel, Severity, Skeleton, Stat, Tag,
} from "../components/primitives";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { count, pct, sci, timeIST, titleise } from "../lib/format";
import type { Investigation } from "../lib/types";

export function IncidentDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const incident = useAsync(() => api.incident(id), [id]);
  const cohort = useAsync(() => api.cohort(id), [id]);
  const probe = useAsync(() => api.investigation(id), [id]);

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
              Model treatments →
            </Button>
          </div>

          {/* ------------------------------------------------------ tiles */}
          <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <div className="panel p-6">
              <Stat
                label="Auth rate"
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
            {/* Once the cohort is loaded every figure comes from it, so the
                denominators match. The incident's own exposure is measured on
                the detector's peak window while the cohort spans the whole
                episode - showing one against the other made "would self-recover"
                exceed "revenue exposed". */}
            <div className="hero-loss p-6">
              <Label>Revenue exposed</Label>
              <div className="mt-2 text-[30px] font-bold leading-none tracking-tight">
                <Money
                  paise={co ? co.revenue_exposed_paise : inc.revenue_exposed_paise}
                  tone="loss"
                />
              </div>
              <p className="mt-2 text-xs text-white/40">
                {co ? `${count(co.member_count)} recoverable payments` : "peak window"}
              </p>
            </div>
            <div className="hero-neutral p-6">
              <Label>Baseline recovery</Label>
              <div className="mt-2 text-[30px] font-bold leading-none tracking-tight">
                {co ? <Money paise={co.natural_recovery_paise} tone="muted" /> : "—"}
              </div>
              <p className="mt-2 text-xs text-white/40">
                {co
                  ? `${pct(co.natural_recovery_paise / Math.max(co.revenue_exposed_paise, 1))} of exposure — lands with no treatment`
                  : ""}
              </p>
            </div>
            <div className="hero-accent p-6">
              <Label>Addressable</Label>
              <div className="mt-2 text-[30px] font-bold leading-none tracking-tight">
                {co ? <Money paise={co.addressable_paise} tone="yellow" /> : "—"}
              </div>
              <p className="mt-2 text-xs text-white/40">the only part worth treating</p>
            </div>
          </div>

          <div className="mt-6 grid gap-6 xl:grid-cols-[1.5fr_1fr]">
            {/* ------------------------------------------------- chart */}
            <Panel title="Auth rate through the incident" hint="Each point is the most significant window ending at that tick.">
              <div className="h-72 p-6">
                {series.length > 1 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={series} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                      <defs>
                        <linearGradient id="obs" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#FF5D5D" stopOpacity={0.45} />
                          <stop offset="55%" stopColor="#FF5D5D" stopOpacity={0.12} />
                          <stop offset="100%" stopColor="#FF5D5D" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
                      <XAxis dataKey="t" tick={{ fill: "#ffffff40", fontSize: 11 }} tickLine={false} axisLine={false} />
                      <YAxis domain={[0, 100]} tick={{ fill: "#ffffff40", fontSize: 11 }} tickLine={false} axisLine={false} unit="%" />
                      <Tooltip
                        contentStyle={{
                          background: "rgba(18,18,18,0.94)",
                          border: "1px solid rgba(255,255,255,0.12)",
                          borderRadius: 18, fontSize: 12,
                          boxShadow: "0 24px 48px -24px rgba(0,0,0,0.9)",
                        }}
                        labelStyle={{ color: "#ffffff70" }}
                      />
                      <ReferenceLine
                        y={+(inc.baseline_success_rate * 100).toFixed(1)}
                        stroke="#FDE047" strokeDasharray="4 4"
                        label={{ value: "baseline", fill: "#FDE047", fontSize: 10, position: "right" }}
                      />
                      <Area
                        type="monotone" dataKey="observed" stroke="#FF5D5D"
                        strokeWidth={2} fill="url(#obs)"
                        animationDuration={520} animationEasing="ease-out"
                      />
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
            <Panel title="Decline-code mix" hint="Concentration in one reason code separates an infrastructure fault from ordinary noise.">
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

          {probe.data && <InvestigationPanel finding={probe.data} />}

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
              title="Suppressed by a compliance gate"
              hint="Surfaced by name rather than quietly dropped. An honest exception list is worth more than a confident wrong answer."
            >
              <div className="flex flex-wrap gap-3 p-6">
                {Object.entries(co.exceptions_by_reason).map(([reason, n]) => (
                  <div key={reason} className="surface px-5 py-3">
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


/**
 * Root-cause finding, and the evidence it rests on.
 *
 * Every claim cites evidence by id, and a citation that does not resolve
 * rejects the whole finding — the groundedness figure reports that check. The
 * refusal state gets more visual weight than the confident one on purpose:
 * knowing when not to act is the harder property to demonstrate.
 */
function InvestigationPanel({ finding }: { finding: Investigation }) {
  const supporting = new Set(finding.supporting_evidence);
  const contradicting = new Set(finding.contradicting_evidence);

  return (
    <div
      className={`mt-6 ${
        finding.insufficient_evidence ? "surface-alarm" : "surface"
      } overflow-hidden`}
    >
      <div className="grid gap-8 p-6 lg:grid-cols-[1.05fr_1fr]">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Label>Root-cause finding</Label>
            <Tag tone={finding.produced_by === "llm" ? "info" : "neutral"}>
              {finding.produced_by === "llm" ? "language model" : "rule-based"}
            </Tag>
            {finding.produced_by === "llm" && (
              <Tag tone={finding.groundedness === 1 ? "good" : "bad"}>
                {pct(finding.groundedness, 0)} grounded
              </Tag>
            )}
          </div>

          <h2
            className={`mt-3 text-2xl font-bold tracking-tight ${
              finding.insufficient_evidence ? "text-signal-loss" : ""
            }`}
          >
            {finding.insufficient_evidence
              ? "Root cause not attributable"
              : finding.root_cause_label}
          </h2>

          <div className="mt-4 flex items-center gap-4">
            <div>
              <Label>Confidence</Label>
              <div
                className={`tnum mt-1 text-3xl font-bold ${
                  finding.actionable ? "text-cyber" : "text-signal-loss"
                }`}
              >
                {pct(finding.confidence, 0)}
              </div>
            </div>
            <div className="h-10 w-px bg-white/10" />
            <div>
              <Label>Automation</Label>
              <p className="mt-1 text-sm font-semibold">
                {finding.actionable ? "permitted" : "withheld"}
              </p>
            </div>
          </div>

          <p className="mt-5 max-w-2xl text-[13px] leading-relaxed text-white/60">
            {finding.hypothesis}
          </p>

          <div className="mt-5 rounded-[18px] border border-white/[0.08] bg-black/25 px-5 py-4">
            <Label>Recommended next step</Label>
            <p className="mt-1.5 text-[12px] leading-relaxed text-white/60">
              {finding.recommended_next_step}
            </p>
          </div>
        </div>

        <div>
          <Label>
            Evidence · {finding.evidence.length} facts (
            {finding.supporting_evidence.length} supporting,{" "}
            {finding.contradicting_evidence.length} contradicting)
          </Label>
          <div className="mt-4 space-y-2">
            {finding.evidence.map((e) => {
              const cited = supporting.has(e.id) || contradicting.has(e.id);
              const against = contradicting.has(e.id);
              return (
                <div
                  key={e.id}
                  className={`flex gap-3 rounded-[16px] border px-4 py-3 ${
                    against
                      ? "border-signal-loss/25 bg-signal-loss/[0.05]"
                      : cited
                        ? "border-cyber/25 bg-cyber/[0.04]"
                        : "border-white/[0.06] bg-white/[0.015] opacity-55"
                  }`}
                >
                  <span
                    className={`mt-0.5 font-mono text-[11px] ${
                      against ? "text-signal-loss" : cited ? "text-cyber" : "text-white/30"
                    }`}
                  >
                    {against ? "−" : cited ? "+" : "·"}
                  </span>
                  <div className="min-w-0">
                    <p className="text-[12px] leading-relaxed text-white/70">{e.label}</p>
                    <p className="mt-1 font-mono text-[10px] text-white/30">
                      {e.id} · {e.source}
                      {e.sample_size ? ` · n=${e.sample_size.toLocaleString("en-IN")}` : ""}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="border-t border-white/[0.06] px-6 py-4">
        <p className="max-w-4xl text-[11px] leading-relaxed text-white/35">
          The model may not invent a hypothesis — the label comes from a fixed
          vocabulary — and every evidence id it cites is checked against the facts
          actually collected. One fabricated citation rejects the whole response and
          the rule-based investigator answers instead. No money path reads this
          finding; it gates whether a plan may be built at all.
        </p>
      </div>
    </div>
  );
}
