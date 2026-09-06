import { useNavigate } from "react-router-dom";

import { Button, Label, Skeleton, Tag } from "./primitives";
import { lakhs } from "../lib/format";
import type { Attention, AttentionItem } from "../lib/types";

/**
 * The first thing on the dashboard, and the only part most people need.
 *
 * The page underneath this reports state - exposure, capacity, open incidents.
 * All of it is true and none of it says what to do, so an operator arriving at
 * 2pm has to derive their own next step from five tiles and a list. They
 * usually pick the biggest number, which is the wrong answer often enough to
 * be worth fixing.
 *
 * So this is the answer, computed rather than configured, and it is allowed to
 * be empty. An all-clear that says so in a sentence is more useful than a panel
 * that hides when there is nothing in it, because a hidden panel is
 * indistinguishable from a broken one.
 */
export function NeedsYou({
  state,
}: {
  state: { data: Attention | null; loading: boolean; error: Error | null };
}) {
  const navigate = useNavigate();

  if (state.loading) {
    return (
      <section className="card mb-8 p-6">
        <Label>What needs you</Label>
        <div className="mt-4">
          <Skeleton rows={2} />
        </div>
      </section>
    );
  }

  // A failed request must not masquerade as an all-clear. Saying nothing here
  // would read as "you are fine", which is the one wrong thing it could say.
  if (state.error || !state.data) return null;

  const a = state.data;

  if (a.all_clear) {
    return (
      <section className="card mb-8 flex flex-wrap items-center gap-x-4 gap-y-2 p-6">
        <Tag tone="good">All clear</Tag>
        <p className="text-[15px] font-medium">
          Nothing needs a decision right now.
        </p>
        <p className="text-[13px] text-black/60">
          Every open incident has a plan running, and no spend is waiting on a
          human.
        </p>
      </section>
    );
  }

  return (
    <section data-tour="needs-you" className="mb-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Label>What needs you</Label>
          <p className="mt-1 text-[13px] text-black/60">
            Ranked by what it costs to keep ignoring it.
          </p>
        </div>
        {a.money_at_stake_paise > 0 && (
          <p className="text-[13px] text-black/70">
            <span className="tnum font-display text-lg font-extrabold text-signal-loss-ink">
              {lakhs(a.money_at_stake_paise)}
            </span>{" "}
            bleeding with nothing running
          </p>
        )}
      </div>

      <div className="stagger mt-4 space-y-3">
        {a.items.map((item) => (
          <Row key={`${item.kind}:${item.action_path}`} item={item} go={navigate} />
        ))}
      </div>
    </section>
  );
}

const TONE: Record<AttentionItem["urgency"], { tag: "bad" | "yellow" | "neutral"; word: string }> = {
  act: { tag: "bad", word: "Act now" },
  review: { tag: "yellow", word: "Needs a decision" },
  watch: { tag: "neutral", word: "Worth knowing" },
};

function Row({ item, go }: { item: AttentionItem; go: (p: string) => void }) {
  const tone = TONE[item.urgency];
  const also = item.evidence.also ?? [];

  return (
    <div
      className={`card flex flex-col gap-4 p-5 sm:flex-row sm:items-start sm:gap-6 ${
        item.urgency === "act" ? "border-l-[6px] border-l-signal-loss" : ""
      }`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Tag tone={tone.tag}>{tone.word}</Tag>
          {item.money_paise > 0 && (
            <span className="tnum font-display text-sm font-extrabold">
              {lakhs(item.money_paise)}
            </span>
          )}
        </div>

        <p className="mt-2 text-[15px] font-semibold leading-snug">{item.headline}</p>
        <p className="mt-1 max-w-2xl text-[13px] leading-relaxed text-black/70">
          {item.detail}
        </p>

        {/* The other rules that fired on this same incident. Kept, because they
            are worth knowing - demoted, because they are not separate work. */}
        {also.length > 0 && (
          <ul className="mt-3 space-y-1">
            {also.map((note) => (
              <li key={note} className="flex gap-2 text-[12px] text-black/60">
                <span aria-hidden="true">·</span>
                <span>{note}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="shrink-0">
        <Button
          variant={item.urgency === "act" ? "dark" : "ghost"}
          onClick={() => go(item.action_path)}
          className="w-full justify-center sm:w-auto"
        >
          {item.action_label} &rarr;
        </Button>
      </div>
    </div>
  );
}
