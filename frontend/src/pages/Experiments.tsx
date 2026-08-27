import { Bar, ErrorNote, Label, Panel, Skeleton, Stat, Tag } from "../components/primitives";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { count, lakhs, pct, rupees, signedPct } from "../lib/format";
import type { ExperimentResult } from "../lib/types";

export function Experiments() {
  const { data, loading, error } = useAsync(() => api.experiments(), []);
  const concluded = data?.filter((e) => e.status === "concluded" && "incremental_paise" in e.results) ?? [];

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      <Label>Randomised measurement</Label>
      <h1 className="mt-2 text-4xl font-bold tracking-tight">Experiments</h1>
      <p className="mt-3 max-w-3xl text-sm leading-relaxed text-black/45">
        Every recovery run withholds treatment from a randomly assigned slice of the
        plan, stratified on order value. Assignment is <code className="text-black/60">sha256(experiment_id ‖ customer_id)</code> —
        deterministic, keyed on the customer so nobody is half-treated, and recomputable
        by hand from the stored hash prefix.
      </p>

      {error && (
        <div className="mt-6">
          <ErrorNote message={error.message} requestId={error.requestId} />
        </div>
      )}
      {loading && <Skeleton rows={5} />}

      {data && concluded.length === 0 && (
        <Panel className="mt-8">
          <div className="px-6 py-16 text-center">
            <p className="text-sm text-black/50">No experiment has concluded yet.</p>
            <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-black/25">
              Deploy a strategy from Futures to create one. A guest session can model but
              not execute, so this page stays empty unless an operator runs it.
            </p>
          </div>
        </Panel>
      )}

      <div className="mt-8 space-y-6">
        {concluded.map((e) => (
          <ExperimentCard key={e.id} name={e.name} result={e.results as ExperimentResult} />
        ))}
      </div>
    </div>
  );
}

function ExperimentCard({ name, result: r }: { name: string; result: ExperimentResult }) {
  const arms = Object.values(r.arms).sort((a, b) => b.payments - a.payments);
  const treatment = r.arms["treatment"];
  const holdout = r.arms["holdout"];
  const maxRate = Math.max(...arms.map((a) => a.recovery_rate), 0.01);

  return (
    <Panel title={name} hint={r.experiment_id}>
      <div className="grid gap-8 p-6 lg:grid-cols-[1.1fr_1fr]">
        {/* ------------------------------------------------- headline */}
        <div>
          <div className="grid gap-6 sm:grid-cols-3">
            <Stat label="Gross recovery" value={lakhs(r.gross_recovery_paise)} tone="muted" sub="what a conventional tool books" />
            <Stat label="Baseline (holdout)" value={lakhs(r.natural_recovery_paise)} tone="muted" sub="landed with no treatment" />
            <Stat label="Incremental lift" value={lakhs(r.incremental_paise)} tone="yellow" sub="attributable to treatment" />
          </div>

          <div className="mt-7 rounded-[20px] border border-black/15 bg-black/[0.03] p-5">
            <Label>90% confidence interval</Label>
            <div className="tnum mt-2 text-lg font-semibold">
              [{lakhs(r.incremental_lo_paise)}, {lakhs(r.incremental_hi_paise)}]
            </div>
            <p className="mt-2 text-[11px] leading-relaxed text-black/35">
              Customer-level bootstrap over {count(r.bootstrap_samples)} resamples. Recovered
              amounts are heavily skewed — one large payment moves the estimate more than
              fifty small ones — so a normal approximation here would flatter us.
            </p>
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            <Tag tone={r.significant ? "good" : "neutral"}>
              revenue lift {r.significant ? "significant" : "not significant"}
            </Tag>
            <Tag tone={r.rate_significant ? "good" : "neutral"}>
              rate lift {signedPct(r.rate_lift)} [{signedPct(r.rate_lift_lo)}, {signedPct(r.rate_lift_hi)}]
            </Tag>
            {r.concentrated && <Tag tone="bad">effect concentrated</Tag>}
          </div>
        </div>

        {/* ----------------------------------------------------- arms */}
        <div>
          <Label>Arms</Label>
          <div className="mt-4 space-y-4">
            {arms.map((a) => (
              <div key={a.arm}>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm font-semibold capitalize">{a.arm}</span>
                  <span className="tnum text-xs text-black/40">
                    {count(a.recovered)} / {count(a.payments)} · {pct(a.recovery_rate)}
                  </span>
                </div>
                <div className="mt-2">
                  <Bar
                    value={a.recovery_rate}
                    max={maxRate}
                    tone={a.arm === "treatment" ? "yellow" : "muted"}
                  />
                </div>
                <div className="tnum mt-1.5 text-[11px] text-black/30">
                  {lakhs(a.recovered_paise)} of {lakhs(a.exposure_paise)} exposure
                </div>
              </div>
            ))}
          </div>

          {treatment && holdout && (
            <div className="mt-6 rounded-[18px] border border-black/15 p-5">
              <Label>Cost side</Label>
              <div className="mt-3 space-y-2">
                <Line label="Treatment cost" value={rupees(r.cost_paise)} />
                <Line label="Net incremental lift" value={lakhs(r.net_paise)} />
                <Line label="Measurement cost" value={lakhs(r.measurement_cost_paise)} />
              </div>
              <p className="mt-3 text-[11px] leading-relaxed text-black/30">
                The holdout is revenue deliberately not worked. It is the price of being able
                to make a causal claim at all, and it belongs on the same page as the
                claim.
              </p>
            </div>
          )}
        </div>
      </div>

      {r.warnings.length > 0 && (
        <div className="border-t border-black/15 p-6">
          <Label>Diagnostics</Label>
          <ul className="mt-3 space-y-2">
            {r.warnings.map((w) => (
              <li key={w} className="flex gap-3 text-[12px] leading-relaxed text-black/50">
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

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[11px] text-black/40">{label}</span>
      <span className="tnum text-[13px] font-semibold">{value}</span>
    </div>
  );
}
