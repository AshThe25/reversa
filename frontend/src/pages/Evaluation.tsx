import { Bar, ErrorNote, Label, Panel, Skeleton, Stat, Tag } from "../components/primitives";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { count, lakhs, pct, signedPct } from "../lib/format";

/**
 * Reversa graded against the simulator's hidden answer key.
 *
 * Nothing here is self-reported. The detector's recall is measured against the
 * incidents the world actually injected, the natural-recovery estimate is scored
 * on the holdout where the realised outcome IS the natural outcome, and the
 * headline incremental figure is compared against the exact value computed from
 * potential outcomes.
 *
 * The failures stay on the page. A page that only showed what the system got
 * right would be marketing.
 */
export function Evaluation() {
  const { data, loading, error } = useAsync(() => api.evaluation(), []);

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      <Label>Graded against ground truth</Label>
      <h1 className="mt-2 text-4xl font-bold tracking-tight">Evaluation</h1>
      <p className="mt-3 max-w-3xl text-sm leading-relaxed text-black/60">
        The simulator holds every payment's latent resolve and both potential
        outcomes. Reversa never reads them — an import-graph test fails the build
        if any engine tries. These are the system's outputs compared against that
        answer key, including where it was wrong.
      </p>

      {error && (
        <div className="mt-6">
          <ErrorNote message={error.message} requestId={error.requestId} />
        </div>
      )}
      {loading && <Skeleton rows={8} />}

      {data && (
        <>
          <Panel className="mt-8" title="Incident detection" hint="Against the incidents the world actually injected.">
            <div className="grid gap-6 p-6 sm:grid-cols-2 xl:grid-cols-5">
              <Stat label="Recall" value={pct(data.detection.recall, 0)}
                    sub={`${data.detection.matched} of ${data.detection.true_incidents} found`}
                    tone={data.detection.recall >= 1 ? "yellow" : "default"} />
              <Stat label="Precision" value={pct(data.detection.precision, 0)}
                    sub={`${data.detection.false_alarms} false alarms`} />
              <Stat label="Median latency"
                    value={data.detection.median_latency_min !== null
                      ? `${data.detection.median_latency_min}m` : "—"}
                    sub="from true onset to alert" />
              <Stat label="Fastest detection"
                    value={data.detection.latencies_min.length
                      ? `${Math.min(...data.detection.latencies_min)}m` : "—"}
                    sub="the high-volume slice" tone="yellow" />
              <Stat label="Missed"
                    value={`${data.detection.missed.length}`}
                    sub={data.detection.missed.join(", ") || "none"}
                    tone={data.detection.missed.length ? "loss" : "muted"} />
            </div>
            <div className="border-t border-black/15 px-6 py-4">
              <p className="text-[12px] leading-relaxed text-black/60">
                Per-incident latency:{" "}
                {data.detection.latencies_min.map((l) => `${l}m`).join(" · ")}. Thin
                slices are detected later than high-volume ones, which is honest
                rather than tunable — a bank holding 2% of traffic simply takes
                longer to accumulate evidence.
              </p>
            </div>
          </Panel>

          {data.experiments.map((e) => (
            <div key={e.experiment_id} className="mt-6 space-y-6">
              {/* ------------------------------------------- measurement */}
              <Panel
                title="Did the measurement work?"
                hint="The estimate comes from a randomised holdout. The truth is computed exactly from potential outcomes. This compares them."
              >
                <div className="grid gap-8 p-6 lg:grid-cols-[1.2fr_1fr]">
                  <div>
                    <div className="grid gap-6 sm:grid-cols-2">
                      <Stat label="Measured from holdout"
                            value={lakhs(e.measurement.estimated_paise)}
                            sub={`90% CI [${lakhs(e.measurement.estimated_lo_paise)}, ${lakhs(e.measurement.estimated_hi_paise)}]`} />
                      <Stat label="True incremental"
                            value={lakhs(e.measurement.true_paise)}
                            sub="exact, from the answer key" tone="yellow" />
                    </div>

                    <div className={`mt-6 rounded-[20px] border p-5 ${
                      e.measurement.interval_contains_truth
                        ? "border-black bg-signal-calm/10"
                        : "border-black bg-signal-loss/10"
                    }`}>
                      <div className="flex items-center gap-3">
                        <span className={`grid h-8 w-8 place-items-center rounded-full ${
                          e.measurement.interval_contains_truth
                            ? "bg-signal-calm/20 text-black"
                            : "bg-signal-loss/20 text-signal-loss-ink"
                        }`}>
                          {e.measurement.interval_contains_truth ? "✓" : "✕"}
                        </span>
                        <p className="text-sm font-semibold">
                          {e.measurement.interval_contains_truth
                            ? "The interval contains the truth"
                            : "The interval missed the truth"}
                        </p>
                      </div>
                      <p className="mt-3 text-[12px] leading-relaxed text-black/60">
                        {e.measurement.interval_contains_truth
                          ? "The experiment design recovers the real effect. The point estimate is noisy — that is what the interval is for — but the method is sound, which is the prerequisite for every other number in this product meaning anything."
                          : "The holdout estimate did not bracket the true effect. Every headline figure downstream should be treated as unreliable until this is understood."}
                      </p>
                      {e.measurement.relative_error !== null && (
                        <p className="tnum mt-2 text-[12px] text-black/60">
                          Point estimate error {signedPct(e.measurement.relative_error, 0)} ·{" "}
                          {count(e.measurement.treated_payments)} treated payments
                        </p>
                      )}
                    </div>
                  </div>

                  {e.calibration && (
                    <div>
                      <Label>Natural-recovery calibration</Label>
                      <p className="mt-2 text-[11px] leading-relaxed text-black/60">
                        Scored on the holdout only — nothing was done to them, so their
                        realised outcome is the natural outcome by definition.
                      </p>
                      <div className="mt-4 grid grid-cols-3 gap-4">
                        <Stat label="Brier" value={e.calibration.brier.toFixed(3)} />
                        <Stat label="Cal. error" value={e.calibration.expected_calibration_error.toFixed(3)} />
                        <Stat label="Bias" value={signedPct(e.calibration.bias, 1)}
                              tone={Math.abs(e.calibration.bias) < 0.05 ? "default" : "loss"} />
                      </div>
                      <div className="mt-5 space-y-2">
                        {e.calibration.bins.map((b) => (
                          <div key={b.bin_lo} className="flex items-center gap-3">
                            <span className="tnum w-16 shrink-0 text-[10px] text-black/60">
                              {b.bin_lo.toFixed(1)}–{b.bin_hi.toFixed(1)}
                            </span>
                            <div className="flex-1">
                              <Bar value={b.actual} max={1} tone="yellow" />
                              <div className="mt-1">
                                <Bar value={b.predicted} max={1} tone="muted" />
                              </div>
                            </div>
                            <span className="tnum w-10 shrink-0 text-right text-[10px] text-black/60">
                              n={b.n}
                            </span>
                          </div>
                        ))}
                      </div>
                      <p className="mt-3 text-[10px] text-black/60">
                        yellow = actual · grey = predicted
                      </p>
                    </div>
                  )}
                </div>
              </Panel>

              {/* --------------------------------------------- decisions */}
              <Panel title="Were the decisions good?" hint={e.decisions.note}>
                <div className="grid gap-6 p-6 sm:grid-cols-2 xl:grid-cols-5">
                  <Stat label="Actions placed" value={count(e.decisions.decisions)} />
                  <Stat label="Genuinely effective"
                        value={pct(e.decisions.effective_rate, 0)}
                        sub="true uplift above zero"
                        tone={e.decisions.effective_rate > 0.9 ? "yellow" : "default"} />
                  <Stat label="Picked the best available"
                        value={pct(e.decisions.top1_accuracy, 0)}
                        sub="among actions compliance allowed" />
                  <Stat label="Actually harmful"
                        value={count(e.decisions.chose_harmful)}
                        tone={e.decisions.chose_harmful ? "loss" : "muted"}
                        sub="true uplift below zero" />
                  <Stat label="System flagged as waste"
                        value={count(e.decisions.flagged_wasteful)}
                        tone="muted"
                        sub="high estimated natural recovery" />
                </div>
                <div className="border-t border-black/15 px-6 py-4">
                  <p className="max-w-4xl text-[12px] leading-relaxed text-black/60">
                    Mean regret is {e.decisions.mean_regret_uplift_points.toFixed(4)} uplift
                    points — the average gap between the action taken and the best one that
                    was available. Top-1 accuracy is low by design of the data, not of the
                    optimiser: distinguishing the best action from the second-best often
                    means resolving a difference of two or three percentage points, which
                    ordinary merchant history cannot support. That is the argument for the
                    exploration arm, and it is why the genuinely-harmful count matters more
                    than the top-1 figure.
                  </p>
                </div>
              </Panel>

              {/* ------------------------------------------------ cohort */}
              <Panel title="Was the cohort right?" hint={e.cohort.note}>
                <div className="grid gap-6 p-6 sm:grid-cols-3">
                  <Stat label="Cohort size" value={count(e.cohort.members)} />
                  <Stat label="Truly incident-caused"
                        value={count(e.cohort.true_incident_members ?? 0)} />
                  <Stat label="Cohort precision"
                        value={e.cohort.precision !== null ? pct(e.cohort.precision, 0) : "—"}
                        tone="yellow" />
                </div>
              </Panel>
            </div>
          ))}

          {data.experiments.length === 0 && (
            <Panel className="mt-6">
              <div className="px-6 py-14 text-center">
                <p className="text-sm text-black/60">No experiment has run yet.</p>
                <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-black/60">
                  Detection is scored above regardless. The measurement and decision
                  scores need a deployed strategy, which a demo session cannot create.
                </p>
              </div>
            </Panel>
          )}

          <div className="mt-6 surface p-6">
            <Label>Method</Label>
            <p className="mt-2 max-w-4xl text-[12px] leading-relaxed text-black/60">
              {data.method_note}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Tag tone="neutral">computed in {Math.round(data.compute_ms)}ms</Tag>
              <Tag tone="neutral">estimator trained on history only</Tag>
              <Tag tone="neutral">live day is a temporal holdout</Tag>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
