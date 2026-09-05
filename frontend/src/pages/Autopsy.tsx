import { useMemo } from "react";

import { ErrorNote, Label, Panel, Skeleton, Stat, Tag } from "../components/primitives";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { count, lakhs, pct, rupees } from "../lib/format";
import type { ExperimentResult } from "../lib/types";

/**
 * Where did the money go.
 *
 * Post-incident forensics on a concluded run: exposure decomposed into what
 * arrived on its own, what the intervention caused, and what was simply lost.
 * The point is to learn from an incident rather than close it, so the page
 * leads with the least flattering number — remaining loss — and names the
 * largest wasted intervention alongside the best one.
 */
export function Autopsy() {
  const experiments = useAsync(() => api.experiments(), []);
  const incidents = useAsync(() => api.incidents(), []);

  const concluded = useMemo(
    () =>
      (experiments.data ?? []).filter(
        (e) => e.status === "concluded" && "incremental_paise" in e.results,
      ),
    [experiments.data],
  );

  const totalExposed = (incidents.data ?? []).reduce(
    (sum, i) => sum + i.revenue_exposed_paise, 0,
  );

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      <Label>Post-incident forensics</Label>
      <h1 className="mt-2 text-4xl font-bold tracking-tight">Where did the money go?</h1>
      <p className="mt-3 max-w-3xl text-sm leading-relaxed text-black/60">
        Exposure decomposed into baseline recovery, the lift the treatment actually
        caused, and unrecovered revenue. The last number is the largest one, and it
        stays on the page.
      </p>

      {experiments.error && (
        <div className="mt-6">
          <ErrorNote message={experiments.error.message} requestId={experiments.error.requestId} />
        </div>
      )}
      {experiments.loading && <Skeleton rows={6} />}

      {concluded.length === 0 && !experiments.loading && (
        <Panel className="mt-8">
          <div className="px-6 py-16 text-center">
            <p className="text-sm text-black/60">No concluded run to dissect yet.</p>
            <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-black/60">
              A read-out needs a deployed strategy with measured outcomes. A guest
              session can model but not execute.
            </p>
          </div>
        </Panel>
      )}

      {concluded.map((e) => (
        <AutopsyBody key={e.id} name={e.name} result={e.results as ExperimentResult}
                     totalExposed={totalExposed} />
      ))}
    </div>
  );
}

function AutopsyBody({
  name, result: r, totalExposed,
}: {
  name: string;
  result: ExperimentResult;
  totalExposed: number;
}) {
  const treatment = r.arms["treatment"];
  const exposure = treatment?.exposure_paise ?? totalExposed;
  const lost = Math.max(0, exposure - r.gross_recovery_paise);

  const stages = [
    { label: "Revenue exposed", value: exposure, tone: "loss" as const,
      note: "cohort exposure at time of decline" },
    { label: "Baseline recovery", value: r.natural_recovery_paise, tone: "muted" as const,
      note: "would have landed with no treatment" },
    { label: "Incremental lift", value: r.incremental_paise, tone: "yellow" as const,
      note: "attributable to the treatment" },
    { label: "Unrecovered", value: lost, tone: "loss" as const,
      note: "written off" },
  ];

  return (
    <div className="mt-8 space-y-6">
      <Panel title={name} hint={r.experiment_id}>
        <div className="p-6">
          <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
            {stages.map((s) => (
              <div key={s.label} className={
                s.tone === "yellow"
                  ? "surface-accent p-5"
                  : "surface p-5"
              }>
                <Stat label={s.label} value={lakhs(s.value)} sub={s.note} tone={s.tone} />
                <div className="mt-3 text-[11px] text-black/60">
                  {pct(s.value / Math.max(exposure, 1), 0)} of exposure
                </div>
              </div>
            ))}
          </div>

          <div className="mt-8">
            <Label>Attribution</Label>
            <div className="mt-3 flex h-14 w-full overflow-hidden rounded-full border border-black/25">
              <Segment width={r.natural_recovery_paise / exposure}
                       className="bg-black/[0.03] text-black/60" text="baseline" />
              <Segment width={r.incremental_paise / exposure}
                       className="bg-cyber text-cyber font-bold" text="incremental" />
              <Segment width={lost / exposure}
                       className="bg-signal-loss/20 text-signal-loss-ink" text="unrecovered" />
            </div>
            <p className="mt-4 max-w-4xl text-[12px] leading-relaxed text-black/60">
              A conventional dunning tool would book{" "}
              <span className="tnum font-semibold text-black">
                {lakhs(r.gross_recovery_paise)}
              </span>{" "}
              recovered. Only{" "}
              <span className="tnum font-semibold text-black">
                {lakhs(r.incremental_paise)}
              </span>{" "}
              of that is attributable to the treatment — the rest was landing regardless,
              and the holdout is how we know the difference.
            </p>
          </div>
        </div>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Performance" hint="Ranked by contribution.">
          <div className="space-y-4 p-6">
            <Line label="Recovery-rate lift"
                  value={`${(r.rate_lift * 100).toFixed(2)}%`}
                  note={`treated ${pct(treatment?.recovery_rate ?? 0)} vs holdout ${pct(r.arms["holdout"]?.recovery_rate ?? 0)}`} />
            <Line label="Net of treatment cost" value={lakhs(r.net_paise)}
                  note={`${rupees(r.cost_paise)} across ${count(treatment?.payments ?? 0)} treated payments`} />
            <Line label="Cost of measurement" value={lakhs(r.measurement_cost_paise)}
                  note="revenue the holdout was deliberately not worked" />
          </div>
        </Panel>

        <Panel title="Read-out" hint="How it scored itself.">
          <div className="p-6">
            {r.warnings.length > 0 ? (
              <ul className="space-y-3">
                {r.warnings.map((w) => (
                  <li key={w} className="flex gap-3 text-[12px] leading-relaxed text-black/60">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-cyber" />
                    {w}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[12px] text-black/60">
                Nothing flagged. The effect was significant, the arms balanced, and the
                design had the power to resolve it.
              </p>
            )}
            <div className="mt-5 flex flex-wrap gap-2">
              <Tag tone={r.significant ? "good" : "neutral"}>
                {r.significant ? "revenue lift significant" : "revenue lift not significant"}
              </Tag>
              {r.underpowered && <Tag tone="bad">underpowered</Tag>}
              {r.concentrated && <Tag tone="bad">effect concentrated</Tag>}
              {r.required_holdout > 0 && (
                <Tag tone="neutral">
                  would need a {count(r.required_holdout)}-payment holdout
                </Tag>
              )}
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Segment({ width, className, text }: { width: number; className: string; text: string }) {
  const w = Math.max(0, Math.min(1, width)) * 100;
  if (w < 0.5) return null;
  return (
    <div className={`flex items-center justify-center text-[11px] ${className}`}
         style={{ width: `${w}%` }}>
      {w > 8 ? text : ""}
    </div>
  );
}

function Line({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="border-b border-black/15 pb-4 last:border-0">
      <div className="flex items-baseline justify-between gap-4">
        <span className="text-[12px] text-black/60">{label}</span>
        <span className="tnum text-lg font-bold">{value}</span>
      </div>
      <p className="mt-1 text-[11px] text-black/60">{note}</p>
    </div>
  );
}
