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
          <p className="mt-3 max-w-3xl text-sm leading-relaxed text-black/45">
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
              ? "border-black bg-signal-calm/10"
              : "border-black bg-signal-loss/10"
          }`}
        >
          <div className="flex flex-wrap items-center gap-4">
            <span
              className={`grid h-10 w-10 place-items-center rounded-full text-lg ${
                chain.data.valid ? "bg-signal-calm/20 text-black" : "bg-signal-loss/20 text-signal-loss"
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
              <p className="mt-0.5 font-mono text-[11px] text-black/35">
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
          <div className="divide-y divide-black/10">
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
      {/* The fixed columns add up to more than a phone is wide, so below `sm`
          the row wraps: sequence, time and actor on the first line, the event
          name on its own line under them. Widths come back at `sm`, where the
          five columns line up again. */}
      <button
        onClick={onToggle}
        className="row-hover flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3.5
                   text-left sm:flex-nowrap sm:gap-4 sm:px-6"
      >
        <span className="tnum w-12 shrink-0 font-mono text-[11px] text-black/25">#{e.seq}</span>
        <span className="tnum shrink-0 text-[11px] text-black/40 sm:w-32">{dateTimeIST(e.at)}</span>
        <span className="shrink-0 sm:w-40">
          <Tag tone={ACTOR_TONE[e.actor] ?? "neutral"}>{e.actor}</Tag>
        </span>
        <span className="min-w-0 basis-full truncate text-sm font-medium sm:flex-1 sm:basis-auto">
          {titleise(e.event_type)}
        </span>
        <span className="hidden shrink-0 font-mono text-[10px] text-black/25 lg:block">
          {e.prev_hash}… → {e.entry_hash}…
        </span>
      </button>
      {open && (
        <div className="border-t border-black/15 bg-black/[0.03] px-6 py-4">
          <Label>Hashed payload</Label>
          <pre className="mt-3 overflow-x-auto rounded-[16px] bg-paper p-4 font-mono text-[11px] leading-relaxed text-black/60">
            {JSON.stringify(e.payload, null, 2)}
          </pre>
          <div className="mt-3 grid gap-2 font-mono text-[10px] text-black/30 sm:grid-cols-2">
            <div>subject: {e.subject_type}/{e.subject_id}</div>
            <div>entry: {e.id}</div>
          </div>
        </div>
      )}
    </div>
  );
}
