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
  /**
   * Prefix that also counts as "on this step".
   *
   * /investigate resolves the worst incident and redirects to /incidents/:id,
   * so an exact path comparison would decide the reader had wandered off and
   * offer to take them back - to the redirect they just followed.
   */
  matches?: string;
  /**
   * CSS selector for the element this step is about.
   *
   * When it resolves, the rest of the screen dims and this stays lit. Nine
   * screens of dense numbers with a paragraph underneath asks the reader to
   * find what is being described; this points at it.
   */
  spotlight?: string;
}

export const STEPS: TourStep[] = [
  {
    path: "/command",
    title: "What you are looking at",
    spotlight: '[data-tour="overview-tiles"]',
    body: "When a payment fails, some of that money comes back on its own - the customer retries, the bank recovers, the card works an hour later. Recovery tools take credit for all of it. Reversa separates the money that was coming back anyway from the money that only arrives because you did something, and spends effort only on the second kind.",
    cta: "Show me",
  },
  {
    path: "/command",
    title: "Start with what is bleeding",
    spotlight: '[data-tour="overview-tiles"]',
    body: "This is today's payment stream, sliced by method and instrument, with the slices whose success rate broke against their own baseline. The number that matters is not revenue at risk - it is how much of it would come back with no help at all.",
    cta: "See the incidents",
  },
  {
    path: "/incidents",
    spotlight: '[data-tour="incident-table"]',
    title: "One outage, not seven alerts",
    body: "When a payment processor degrades, every UPI handle on it fails at once. Most tools would page you seven times. The detector rolls those into a single incident and keeps the handles as evidence of scope, because 'all seven' and 'only one' mean completely different things.",
    cta: "Open the worst one",
  },
  {
    path: "/investigate",
    spotlight: '[data-tour="agent-trace"]',
    matches: "/incidents/",
    title: "It decides what to ask next",
    body: "The agent is given a catalogue of questions it may ask about the incident and a budget of five. It asks one at a time and stops when the remaining questions cannot change the answer — here it stopped after three. What it declined to ask is on the record next to what it asked, and every citation is checked against the facts a question actually returned. On the unattributable incident it works the same way and refuses to name a cause.",
    cta: "See the counterfactual",
  },
  {
    path: "/futures",
    spotlight: '[data-tour="strategy-chart"]',
    title: "This is the whole product",
    body: "Before contacting a single customer, rewind the incident and try every strategy against the same cohort. Watch NO TREATMENT: most of the exposed revenue lands regardless. Every other strategy is worth only the lift it adds on top of that, which is why the most aggressive one is rarely the best one.",
    cta: "Run the analysis",
  },
  {
    path: "/portfolio",
    spotlight: '[data-tour="eligible-payments"]',
    title: "Why these customers and not the biggest ones",
    body: "You cannot contact everyone, so the question is where effort changes the outcome. A large payment that was 83% likely to recover anyway is worth less than a small one that was never coming back. Payment links are capped at 24, held under Razorpay's test-mode ceiling of 30 so a demo can never wedge the account.",
    cta: "Look at the decisions",
  },
  {
    path: "/experiments",
    spotlight: '[data-tour="lift-result"]',
    title: "Measured, not claimed",
    body: "A randomly chosen slice of the plan was deliberately left untreated. Whatever that group recovers is what the treated group would have recovered anyway, so treatment minus holdout - with a confidence interval - is the only number here that can honestly be called incremental.",
    cta: "See the result",
  },
  {
    path: "/autopsy",
    spotlight: '[data-tour="autopsy-split"]',
    title: "Where the money actually went",
    body: "The exposure split three ways: what came back on its own, what the treatment caused, and what was never recovered at all. That last number is the biggest one on the page and it stays there - just over half of this incident's exposure is simply gone, and a tool that hides that is not worth trusting on the rest.",
    cta: "See the rules it works under",
  },
  {
    path: "/policies",
    spotlight: '[data-tour="policy-editor"]',
    title: "Rules in plain English",
    body: "Write a constraint the way you would say it - no links over five thousand rupees, nothing before nine in the morning - and it compiles into gates the optimiser has to obey. Merchant rules can only ever tighten what the system may do, never widen it, so a typo cannot grant a permission nobody intended.",
    cta: "Verify the trail",
  },
  {
    path: "/audit",
    spotlight: '[data-tour="audit-chain"]',
    title: "Every decision, hash-chained",
    body: "The system contacts customers without a human approving each one, so the trail commits to itself: each entry carries the fingerprint of the one before it. Edit any row and verification breaks at that row and every row after it.",
    cta: "Verify the chain",
  },
  {
    path: "/evaluation",
    spotlight: '[data-tour="detection-score"]',
    title: "Scored against a hidden answer key",
    body: "The simulator knows what would really have happened to every payment, and Reversa is never allowed to read it - a test fails the build if any engine tries. This page is the two compared, including the incident the detector missed.",
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
