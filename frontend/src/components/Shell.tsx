import { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { currentRole } from "../lib/api";
import { STEPS, useTour } from "../lib/tour";
import { Button, Tag } from "./primitives";

const NAV = [
  { to: "/command", label: "Command" },
  { to: "/incidents", label: "Incidents" },
  { to: "/futures", label: "Futures" },
  { to: "/portfolio", label: "Portfolio" },
  { to: "/experiments", label: "Tests" },
  { to: "/autopsy", label: "Autopsy" },
  { to: "/policies", label: "Policy" },
  { to: "/audit", label: "Audit" },
  { to: "/evaluation", label: "Eval" },
];

/**
 * The app shell.
 *
 * Fixed yellow header on a hard black rule, dot field behind it. The nav is a
 * segmented track with a bordered yellow thumb — the active item is a physical
 * object sitting on the track, not a highlighted link.
 */
export function Shell({
  children,
  onSignOut,
}: {
  children: React.ReactNode;
  onSignOut?: () => void;
}) {
  const location = useLocation();
  const role = currentRole();

  return (
    <div className="min-h-full bg-paper">
      <header className="dot-field sticky top-0 z-50 border-b-2 border-black bg-cyber">
        <div className="relative z-10 mx-auto flex max-w-[1600px] flex-wrap items-center gap-4 px-6 py-3">
          <NavLink to="/" className="flex shrink-0 items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center border-2 border-black bg-black font-display text-base font-extrabold text-cyber">
              R
            </span>
            <span className="font-display text-xl font-extrabold uppercase tracking-tighter">
              Reversa
            </span>
          </NavLink>

          {/* Until `lg` the nav takes its own full-width row under the wordmark
              rather than competing with it for space: as an inline flex child it
              shrank to about fifty pixels on a phone while still holding ten
              links, which is a scroll track nobody can aim at. */}
          <nav
            className="segment-track order-last min-w-0 basis-full overflow-x-auto
                       lg:order-none lg:basis-auto lg:flex-1"
          >
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `segment whitespace-nowrap ${isActive ? "segment-on" : ""}`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          {role && (
            <div className="flex shrink-0 items-center gap-2">
              {/* The walkthrough was reachable only from the landing page, so
                  anyone who skipped it once could not find it again. It is the
                  difference between nine screens of dense numbers and knowing
                  what they are for, so it stays one click away. */}
              <GuideButton />
              <Tag tone={role === "operator" ? "info" : "neutral"}>
                {role === "operator" ? "Operator" : "Guest"}
              </Tag>
              {onSignOut && (
                <button
                  onClick={onSignOut}
                  title="End this session"
                  className="link-quiet"
                >
                  Sign out
                </button>
              )}
            </div>
          )}
        </div>
      </header>

      <main key={location.pathname} className="animate-rise">
        {children}
      </main>

      <TourBar />

      <footer className="border-t-2 border-black bg-charcoal px-6 py-10 text-white">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-4">
          <p className="font-display text-[11px] font-extrabold uppercase tracking-label">
            Reversa · Counterfactual revenue recovery
          </p>
          <p className="text-[11px] text-white/70">
            Built by <span className="font-semibold text-white">Aishwarya Tripathi</span> for the
            Razorpay AI Buildathon 2026
          </p>
          <p className="text-[11px] text-white/70">
            Every figure on this site is computed by a backend engine. None are authored.
          </p>
        </div>
      </footer>
    </div>
  );
}

/**
 * The walkthrough bar. Docked, never modal, escapable at every step — a tour
 * you cannot leave is worse than no tour.
 */
/**
 * Dims the screen and leaves one element lit.
 *
 * A paragraph describing a number on a screen full of numbers asks the reader
 * to go find it. This points. The dimming is one element with an enormous
 * spread shadow rather than four panels around a hole - fewer things to keep in
 * sync when the target moves, and it cannot leave a seam.
 *
 * It never blocks the page. Pointer events pass through, so the reader can
 * still click the thing being explained, which is usually what they want to do
 * next. A tour that traps you is worse than no tour.
 */
function Spotlight({ selector }: { selector: string }) {
  const [box, setBox] = useState<DOMRect | null>(null);

  useEffect(() => {
    let frame = 0;
    const measure = () => {
      const el = document.querySelector(selector);
      setBox(el ? el.getBoundingClientRect() : null);
      frame = requestAnimationFrame(measure);
    };
    // Tracked per frame rather than on scroll and resize: the target moves for
    // reasons neither event reports - a chart finishing its layout, an async
    // panel arriving - and a highlight sitting where the element used to be is
    // worse than none.
    frame = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(frame);
  }, [selector]);

  if (!box || box.width === 0) return null;

  const pad = 10;
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed z-40 rounded-neo border-2 border-black
                 transition-all duration-300"
      style={{
        top: box.top - pad,
        left: box.left - pad,
        width: box.width + pad * 2,
        height: box.height + pad * 2,
        boxShadow: "0 0 0 9999px rgba(0,0,0,0.55)",
      }}
    />
  );
}

