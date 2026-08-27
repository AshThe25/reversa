import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { currentRole } from "../lib/api";
import { STEPS, useTour } from "../lib/tour";
import { Button, Tag } from "./primitives";

const NAV = [
  { to: "/command", label: "Command" },
  { to: "/incidents", label: "Incidents" },
  { to: "/futures", label: "Futures" },
  { to: "/portfolio", label: "Portfolio" },
  { to: "/experiments", label: "Experiments" },
  { to: "/autopsy", label: "Autopsy" },
  { to: "/policies", label: "Policies" },
  { to: "/audit", label: "Audit" },
  { to: "/evaluation", label: "Evaluation" },
];

/**
 * The app shell.
 *
 * Chrome floats and is frosted; content sits on the void beneath an ambient
 * light bleed. The nav is a recessed track with a raised thumb on the active
 * item — the same inversion a physical switch uses, and the reason it reads as
 * a control rather than a row of links.
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
    <div className="ambient relative min-h-full">
      <header className="above sticky top-0 z-40 px-4 pt-4">
        <div className="mx-auto flex max-w-[1600px] items-center gap-4 rounded-full frost px-3 py-2">
          <NavLink to="/" className="flex shrink-0 items-center gap-2.5 pl-1.5">
            <span className="orb grid h-7 w-7 place-items-center text-[12px] font-black text-onyx">
              R
            </span>
            <span className="hidden text-[14px] font-bold tracking-tight sm:block">
              REVERSA
            </span>
          </NavLink>

          <nav className="segment-track min-w-0 flex-1 overflow-x-auto">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `segment whitespace-nowrap ${isActive ? "segment-on" : "hover:text-white/80"}`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          {role && (
            <div className="hidden shrink-0 items-center gap-2 pr-1 lg:flex">
              <Tag tone={role === "operator" ? "yellow" : "neutral"}>
                {role === "operator" ? "OPERATOR" : "GUEST · read + simulate"}
              </Tag>
              {onSignOut && (
                <button
                  onClick={onSignOut}
                  title="End this session"
                  className="rounded-full px-3 py-1.5 text-[11px] font-medium text-white/35
                             transition-colors hover:text-white/80"
                >
                  Sign out
                </button>
              )}
            </div>
          )}
        </div>
      </header>

      <main key={location.pathname} className="above animate-rise">
        {children}
      </main>

      <TourBar />

      <footer className="above px-6 py-10">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-4 border-t border-white/[0.06] pt-8">
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
 * every step has a visible way out — a tour you cannot escape is worse than no
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
    <div className="sticky bottom-0 z-50 px-4 pb-4">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-3 rounded-[28px] bg-cyber px-5 py-4 text-onyx shadow-[0_-8px_40px_-12px_rgba(253,224,71,0.35)] md:flex-row md:items-center">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-onyx text-[11px] font-black text-cyber">
          {tour.index + 1}
        </span>

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
            <Button
              variant="dark"
              onClick={() => {
                const nextIdx = tour.index + 1;
                tour.next();
                const nextStep = STEPS[nextIdx];
                if (nextStep) navigate(nextStep.path);
              }}
            >
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
