import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { currentRole } from "../lib/api";
import { STEPS, useTour } from "../lib/tour";
import { Button, Tag } from "./primitives";

const NAV = [
  { to: "/command", label: "Command Centre" },
  { to: "/incidents", label: "Incidents" },
  { to: "/futures", label: "Futures" },
  { to: "/portfolio", label: "Portfolio" },
  { to: "/experiments", label: "Experiments" },
  { to: "/autopsy", label: "Autopsy" },
  { to: "/policies", label: "Policies" },
  { to: "/audit", label: "Audit" },
  { to: "/evaluation", label: "Evaluation" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const role = currentRole();

  return (
    <div className="min-h-full bg-onyx">
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-onyx/85 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1600px] items-center gap-6 px-6 py-3">
          <NavLink to="/" className="group flex items-center gap-3">
            <span className="grid h-8 w-8 place-items-center rounded-full bg-cyber text-[13px] font-black text-onyx">
              R
            </span>
            <span className="text-[15px] font-bold tracking-tight">REVERSA</span>
          </NavLink>

          <nav className="hidden flex-1 items-center gap-1 lg:flex">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  [
                    "rounded-full px-3 py-1.5 text-[12px] font-medium transition-colors duration-200",
                    isActive
                      ? "bg-cyber text-onyx"
                      : "text-white/45 hover:bg-white/[0.06] hover:text-white/80",
                  ].join(" ")
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            {role && (
              <Tag tone={role === "operator" ? "yellow" : "neutral"}>
                {role === "operator" ? "OPERATOR" : "DEMO · read + simulate"}
              </Tag>
            )}
          </div>
        </div>

        <nav className="flex gap-1 overflow-x-auto px-6 pb-2 lg:hidden">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                [
                  "whitespace-nowrap rounded-full px-3 py-1.5 text-[12px]",
                  isActive ? "bg-cyber text-onyx" : "text-white/45",
                ].join(" ")
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main key={location.pathname} className="animate-rise">
        {children}
      </main>

      <TourBar />
      <footer className="border-t border-white/[0.06] px-6 py-8">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-4">
          <p className="text-[11px] text-white/25">
            Reversa · counterfactual revenue recovery · Razorpay AI Buildathon 2026
          </p>
          <p className="text-[11px] text-white/25">
            Every figure on this site is computed by a backend engine. None are authored.
          </p>
        </div>
      </footer>
    </div>
  );
}

/**
 * The walkthrough bar.
 *
 * Docked, never modal. It cannot cover a number the reader is looking at, and
 * every step has a visible way out - a tour you cannot escape is worse than no
 * tour at all.
 */
function TourBar() {
  const tour = useTour();
  const navigate = useNavigate();
  const location = useLocation();

  if (!tour.active || !tour.step) return null;
  const step = tour.step;
  const onStepPage = location.pathname === step.path;

  return (
    <div className="sticky bottom-0 z-50 border-t border-cyber/25 bg-cyber text-onyx">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-3 px-6 py-4 md:flex-row md:items-center">
        <div className="flex items-center gap-3">
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-onyx text-[11px] font-black text-cyber">
            {tour.index + 1}
          </span>
          <div className="hidden h-8 w-px bg-onyx/15 md:block" />
        </div>

        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-bold tracking-tight">{step.title}</p>
          <p className="mt-0.5 max-w-3xl text-[12px] leading-relaxed text-onyx/70">
            {step.body}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <span className="label-dark hidden sm:block">
            {tour.index + 1} / {STEPS.length}
          </span>
          {!onStepPage ? (
            <Button variant="dark" onClick={() => navigate(step.path)}>
              {step.cta} →
            </Button>
          ) : (
            <Button variant="dark" onClick={() => {
              const nextIdx = tour.index + 1;
              tour.next();
              const nextStep = STEPS[nextIdx];
              if (nextStep) navigate(nextStep.path);
            }}>
              {tour.index + 1 === STEPS.length ? "Done" : "Next →"}
            </Button>
          )}
          <button
            onClick={tour.stop}
            className="rounded-full px-3 py-2 text-[12px] font-medium text-onyx/50 transition-colors hover:text-onyx"
          >
            Exit
          </button>
        </div>
      </div>
    </div>
  );
}
