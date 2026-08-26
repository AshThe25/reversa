import { useState } from "react";

import { Button, ErrorNote, Label, Panel, Skeleton, Tag } from "../components/primitives";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { dateTimeIST, titleise } from "../lib/format";
import type { AuditEntry } from "../lib/types";

const ACTOR_TONE: Record<string, "yellow" | "info" | "good" | "neutral"> = {
  sentinel: "info",
  cohort_engine: "neutral",
  simulation_engine: "neutral",
  executor: "yellow",
  experiment_engine: "good",
};

export function Audit() {
  const events = useAsync(() => api.audit(150), []);
  const chain = useAsync(() => api.verifyChain(), []);
  const [open, setOpen] = useState<number | null>(null);

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Tamper-evident record</Label>
          <h1 className="mt-2 text-4xl font-bold tracking-tight">Audit Ledger</h1>
          <p className="mt-3 max-w-3xl text-sm leading-relaxed text-white/45">
            Reversa moves money without a human in the loop, so "we logged it" is not
            enough — logs are editable. Each entry commits to the hash of the one before
            it, over a canonical JSON serialisation. Alter any row and verification breaks
            at that row and every row after it, and you do not need this database to check.
          </p>
        </div>
        <Button variant="ghost" onClick={() => { events.reload(); chain.reload(); }}>
          Re-verify
        </Button>
      </div>

      {chain.data && (
        <div
          className={`mt-8 rounded-[24px] border p-6 ${
            chain.data.valid
              ? "border-signal-calm/25 bg-signal-calm/[0.05]"
              : "border-signal-loss/30 bg-signal-loss/[0.06]"
          }`}
        >
          <div className="flex flex-wrap items-center gap-4">
            <span
              className={`grid h-10 w-10 place-items-center rounded-full text-lg ${
                chain.data.valid ? "bg-signal-calm/20 text-signal-calm" : "bg-signal-loss/20 text-signal-loss"
              }`}
            >
              {chain.data.valid ? "✓" : "✕"}
            </span>
            <div>
              <p className="text-sm font-semibold">
                {chain.data.valid
                  ? `Chain verified across ${chain.data.entries_checked} entries`
                  : `Chain broken at entry ${chain.data.broken_at_seq}`}
              </p>
              <p className="mt-0.5 font-mono text-[11px] text-white/35">
                head {chain.data.head_hash.slice(0, 32)}…
              </p>
            </div>
            {chain.data.reason && (
              <p className="text-[12px] text-signal-loss">{chain.data.reason}</p>
            )}
          </div>
        </div>
      )}

      {events.error && (
        <div className="mt-6">
          <ErrorNote message={events.error.message} requestId={events.error.requestId} />
        </div>
      )}

      <Panel className="mt-6" title="Events" hint="Newest first. Click any row for the full payload that was hashed.">
        {events.loading && <Skeleton rows={8} />}
        {events.data && (
          <div className="divide-y divide-white/[0.04]">
            {events.data.map((e) => (
              <EventRow key={e.id} event={e} open={open === e.seq} onToggle={() => setOpen(open === e.seq ? null : e.seq)} />
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

function EventRow({ event: e, open, onToggle }: { event: AuditEntry; open: boolean; onToggle: () => void }) {
  return (
    <div>
      <button onClick={onToggle} className="row-hover flex w-full items-center gap-4 px-6 py-3.5 text-left">
        <span className="tnum w-12 shrink-0 font-mono text-[11px] text-white/25">#{e.seq}</span>
        <span className="tnum w-32 shrink-0 text-[11px] text-white/40">{dateTimeIST(e.at)}</span>
        <span className="w-40 shrink-0">
          <Tag tone={ACTOR_TONE[e.actor] ?? "neutral"}>{e.actor}</Tag>
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{titleise(e.event_type)}</span>
        <span className="hidden shrink-0 font-mono text-[10px] text-white/25 lg:block">
          {e.prev_hash}… → {e.entry_hash}…
        </span>
      </button>
      {open && (
        <div className="border-t border-white/[0.04] bg-white/[0.015] px-6 py-4">
          <Label>Hashed payload</Label>
          <pre className="mt-3 overflow-x-auto rounded-[16px] bg-onyx/60 p-4 font-mono text-[11px] leading-relaxed text-white/60">
            {JSON.stringify(e.payload, null, 2)}
          </pre>
          <div className="mt-3 grid gap-2 font-mono text-[10px] text-white/30 sm:grid-cols-2">
            <div>subject: {e.subject_type}/{e.subject_id}</div>
            <div>entry: {e.id}</div>
          </div>
        </div>
      )}
    </div>
  );
}
