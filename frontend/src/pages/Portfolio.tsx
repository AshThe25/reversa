import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  Bar, Button, ErrorNote, Label, Panel, Skeleton, Stat, Tag,
} from "../components/primitives";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { count, lakhs, pct, rupees, titleise } from "../lib/format";
import type { CandidateRow } from "../lib/types";

/**
 * The decision view.
 *
 * An operator has to be able to answer three questions about any row: why this
 * customer, why this action, and why not the others. So every candidate shows
 * its estimated natural recovery, the full scored option set including the
 * rejected ones, and which options compliance removed before scoring began.
 */
export function Portfolio() {
  const [params, setParams] = useSearchParams();
  const incidents = useAsync(() => api.incidents(), []);
  const selected = params.get("incident");
  const [open, setOpen] = useState<string | null>(null);

  // Default to an incident whose scope is attributable. A diffuse cluster has
  // no supportable root cause, so a ranked list of interventions for it would be
  // a confident-looking answer to a question the evidence cannot settle.
  useEffect(() => {
    if (!selected && incidents.data?.length) {
      const attributable = incidents.data.filter((i) => !i.ambiguous);
      const pool = attributable.length ? attributable : incidents.data;
      const worst = pool.reduce((a, b) =>
        a.revenue_exposed_paise >= b.revenue_exposed_paise ? a : b,
      );
      setParams({ incident: worst.id }, { replace: true });
    }
  }, [incidents.data, selected, setParams]);

  const cohort = useAsync(
    () => (selected ? api.cohort(selected) : Promise.resolve(null)),
    [selected],
  );
  const co = cohort.data;

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Constrained allocation</Label>
          <h1 className="mt-2 text-4xl font-bold tracking-tight">Recovery Portfolio</h1>
          <p className="mt-3 max-w-3xl text-sm leading-relaxed text-black/60">
            Capacity is finite and the expensive channels are the scarce ones. Eligible
            payments ranked by expected incremental value — not by ticket size.
          </p>
        </div>
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
      </div>

      {cohort.error && (
        <div className="mt-6">
          <ErrorNote message={cohort.error.message} requestId={cohort.error.requestId} />
        </div>
      )}

      {co && (
        <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div className="panel p-6">
            <Stat label="Eligible" value={count(co.member_count)} sub={`${count(co.in_window_payments)} in window`} />
          </div>
          <div className="panel p-6">
            <Stat label="Exposure" value={lakhs(co.revenue_exposed_paise)} tone="loss" />
          </div>
          <div className="panel p-6">
            <Stat
              label="Attribution weight"
              value={pct(co.attribution_weight, 0)}
              sub="share of in-window declines the incident caused"
              tone="muted"
              hint="The baseline failure rate keeps running underneath an incident. Counting every in-window failure as incident damage overstates the headline."
            />
          </div>
          <div className="surface-accent p-6">
            <Stat label="Addressable" value={lakhs(co.addressable_paise)} tone="yellow" />
          </div>
        </div>
      )}

      <Panel
        className="mt-6"
        title="Eligible payments"
        hint="Sorted by exposure. Expand a row for the full scored option set, including the actions that were rejected and the ones compliance removed."
      >
        {cohort.loading && <Skeleton rows={6} />}
        {co && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1000px] text-left">
              <thead>
                <tr className="border-b border-black/15">
                  {["Payment", "Amount", "Decline class", "Baseline P(recover)", "Best treatment", "Expected lift", "Confidence", ""].map((h) => (
                    <th key={h} className="label px-5 py-3 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-black/10">
                {co.candidates.map((c) => (
                  <CandidateRowView
                    key={c.payment_id}
                    row={c}
                    open={open === c.payment_id}
                    onToggle={() => setOpen(open === c.payment_id ? null : c.payment_id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {co && co.exception_sample.length > 0 && (
        <Panel
          className="mt-6"
          title="Suppressed by a compliance gate"
          hint="Named, not dropped. Each is a payment we could have worked and chose not to."
        >
          {/* The payment id is one unbreakable token. Left to itself it set the
              row's min-content width and pushed the whole page past a narrow
              phone, so it is the element allowed to truncate. */}
          <div className="divide-y divide-black/10">
            {co.exception_sample.slice(0, 10).map((e) => (
              <div
                key={e.payment_id}
                className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 sm:flex-nowrap"
              >
                <Tag tone="bad">{titleise(e.reason)}</Tag>
                <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-black/60">
                  {e.payment_id}
                </span>
                <span className="tnum shrink-0 text-sm text-black/60 sm:ml-auto">
                  {rupees(e.amount_paise)}
                </span>
              </div>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}

function CandidateRowView({
  row, open, onToggle,
}: {
  row: CandidateRow;
  open: boolean;
  onToggle: () => void;
}) {
  const ranked = Object.entries(row.uplift).sort((a, b) => b[1].delta - a[1].delta);
  const eligibleRanked = ranked.filter(([a]) => row.eligible.includes(a));
  const bestEntry = eligibleRanked[0];
  const maxEv = Math.max(...ranked.map(([, u]) => Math.abs(u.ev_paise)), 1);

  return (
    <>
      <tr className={`row-hover ${row.would_recover_anyway ? "opacity-60" : ""}`}>
        <td className="px-5 py-4 font-mono text-[11px] text-black/60">{row.payment_id}</td>
        <td className="tnum px-5 py-4 text-sm font-semibold">{rupees(row.amount_paise)}</td>
        <td className="px-5 py-4">
          <span className="font-mono text-[11px] text-black/60">{row.failure_class}</span>
        </td>
        <td className="px-5 py-4">
          <div className="flex items-center gap-2">
            <span className={`tnum text-sm ${row.would_recover_anyway ? "text-black/60" : ""}`}>
              {pct(row.p_natural)}
            </span>
            {row.would_recover_anyway && <Tag tone="neutral">likely anyway</Tag>}
          </div>
        </td>
        <td className="px-5 py-4">
          {bestEntry ? (
            <span className="text-sm font-medium">{titleise(bestEntry[0])}</span>
          ) : (
            <span className="text-xs text-black/60">no legal action</span>
          )}
        </td>
        <td className="tnum px-5 py-4 text-sm font-bold text-black">
          {bestEntry ? rupees(bestEntry[1].ev_paise) : "—"}
        </td>
        <td className="px-5 py-4">
          <div className="w-16">
            <Bar value={row.confidence} max={1} tone={row.confidence > 0.6 ? "yellow" : "muted"} />
          </div>
        </td>
        <td className="px-5 py-4 text-right">
          <Button variant="ghost" onClick={onToggle}>
            {open ? "Hide" : "Why?"}
          </Button>
        </td>
      </tr>

      {open && (
        <tr>
          <td colSpan={8} className="bg-black/[0.03] px-5 py-6">
            <div className="grid gap-8 lg:grid-cols-[1.3fr_1fr]">
              <div>
                <Label>Every treatment scored, including the rejected</Label>
                <div className="mt-4 space-y-2.5">
                  {ranked.map(([action, u]) => {
                    const eligible = row.eligible.includes(action);
                    const isBest = bestEntry?.[0] === action;
                    return (
                      <div key={action} className="flex items-center gap-3">
                        <span
                          className={`w-36 shrink-0 text-[12px] ${
                            isBest ? "font-semibold text-black" : eligible ? "text-black/70" : "text-black/60 line-through"
                          }`}
                        >
                          {titleise(action)}
                        </span>
                        <div className="h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-black/[0.03]">
                          <div
                            className={`h-full rounded-full ${
                              !eligible ? "bg-black/[0.03]" : isBest ? "bg-cyber" : u.delta > 0 ? "bg-black/[0.03]" : "bg-signal-loss/50"
                            }`}
                            style={{ width: `${(Math.abs(u.ev_paise) / maxEv) * 100}%` }}
                          />
                        </div>
                        <span className="tnum w-24 shrink-0 text-right text-[11px] text-black/60">
                          {rupees(u.ev_paise)}
                        </span>
                        {!u.credible && (
                          <span className="shrink-0 text-[10px] uppercase tracking-label text-black/60">
                            not credible
                          </span>
                        )}
                        {!eligible && (
                          <span className="shrink-0 text-[10px] uppercase tracking-label text-signal-loss-ink/70">
                            gated
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="space-y-4">
                <div>
                  <Label>Why this payment</Label>
                  <p className="mt-2 text-[12px] leading-relaxed text-black/60">
                    Estimated {pct(row.p_natural)} chance of recovering with no treatment at
                    all, leaving {pct(1 - row.p_natural)} of headroom. A treatment can only
                    ever compete for that remainder — which is why a large payment already
                    likely to land is worth less than a small one that is not.
                  </p>
                </div>
                <div>
                  <Label>Why not the others</Label>
                  <p className="mt-2 text-[12px] leading-relaxed text-black/60">
                    Struck-through treatments were removed by a compliance gate before scoring.
                    Those marked <em className="not-italic text-black/70">not credible</em>{" "}
                    have uplift estimates whose interval spans zero — the optimiser will not
                    spend on an effect it cannot distinguish from nothing.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2 pt-1">
                  <Tag tone="neutral">{row.method.toUpperCase()}</Tag>
                  <Tag tone="neutral">{row.eligible.length} permitted treatments</Tag>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
