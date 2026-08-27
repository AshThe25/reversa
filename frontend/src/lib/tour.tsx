/**
 * The guided walkthrough.
 *
 * A judge opens this cold and has about ninety seconds of patience. The tour is
 * not decoration - it is the difference between "a dashboard with a lot on it"
 * and understanding, in order, that most of the money comes back on its own,
 * that the aggressive strategy is not the best one, and that the headline
 * number is measured rather than claimed.
 *
 * Deliberately non-blocking: it never traps focus, never covers content, and
 * every step can be skipped. A walkthrough you cannot escape is worse than none.
 */

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

export interface TourStep {
  path: string;
  title: string;
  body: string;
  cta: string;
}

export const STEPS: TourStep[] = [
  {
    path: "/command",
    title: "Start with what's bleeding",
    body: "Reversa watched today's payment stream slice by slice and flagged where success rates broke. The number that matters is not revenue at risk - it is how much of it would come back with no help at all.",
    cta: "See the incidents",
  },
  {
    path: "/incidents",
    title: "One outage, not seven alerts",
    body: "A PSP degradation breaks every UPI handle at once. The detector rolls those into a single incident and keeps the handles as scope evidence, because 'all seven' and 'only one' mean completely different things.",
    cta: "Open the worst one",
  },
  {
    path: "/futures",
    title: "This is the whole product",
    body: "Rewind the incident and evaluate every treatment strategy against the same cohort. Watch NO TREATMENT - most of the exposed revenue lands regardless. Every other strategy is only worth the lift it adds over that.",
    cta: "Run the analysis",
  },
  {
    path: "/portfolio",
    title: "Why these customers",
    body: "Capacity is finite: 30 payment links, because that is Razorpay test mode's ceiling. The optimiser spends them where a treatment changes the outcome, not where the ticket is largest.",
    cta: "Look at the decisions",
  },
  {
    path: "/experiments",
    title: "Measured, not claimed",
    body: "A random slice of the plan was deliberately withheld. Treatment minus holdout, with a confidence interval, is the only number here that can honestly be called incremental.",
    cta: "See the result",
  },
  {
    path: "/audit",
    title: "Every decision, hash-chained",
    body: "The agent moved money without a human in the loop, so the trail commits to itself. Edit any row and verification breaks at that row and everything after it.",
    cta: "Verify the chain",
  },
  {
    path: "/evaluation",
    title: "Scored against a hidden answer key",
    body: "The simulator knows what would really have happened to every payment. Reversa never sees it. This page is the two compared - including where the system was wrong.",
    cta: "Finish",
  },
];

interface TourValue {
  active: boolean;
  index: number;
  step: TourStep | null;
  start: () => void;
  next: () => void;
  stop: () => void;
  goTo: (i: number) => void;
}

const Ctx = createContext<TourValue | null>(null);

export function TourProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState(false);
  const [index, setIndex] = useState(0);

  const start = useCallback(() => {
    setIndex(0);
    setActive(true);
  }, []);
  const stop = useCallback(() => setActive(false), []);
  const next = useCallback(() => {
    setIndex((i) => {
      if (i + 1 >= STEPS.length) {
        setActive(false);
        return i;
      }
      return i + 1;
    });
  }, []);
  const goTo = useCallback((i: number) => setIndex(Math.max(0, Math.min(i, STEPS.length - 1))), []);

  const value = useMemo<TourValue>(
    () => ({ active, index, step: active ? STEPS[index] ?? null : null, start, next, stop, goTo }),
    [active, index, start, next, stop, goTo],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTour(): TourValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTour outside TourProvider");
  return v;
}
