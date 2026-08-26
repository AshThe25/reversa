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
          <Label>Counterfactual simulation</Label>
          <h1 className="mt-2 text-5xl font-bold tracking-tight">Revenue Wind Tunnel</h1>
          <p className="mt-3 max-w-3xl text-sm leading-relaxed text-white/45">
            Rewind the incident and run the alternative futures over the same cohort,
            before spending a single customer interaction. Every branch starts from
            identical reality and differs only in what we did.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={selected ?? ""}
            onChange={(e) => setParams({ incident: e.target.value })}
            className="rounded-full border border-white/12 bg-charcoal px-4 py-2 text-sm text-white/80 outline-none focus:border-cyber/50"
          >
            {incidents.data?.map((i) => (
              <option key={i.id} value={i.id}>
                {i.slice} · {lakhs(i.revenue_exposed_paise)}
                {i.ambiguous ? " · unattributable" : ""}
              </option>
            ))}
          </select>
          <Button onClick={simulate} disabled={!selected || running || !!incident?.ambiguous}>
            {running ? "Simulating…" : "Simulate ▸"}
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
              <p className="mt-1 text-xs text-white/40">{incident.label}</p>
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
                      label="Arrives with no help"
                      value={lakhs(run.cohort.natural_recovery_paise)}
                      note={`${pct(
                        run.cohort.natural_recovery_paise /
                          Math.max(run.cohort.revenue_exposed_paise, 1),
                      )} of exposure — a conventional tool counts this as recovered`}
                    />
                    <Metric
                      label="Addressable"
                      value={lakhs(run.cohort.addressable_paise)}
                      note="the only part worth spending on"
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
          title="Alternative futures"
          hint={
            run
              ? `${count(run.candidate_count)} candidates · solved in ${duration(run.total_ms)}`
              : "Press Simulate to evaluate every branch."
          }
        >
          {incident?.ambiguous && (
            <div className="px-6 py-16 text-center">
              <p className="text-sm font-semibold text-signal-loss">
                No plan is offered for this incident.
              </p>
              <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-white/35">
                Simulating it would produce a confident-looking set of futures
                built on a root cause the evidence does not support.
              </p>
            </div>
          )}

          {!run && !running && !incident?.ambiguous && (
            <div className="px-6 py-16 text-center">
              <p className="text-sm text-white/45">Nothing simulated yet.</p>
              <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-white/25">
                The tunnel solves a linear program over every candidate and every
                legal action. Nothing here is precomputed.
              </p>
              <div className="mt-6">
                <Button onClick={simulate} disabled={!selected || !!incident?.ambiguous}>
                  Simulate ▸
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
            <div className="h-[320px] p-6">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={run.scenarios.map((s) => ({
                    name: s.label,
                    incremental: +(s.net_incremental_paise / 1e7).toFixed(2),
                    key: s.key,
                  }))}
                  margin={{ top: 8, right: 8, left: -20, bottom: 0 }}
                >
                  <CartesianGrid stroke="#ffffff10" vertical={false} />
                  <XAxis dataKey="name" tick={{ fill: "#ffffff45", fontSize: 10 }} tickLine={false} axisLine={false} interval={0} />
                  <YAxis tick={{ fill: "#ffffff40", fontSize: 11 }} tickLine={false} axisLine={false} unit="L" />
                  <Tooltip
                    cursor={{ fill: "#ffffff08" }}
                    contentStyle={{ background: "#171717", border: "1px solid #ffffff18", borderRadius: 16, fontSize: 12 }}
                    formatter={(v: number) => [`₹${v}L`, "net incremental"]}
                  />
                  <RBar dataKey="incremental" radius={[8, 8, 0, 0]}>
                    {run.scenarios.map((s) => (
                      <Cell key={s.key} fill={s.key === run.best_scenario ? "#FDE047" : "#ffffff22"} />
                    ))}
                  </RBar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>
      </div>

      {/* ------------------------------------------------- the comparison */}
      {run && (
        <Panel
          className="mt-6"
          title="Every future, side by side"
          hint="GROSS is what a conventional tool would report. INCREMENTAL is what the intervention actually adds on top of what was arriving anyway."
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1200px] text-left">
              <thead>
                <tr className="border-b border-white/[0.06]">
                  {["Scenario", "Gross", "Natural", "Incremental", "Actions", "Capacity", "Cost", "Net", "Wasted", "Friction", "Risk", ""].map((h) => (
                    <th key={h} className="label px-5 py-3 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
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
            <div className="border-t border-white/[0.06] p-6">
              <p className="max-w-4xl text-[13px] leading-relaxed text-white/55">
                <span className="font-semibold text-cyber">{best.label}</span> recovers{" "}
                <span className="tnum font-semibold text-white">
                  {lakhs(best.incremental_recovery_paise)}
                </span>{" "}
                more than doing nothing, using{" "}
                <span className="tnum font-semibold text-white">{count(best.action_count)}</span>{" "}
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
                      <span className="font-semibold text-white">{rival.label}</span>, produces{" "}
                      <span className="tnum font-semibold text-white">
                        {lakhs(rival.incremental_recovery_paise)}
                      </span>{" "}
                      from{" "}
                      <span className="tnum font-semibold text-white">
                        {count(rival.action_count)}
                      </span>{" "}
                      actions — the optimiser is{" "}
                      <span className="font-semibold text-cyber">{ratio.toFixed(1)}×</span>{" "}
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
        <div className="mt-6 rounded-[24px] border border-cyber/20 bg-cyber/[0.04] p-6">
          <Label>Why Deploy is disabled</Label>
          <p className="mt-2 max-w-3xl text-[13px] leading-relaxed text-white/60">
            This is a demo session. It carries <code className="text-cyber">read</code> and{" "}
            <code className="text-cyber">simulate</code> scope but not{" "}
            <code className="text-cyber">execute</code>, so you can explore every future here
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
    <div className="mt-8 rounded-[32px] border border-signal-loss/25 bg-signal-loss/[0.05] p-8">
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="max-w-3xl">
          <div className="flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-signal-loss/20 text-lg text-signal-loss">
              !
            </span>
            <Label>Root cause uncertain — automation withheld</Label>
          </div>

          <h2 className="mt-4 text-3xl font-bold tracking-tight">
            {lakhs(incident.revenue_exposed_paise)} exposed, and we are not going
            to guess.
          </h2>

          <p className="mt-4 text-[13px] leading-relaxed text-white/55">
            This degradation appeared on {members.length} slices at once with no
            common parent — some UPI handles, some netbanking, some cards. A PSP
            fault would have taken one method down together. A single bad bank
            would have stayed inside one instrument. This did neither, so the
            evidence cannot distinguish merchant-side latency from an upstream
            issue, and any root cause we named would be a guess wearing a
            confidence score.
          </p>

          <p className="mt-3 text-[13px] leading-relaxed text-white/55">
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
            <div className="tnum mt-1 text-4xl font-bold text-signal-loss">
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
            <p className="mt-0.5 text-[11px] text-white/35">the degradation is real</p>
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
    <tr className={best ? "bg-cyber/[0.05]" : "row-hover"}>
      <td className="px-5 py-4">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-bold ${best ? "text-cyber" : ""}`}>{s.label}</span>
          {best && <Tag tone="yellow">BEST</Tag>}
        </div>
        <p className="mt-1 max-w-xs text-[11px] leading-relaxed text-white/30">{s.description}</p>
        {s.action_count === 0 && s.key !== "do_nothing" && s.notes.length > 0 && (
          <p className="mt-2 max-w-xs text-[11px] leading-relaxed text-signal-loss/80">
            {s.notes[0]}
          </p>
        )}
      </td>
      <td className="tnum px-5 py-4 text-sm text-white/50">{lakhs(s.gross_recovery_paise)}</td>
      <td className="tnum px-5 py-4 text-sm text-white/35">{lakhs(s.natural_recovery_paise)}</td>
      <td className={`tnum px-5 py-4 text-base font-bold ${best ? "text-cyber" : "text-white"}`}>
        {lakhs(s.incremental_recovery_paise)}
      </td>
      <td className="tnum px-5 py-4 text-sm text-white/60">{count(s.action_count)}</td>
      <td className="px-5 py-4">
        <div className="w-24">
          <Bar value={s.action_count} max={totalCap} tone={capacityBound ? "loss" : "yellow"} />
        </div>
        {capacityBound && (
          <span className="mt-1 block text-[10px] text-signal-loss">
            {s.exhausted.map(titleise).join(", ")} exhausted
          </span>
        )}
      </td>
      <td className="tnum px-5 py-4 text-sm text-white/50">{rupees(s.cost_paise)}</td>
      <td className="tnum px-5 py-4 text-sm font-semibold">{lakhs(s.net_incremental_paise)}</td>
      <td className="tnum px-5 py-4 text-sm text-white/40" title="Actions aimed at customers the model expects to recover anyway">
        {count(s.wasted_actions)}
      </td>
      <td className="tnum px-5 py-4 text-sm text-white/40">{s.friction.toFixed(1)}</td>
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
      title="Deployed and measured"
      hint="Projection versus what the randomised holdout actually showed."
    >
      <div className="grid gap-6 p-6 lg:grid-cols-[1fr_1.2fr]">
        <div className="space-y-5">
          <div>
            <Label>Projected before deploying</Label>
            <div className="tnum mt-1 text-2xl font-bold text-white/45">
              {lakhs(report.projected_incremental_paise)}
            </div>
          </div>
          <div>
            <Label>Measured against the holdout</Label>
            <div className="tnum mt-1 text-5xl font-bold tracking-tight text-cyber">
              {lakhs(r.incremental_paise)}
            </div>
            <p className="tnum mt-2 text-[12px] text-white/40">
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
              <div key={a.arm} className="rounded-[18px] border border-white/[0.07] bg-white/[0.02] px-5 py-4">
                <div className="flex items-baseline justify-between">
                  <span className="text-sm font-semibold capitalize">{a.arm}</span>
                  <span className="tnum text-xs text-white/40">{count(a.payments)} payments</span>
                </div>
                <div className="mt-2 flex items-baseline justify-between">
                  <span className="tnum text-2xl font-bold">{pct(a.recovery_rate)}</span>
                  <span className="tnum text-sm text-white/50">
                    {lakhs(a.recovered_paise)} of {lakhs(a.exposure_paise)}
                  </span>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 rounded-[18px] border border-white/[0.07] px-5 py-4">
            <div className="flex items-baseline justify-between">
              <span className="text-[11px] text-white/40">Cost of measurement</span>
              <span className="tnum text-sm font-semibold">{lakhs(r.measurement_cost_paise)}</span>
            </div>
            <p className="mt-1.5 text-[11px] leading-relaxed text-white/30">
              Revenue the holdout was deliberately not chased for. Stated rather than hidden —
              it is the price of being able to make a causal claim at all.
            </p>
          </div>
        </div>
      </div>

      {r.warnings.length > 0 && (
        <div className="border-t border-white/[0.06] p-6">
          <Label>The system's own caveats</Label>
          <ul className="mt-3 space-y-2">
            {r.warnings.map((w) => (
              <li key={w} className="flex gap-3 text-[12px] leading-relaxed text-white/50">
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
  const colour = { default: "text-white", loss: "text-signal-loss", yellow: "text-cyber" }[tone];
  return (
    <div>
      <Label>{label}</Label>
      <div className={`tnum mt-1 text-2xl font-bold tracking-tight ${colour}`}>{value}</div>
      {note && <p className="mt-0.5 text-[11px] text-white/30">{note}</p>}
    </div>
  );
}