function GuideButton() {
  const tour = useTour();
  const navigate = useNavigate();
  if (tour.active) return null;
  return (
    <button
      onClick={() => {
        tour.start();
        const first = STEPS[0];
        if (first) navigate(first.path);
      }}
      title="Nine steps. Leave at any point."
      className="btn btn-sm bg-white text-black"
    >
      Guide me
    </button>
  );
}

function TourBar() {
  const tour = useTour();
  const navigate = useNavigate();
  const location = useLocation();

  if (!tour.active || !tour.step) return null;
  const step = tour.step;
  const onStepPage =
    location.pathname === step.path ||
    (step.matches !== undefined && location.pathname.startsWith(step.matches));
  const last = tour.index + 1 === STEPS.length;

  const advance = () => {
    const nextIdx = tour.index + 1;
    tour.next();
    const nextStep = STEPS[nextIdx];
    // Two steps share /command - the opener explains the idea, the next one
    // reads the screen - so only navigate when the page actually changes.
    if (nextStep && nextStep.path !== step.path) navigate(nextStep.path);
  };

  return (
    <>
    {step.spotlight && <Spotlight key={step.spotlight} selector={step.spotlight} />}
    <div className="sticky bottom-0 z-50 border-t-2 border-black bg-cyber">
      {/* Progress reads as a bar rather than only a fraction: "3 / 8" says where
          you are, the bar says how much is left. */}
      <div className="h-1.5 w-full bg-black/10">
        <div
          className="h-full bg-black transition-[width] duration-300"
          style={{ width: `${((tour.index + 1) / STEPS.length) * 100}%` }}
        />
      </div>

      <div className="mx-auto flex max-w-[1600px] flex-col gap-3 px-6 py-4 md:flex-row md:items-center">
        <span className="grid h-8 w-8 shrink-0 place-items-center border-2 border-black bg-black font-display text-xs font-extrabold text-cyber">
          {String(tour.index + 1).padStart(2, "0")}
        </span>

        <div className="min-w-0 flex-1">
          <p className="font-display text-sm font-extrabold uppercase tracking-tighter">
            {step.title}
          </p>
          <p className="mt-0.5 max-w-3xl text-[12px] leading-relaxed text-black/70">
            {step.body}
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-3">
          <span className="label hidden sm:block">
            {tour.index + 1} / {STEPS.length}
          </span>

          {tour.index > 0 && (
            <button
              onClick={() => {
                const prev = tour.index - 1;
                tour.goTo(prev);
                const prevStep = STEPS[prev];
                if (prevStep && prevStep.path !== location.pathname) navigate(prevStep.path);
              }}
              className="link-quiet"
            >
              &larr; Back
            </button>
          )}

          {!onStepPage ? (
            <Button variant="dark" onClick={() => navigate(step.path)}>
              Take me there &rarr;
            </Button>
          ) : (
            <Button variant="dark" onClick={advance}>
              {last ? "Done" : `${step.cta} \u2192`}
            </Button>
          )}

          <button
            onClick={tour.stop}
            className="link-quiet"
          >
            Exit
          </button>
        </div>
      </div>
    </div>
    </>
  );
}
