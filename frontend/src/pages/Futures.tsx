import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Bar as RBar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import {
  Bar, Button, ErrorNote, Glass, Label, Panel, Skeleton, Spinner, Tag,
} from "../components/primitives";
import { useAsync } from "../hooks/useAsync";
import { ApiError, api, can } from "../lib/api";
import { count, duration, lakhs, pct, rupees, titleise } from "../lib/format";
import type { ExecutionReport, Scenario, WindTunnel } from "../lib/types";

/**
 * The Revenue Wind Tunnel.
 *
 * Nothing on this page is animated to look like computation. Pressing SIMULATE
 * posts the cohort to the optimiser and waits for a real linear program to
 * solve; the elapsed time shown is the time it actually took.
 */
export function Futures() {
  const [params, setParams] = useSearchParams();
  const incidents = useAsync(() => api.incidents(), []);
  const selected = params.get("incident");

  const [run, setRun] = useState<WindTunnel | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [deployed, setDeployed] = useState<ExecutionReport | null>(null);
  const [deploying, setDeploying] = useState(false);

  // Default to the costliest incident whose scope is actually attributable. A
  // diffuse cluster may well be the most expensive thing on the board, but it
  // is the case where automation should stop - opening the tunnel on it would
  // invite exactly the decision the system is built to refuse.
  useEffect(() => {
    if (!selected && incidents.data && incidents.data.length > 0) {
      const attributable = incidents.data.filter((i) => !i.ambiguous);
      const pool = attributable.length ? attributable : incidents.data;
      const worst = pool.reduce((a, b) =>
        a.revenue_exposed_paise >= b.revenue_exposed_paise ? a : b,
      );
      setParams({ incident: worst.id }, { replace: true });
    }
  }, [incidents.data, selected, setParams]);

  useEffect(() => {
    setRun(null);
    setDeployed(null);
    setError(null);
  }, [selected]);

  const simulate = async () => {
    if (!selected) return;
    setRunning(true);
    setError(null);
    try {
      setRun(await api.windTunnel(selected));
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "network", "Request failed."));
    } finally {
      setRunning(false);
    }
  };

  const deploy = async (scenarioKey: string) => {
    if (!selected) return;
    setDeploying(true);
    setError(null);
    try {
      setDeployed(await api.execute({ incident_id: selected, scenario: scenarioKey }));
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "network", "Request failed."));
    } finally {
      setDeploying(false);
    }
  };

  const incident = incidents.data?.find((i) => i.id === selected);
  const best = run?.scenarios.find((s) => s.key === run.best_scenario);
  const baseline = run?.scenarios.find((s) => s.key === "do_nothing");

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Counterfactual scenario analysis</Label>
          <h1 className="mt-2 text-4xl font-bold tracking-tight">Revenue Wind Tunnel</h1>
          <p className="mt-3 max-w-3xl text-sm leading-relaxed text-black/60">
            Rewind the incident and evaluate every treatment strategy against the same
            cohort before a single customer is contacted. Branches differ only in the
            treatment applied — the population, the estimates and the constraints are
            held identical.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <select
            aria-label="Incident"
            value={selected ?? ""}
            onChange={(e) => setParams({ incident: e.target.value })}
            className="rounded-neo border-2 border-black bg-white px-4 py-2 font-display text-[12px] font-extrabold uppercase tracking-tighter shadow-hard-sm"
          >
            {incidents.data?.map((i) => (
              <option key={i.id} value={i.id}>
                {i.slice} · {lakhs(i.revenue_exposed_paise)}
                {i.ambiguous ? " · unattributable" : ""}
              </option>
            ))}
          </select>
          <Button onClick={simulate} disabled={!selected || running || !!incident?.ambiguous}>
            {running ? "Running…" : "Run analysis ▸"}
          </Button>
        </div>
      </div>

      {error && (
        <div className="mt-6">
          <ErrorNote message={error.message} requestId={error.requestId} />
        </div>
      )}

      {incident?.ambiguous && <AmbiguityRefusal incident={incident} />}

      {/* ------------------------------------------------ current reality */}
      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_1.6fr]">
        <Glass className="p-7">
          <Label>Current reality</Label>
          {incident ? (
            <>
              <h2 className="mt-3 text-3xl font-bold tracking-tight">{incident.slice}</h2>
              <p className="mt-1 text-xs text-black/60">{incident.label}</p>
              {/* Once a run exists every figure comes from the cohort, so the
                  denominators match. The incident's own exposure is measured on
                  the detector's peak window while the cohort spans the whole
                  detected episode - showing one against the other produced
                  "arrives with no help" exceeding "revenue exposed", which is
                  nonsense on its face. */}
              <div className="mt-7 space-y-5">
                <Metric
                  label="Revenue exposed"
                  value={lakhs(run ? run.cohort.revenue_exposed_paise : incident.revenue_exposed_paise)}
                  note={run
                    ? `${count(run.candidate_count)} recoverable payments in the cohort`
                    : `peak window · ${count(incident.affected_payment_count)} payments`}
                  tone="loss"
                />
                {run ? (
                  <>
                    <Metric
                      label="Baseline recovery"
                      value={lakhs(run.cohort.natural_recovery_paise)}
                      note={`${pct(
                        run.cohort.natural_recovery_paise /
                          Math.max(run.cohort.revenue_exposed_paise, 1),
                      )} of exposure — a conventional tool books this as recovered`}
                    />
                    <Metric
                      label="Addressable"
                      value={lakhs(run.cohort.addressable_paise)}
                      note="the only part worth treating"
                      tone="yellow"
                    />
                  </>
                ) : (
                  <Metric
                    label="Payments affected"
                    value={count(incident.affected_payment_count)}
                  />
                )}
              </div>
            </>
          ) : (
            <Skeleton rows={4} />
          )}
        </Glass>

        <Panel
          anchor="strategy-chart" title="Candidate strategies"
          hint={
            run
              ? `${count(run.candidate_count)} candidates · solved in ${duration(run.total_ms)}`
              : "Run the analysis to evaluate every branch."
          }
        >
          {incident?.ambiguous && (
            <div className="px-6 py-16 text-center">
              <p className="text-sm font-semibold text-signal-loss-ink">
                No plan is offered for this incident.
              </p>
              <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-black/60">
                Running it would produce a confident-looking treatment plan built on a
                root cause the evidence does not support.
              </p>
            </div>
          )}

          {!run && !running && !incident?.ambiguous && (
            <div className="px-6 py-16 text-center">
              <p className="text-sm text-black/60">No analysis run yet.</p>
              <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-black/60">
                Solves a constrained assignment over every eligible payment and every
                permitted treatment. Nothing here is precomputed.
              </p>
              <div className="mt-6">
                <Button onClick={simulate} disabled={!selected || !!incident?.ambiguous}>
                  Run analysis ▸
                </Button>
              </div>
            </div>
          )}

          {running && (
            <div className="px-6 py-16">
              <Spinner label="Solving the assignment problem" />
            </div>
          )}

          {run && baseline && (
            <>
            {run.stages && run.stages.length > 0 && (
              /* Measured, not scripted. A progress bar that advances on a timer
                 tells a reader nothing about whether work happened; four stages
                 with the milliseconds they actually took cannot drift out of
                 sync with reality. */
              <ol className="stagger divide-y divide-black/10 border-b-2 border-black">
                {run.stages.map((st, i) => (
                  <li key={st.label} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-6 py-3">
                    <span className="tnum w-5 shrink-0 font-mono text-[11px] text-black/60">
                      {i + 1}
                    </span>
                    <span className="text-[13px] font-semibold">{st.label}</span>
                    <span className="min-w-0 flex-1 text-[11px] text-black/60">{st.note}</span>
                    <span className="tnum shrink-0 text-[11px] font-bold">{st.ms}ms</span>
                  </li>
                ))}
              </ol>
            )}

            <div className="h-[320px] p-6">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={run.scenarios.map((s) => ({
                    name: s.label,
                    incremental: +(s.net_incremental_paise / 1e7).toFixed(2),
                    key: s.key,
                  }))}
                  margin={{ top: 12, right: 8, left: -18, bottom: 0 }}
                >
                  {/* Flat fills with a hard black stroke. Gradients belong to
                      the other visual language entirely - here a bar is a
                      physical block, and the stroke is what makes it one. */}
                  <CartesianGrid stroke="#00000018" vertical={false} />
                  <XAxis
                    dataKey="name"
                    tick={{ fill: "#000000", fontSize: 9, fontWeight: 800 }}
                    tickLine={false}
                    axisLine={{ stroke: "#000000", strokeWidth: 2 }}
                    interval={0}
                  />
                  <YAxis
                    tick={{ fill: "#00000099", fontSize: 11 }}
                    tickLine={false}
                    axisLine={{ stroke: "#000000", strokeWidth: 2 }}
                    unit="L"
                  />
                  <Tooltip
                    cursor={{ fill: "#ffe17c55" }}
                    contentStyle={{
                      background: "#ffffff",
                      border: "2px solid #000000",
                      borderRadius: 2,
                      fontSize: 12,
                      fontWeight: 600,
                      boxShadow: "4px 4px 0px 0px #000000",
                    }}
                    labelStyle={{ color: "#000000", fontWeight: 800 }}
                    formatter={(v: number) => [`₹${v}L`, "net incremental lift"]}
                  />
                  <RBar
                    dataKey="incremental"
                    // No radius. A per-corner array here renders the bar group
                    // empty - six <g> elements with nothing inside - so the
                    // chart came up as bare axes on the one screen the whole
                    // argument rests on. Square corners are the design language
                    // anyway; two pixels of rounding was never worth a blank
                    // chart.
                    maxBarSize={64}
                    stroke="#000000"
                    strokeWidth={2}
                    // Recharts renders the bar group empty when the enter
                    // animation is left on here - six <g> elements with no
                    // shape inside - so the chart came up as bare axes on the
                    // one screen the whole argument rests on.
                    isAnimationActive={false}
                  >
                    {run.scenarios.map((s) => (
                      <Cell
                        key={s.key}
                        fill={s.key === run.best_scenario ? "#ffe17c" : "#b7c6c2"}
                      />
                    ))}
                  </RBar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            </>
          )}
        </Panel>
      </div>

      {/* ------------------------------------------------- the comparison */}
      {run && (
        <Panel
          className="mt-6"
          title="Strategy comparison"
          hint="GROSS is what a conventional dunning tool books. INCREMENTAL is what the treatment adds over the baseline that was landing anyway."
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1200px] text-left">
              <thead>
                <tr className="border-b border-black/15">
                  {["Strategy", "Gross", "Baseline", "Incremental", "Treatments", "Capacity", "Cost", "Net", "Non-incremental", "Friction", "Risk", ""].map((h) => (
                    <th key={h} className="label px-5 py-3 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-black/10">
                {run.scenarios.map((s) => (
                  <ScenarioRow
                    key={s.key}
                    scenario={s}
                    best={s.key === run.best_scenario}
                    capacity={run.capacity}
                    onDeploy={() => deploy(s.key)}
                    deploying={deploying}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {best && baseline && (
            <div className="border-t border-black/15 p-6">
              <p className="max-w-4xl text-[13px] leading-relaxed text-black/60">
                <span className="font-semibold text-black">{best.label}</span> recovers{" "}
                <span className="tnum font-semibold text-black">
                  {lakhs(best.incremental_recovery_paise)}
                </span>{" "}
                more than doing nothing, using{" "}
                <span className="tnum font-semibold text-black">{count(best.action_count)}</span>{" "}
                interventions.{" "}
                {(() => {
                  // Compare against the strongest single-action strategy that
                  // actually placed an action. Comparing against one the gates
                  // emptied divides by zero and produced a 7,979,192x claim.
                  const rivals = run.scenarios.filter(
                    (s) => s.key !== best.key && s.key !== "do_nothing" && s.action_count > 0,
                  );
                  if (!rivals.length) return null;
                  const rival = rivals.reduce((a, b) =>
                    a.incremental_recovery_paise >= b.incremental_recovery_paise ? a : b,
                  );
                  if (rival.incremental_recovery_paise <= 0) return null;
                  const ratio =
                    best.incremental_recovery_paise / rival.incremental_recovery_paise;
                  if (!Number.isFinite(ratio) || ratio <= 1.01) return null;
                  return (
                    <>
                      The best single-action strategy,{" "}
                      <span className="font-semibold text-black">{rival.label}</span>, produces{" "}
                      <span className="tnum font-semibold text-black">
                        {lakhs(rival.incremental_recovery_paise)}
                      </span>{" "}
                      from{" "}
                      <span className="tnum font-semibold text-black">
                        {count(rival.action_count)}
                      </span>{" "}
                      actions — the optimiser is{" "}
                      <span className="font-semibold text-black">{ratio.toFixed(1)}×</span>{" "}
                      better because it stops spending capacity on customers who were
                      going to pay anyway.
                    </>
                  );
                })()}
              </p>
            </div>
          )}
        </Panel>
      )}

      {/* ------------------------------------------------------ deployed */}
      {deployed && <DeployedResult report={deployed} />}

      {!can("execute") && run && (
        <div className="mt-6 rounded-[24px] border border-black bg-cyber/20 p-6">
          <Label>Why Deploy is disabled</Label>
          <p className="mt-2 max-w-3xl text-[13px] leading-relaxed text-black/60">
            This is a demo session. It carries <code className="text-black">read</code> and{" "}
            <code className="text-black">simulate</code> scope but not{" "}
            <code className="text-black">execute</code>, so you can explore every future here
            and there is no path from this browser to moving money. The check is enforced
            server-side — the button is disabled as a courtesy, not as the control.
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * The refusal.
 *
 * A degradation that lands on slices with no common parent has no containable
 * scope, so no single root cause is supportable from the evidence. The system
 * detected it, sized it, and then declines to act - which is the correct
 * behaviour and worth showing as prominently as a successful recovery.
 */
function AmbiguityRefusal({ incident }: { incident: import("../lib/types").Incident }) {
  const members = incident.rca_evidence?.diffuse_members ?? [];
  return (
    <div className="mt-8 rounded-[32px] border border-black bg-signal-loss/10 p-8">
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="max-w-3xl">
          <div className="flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-signal-loss/20 text-lg text-signal-loss-ink">
              !
            </span>
            <Label>Root cause uncertain — automation withheld</Label>
          </div>

          <h2 className="mt-4 text-3xl font-bold tracking-tight">
            {lakhs(incident.revenue_exposed_paise)} exposed, and we are not going
            to guess.
          </h2>

          <p className="mt-4 text-[13px] leading-relaxed text-black/60">
            This degradation appeared on {members.length} slices at once with no
            common parent — some UPI handles, some netbanking, some cards. A PSP
            fault would have taken one method down together. A single bad bank
            would have stayed inside one instrument. This did neither, so the
            evidence cannot distinguish merchant-side latency from an upstream
            issue, and any root cause we named would be a guess wearing a
            confidence score.
          </p>

          <p className="mt-3 text-[13px] leading-relaxed text-black/60">
            The detection is sound and the money is real. What is missing is
            attribution, and interventions chosen from a wrong root cause spend
            capacity and customer patience on the wrong people. So it goes to a
            human.
          </p>

          <div className="mt-6 flex flex-wrap gap-2">
            {members.map((m: string) => (
              <Tag key={m} tone="bad">{m}</Tag>
            ))}
          </div>
        </div>

        <div className="min-w-[220px] space-y-5">
          <div>
            <Label>Root-cause confidence</Label>
            <div className="tnum mt-1 text-4xl font-bold text-signal-loss-ink">
              {pct(incident.rca_confidence, 0)}
            </div>
          </div>
          <div>
            <Label>Scope</Label>
            <p className="mt-1 text-sm font-semibold">not contained</p>
          </div>
          <div>
            <Label>Detection</Label>
            <p className="mt-1 text-sm font-semibold">
              q = {incident.q_value.toExponential(1)}
            </p>
            <p className="mt-0.5 text-[11px] text-black/60">the degradation is real</p>
          </div>
          <Button variant="ghost" disabled title="Requires an operator session">
            Send to human review
          </Button>
        </div>
      </div>
    </div>
  );
}

function ScenarioRow({
  scenario: s, best, capacity, onDeploy, deploying,
}: {
  scenario: Scenario;
  best: boolean;
  capacity: Record<string, number>;
  onDeploy: () => void;
  deploying: boolean;
}) {
  const capacityBound = s.exhausted.length > 0;
  const totalCap = Object.values(capacity).reduce((a, b) => a + b, 0);

  return (
    <tr className={best ? "bg-cyber/20" : "row-hover"}>
      <td className="px-5 py-4">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-bold ${best ? "text-black" : ""}`}>{s.label}</span>
          {best && <Tag tone="yellow">BEST</Tag>}
        </div>
        <p className="mt-1 max-w-xs text-[11px] leading-relaxed text-black/60">{s.description}</p>
        {s.action_count === 0 && s.key !== "do_nothing" && s.notes.length > 0 && (
          <p className="mt-2 max-w-xs text-[11px] leading-relaxed text-signal-loss-ink/80">
            {s.notes[0]}
          </p>
        )}
      </td>
      <td className="tnum px-5 py-4 text-sm text-black/60">{lakhs(s.gross_recovery_paise)}</td>
      <td className="tnum px-5 py-4 text-sm text-black/60">{lakhs(s.natural_recovery_paise)}</td>
      <td className={`tnum px-5 py-4 text-base font-bold ${best ? "text-black" : "text-black"}`}>
        {lakhs(s.incremental_recovery_paise)}
      </td>
      <td className="tnum px-5 py-4 text-sm text-black/60">{count(s.action_count)}</td>
      <td className="px-5 py-4">
        <div className="w-24">
          <Bar value={s.action_count} max={totalCap} tone={capacityBound ? "loss" : "yellow"} />
        </div>
        {capacityBound && (
          <span className="mt-1 block text-[10px] text-signal-loss-ink">
            {s.exhausted.map(titleise).join(", ")} exhausted
          </span>
        )}
      </td>
      <td className="tnum px-5 py-4 text-sm text-black/60">{rupees(s.cost_paise)}</td>
      <td className="tnum px-5 py-4 text-sm font-semibold">{lakhs(s.net_incremental_paise)}</td>
      <td className="tnum px-5 py-4 text-sm text-black/60" title="Treatments applied to payments the model expects to recover without them">
        {count(s.wasted_actions)}
      </td>
      <td className="tnum px-5 py-4 text-sm text-black/60">{s.friction.toFixed(1)}</td>
      <td className="px-5 py-4">
        <div className="w-14">
          <Bar value={s.risk_score} max={1} tone={s.risk_score > 0.5 ? "loss" : "muted"} />
        </div>
      </td>
      <td className="px-5 py-4 text-right">
        {s.action_count > 0 && (
          <Button
            variant={best ? "solid" : "ghost"}
            disabled={!can("execute") || deploying}
            onClick={onDeploy}
            title={can("execute") ? "Deploy this strategy" : "Demo sessions cannot execute"}
          >
            Deploy
          </Button>
        )}
      </td>
    </tr>
  );
}

function DeployedResult({ report }: { report: ExecutionReport }) {
  const r = report.result;
  const balance = report.balance["_balance"] as { mean_ticket_ratio: number; balanced: boolean } | undefined;

  const arms = useMemo(
    () => Object.values(r.arms).sort((a, b) => b.payments - a.payments),
    [r.arms],
  );

  return (
    <Panel
      className="mt-6"
      title="Deployed · measured against holdout"
      hint="What we predicted, against what the holdout actually showed."
    >
      <div className="grid gap-6 p-6 lg:grid-cols-[1fr_1.2fr]">
        <div className="space-y-5">
          <div>
            <Label>Projected lift</Label>
            <div className="tnum mt-1 text-2xl font-bold text-black/60">
              {lakhs(report.projected_incremental_paise)}
            </div>
          </div>
          <div>
            <Label>Measured lift</Label>
            <div className="tnum mt-1 text-5xl font-bold tracking-tight text-black">
              {lakhs(r.incremental_paise)}
            </div>
            <p className="tnum mt-2 text-[12px] text-black/60">
              90% CI [{lakhs(r.incremental_lo_paise)}, {lakhs(r.incremental_hi_paise)}] ·{" "}
              {r.bootstrap_samples.toLocaleString("en-IN")} bootstrap resamples
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Tag tone={r.significant ? "good" : "neutral"}>
              revenue lift {r.significant ? "significant" : "not significant"}
            </Tag>
            <Tag tone={r.rate_significant ? "good" : "neutral"}>
              rate lift {r.rate_significant ? "significant" : "not significant"}
            </Tag>
            {balance && (
              <Tag tone={balance.balanced ? "good" : "bad"}>
                arms {balance.balanced ? "balanced" : "imbalanced"} ({balance.mean_ticket_ratio}×)
              </Tag>
            )}
          </div>
        </div>

        <div>
          <Label>Arms</Label>
          <div className="mt-3 space-y-3">
            {arms.map((a) => (
              <div key={a.arm} className="rounded-[18px] border border-black/15 bg-black/[0.03] px-5 py-4">
                <div className="flex items-baseline justify-between">
                  <span className="text-sm font-semibold capitalize">{a.arm}</span>
                  <span className="tnum text-xs text-black/60">{count(a.payments)} payments</span>
                </div>
                <div className="mt-2 flex items-baseline justify-between">
                  <span className="tnum text-2xl font-bold">{pct(a.recovery_rate)}</span>
                  <span className="tnum text-sm text-black/60">
                    {lakhs(a.recovered_paise)} of {lakhs(a.exposure_paise)}
                  </span>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 rounded-[18px] border border-black/15 px-5 py-4">
            <div className="flex items-baseline justify-between">
              <span className="text-[11px] text-black/60">Cost of measurement</span>
              <span className="tnum text-sm font-semibold">{lakhs(r.measurement_cost_paise)}</span>
            </div>
            <p className="mt-1.5 text-[11px] leading-relaxed text-black/60">
              Revenue the holdout was deliberately not chased for. Stated rather than hidden —
              it is the price of being able to make a causal claim at all.
            </p>
          </div>
        </div>
      </div>

      {r.warnings.length > 0 && (
        <div className="border-t border-black/15 p-6">
          <Label>The system's own caveats</Label>
          <ul className="mt-3 space-y-2">
            {r.warnings.map((w) => (
              <li key={w} className="flex gap-3 text-[12px] leading-relaxed text-black/60">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-cyber" />
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

function Metric({
  label, value, note, tone = "default",
}: {
  label: string;
  value: string;
  note?: string;
  tone?: "default" | "loss" | "yellow";
}) {
  const colour = { default: "text-black", loss: "text-signal-loss-ink", yellow: "text-black" }[tone];
  return (
    <div>
      <Label>{label}</Label>
      <div className={`tnum mt-1 text-2xl font-bold tracking-tight ${colour}`}>{value}</div>
      {note && <p className="mt-0.5 text-[11px] text-black/60">{note}</p>}
    </div>
  );
}
