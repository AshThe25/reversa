/**
 * Neo-brutalist primitives.
 *
 * Two rules govern everything here: a 2px black border on anything that is a
 * surface or a control, and a hard offset shadow with zero blur on anything
 * elevated. Interactive elements travel toward their shadow on press rather
 * than lifting away from it.
 *
 * Where the system is not applied is as deliberate as where it is. Table rows
 * get a hairline and a hover fill, never a border and a shadow — a payments
 * console is mostly dense numeric rows, and bordering every one of them is
 * unreadable.
 */

import type { ReactNode } from "react";

import { splitAmount } from "../lib/format";

/* ---------------------------------------------------------------- labels */

export function Label({
  children,
  dark = false,
  htmlFor,
}: {
  children: ReactNode;
  dark?: boolean;
  htmlFor?: string;
}) {
  // Renders a real <label> when it is captioning a control, so a screen reader
  // announces the field by name instead of "textbox". A div otherwise, because
  // most uses here caption a figure rather than an input.
  const className = dark ? "label-invert" : "label";
  if (htmlFor) {
    return (
      <label htmlFor={htmlFor} className={className}>
        {children}
      </label>
    );
  }
  return <div className={className}>{children}</div>;
}

/* -------------------------------------------------------------- surfaces */

export function Glass({
  children,
  className = "",
  float = false,
  strong = false,
  onColour = false,
}: {
  children: ReactNode;
  className?: string;
  float?: boolean;
  strong?: boolean;
  onColour?: boolean;
}) {
  void float;
  return (
    <div className={`${onColour ? "card-dark" : strong ? "card-lg" : "card"} ${className}`}>
      {children}
    </div>
  );
}

export function Panel({
  children,
  className = "",
  title,
  hint,
  action,
  anchor,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  hint?: string;
  action?: ReactNode;
  /** Names this panel so the walkthrough can point at it. */
  anchor?: string;
}) {
  return (
    <section className={`card ${className}`} data-tour={anchor}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-4 border-b-2 border-black px-6 py-4">
          <div>
            {title && (
              <h3 className="font-display text-[13px] font-extrabold uppercase tracking-tighter">
                {title}
              </h3>
            )}
            {hint && <p className="mt-1 max-w-3xl text-xs text-black/60">{hint}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

/* --------------------------------------------------------------- buttons */

export function Button({
  children,
  onClick,
  disabled,
  variant = "solid",
  title,
  className = "",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "solid" | "ghost" | "dark";
  title?: string;
  className?: string;
  type?: "button" | "submit";
}) {
  const base =
    variant === "solid" ? "bg-cyber text-black"
      : variant === "dark" ? "bg-black text-white"
        : "bg-white text-black";
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`btn btn-sm ${base} ${className}`}
    >
      {children}
    </button>
  );
}

/* ---------------------------------------------------------------- badges */

const SEVERITY: Record<string, string> = {
  critical: "bg-signal-loss text-black",
  high: "bg-cyber text-black",
  medium: "bg-sage text-black",
  low: "bg-white text-black",
};

export function Severity({ level }: { level: string }) {
  return <span className={`chip ${SEVERITY[level] ?? SEVERITY.low}`}>{level}</span>;
}

export function Tag({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "yellow" | "good" | "bad" | "info";
}) {
  const tones = {
    neutral: "bg-white text-black",
    yellow: "bg-cyber text-black",
    good: "bg-signal-calm text-black",
    bad: "bg-signal-loss text-black",
    info: "bg-sage text-black",
  };
  return <span className={`chip ${tones[tone]}`}>{children}</span>;
}

/* ----------------------------------------------------------------- money */

/**
 * A headline amount. The fractional part and the unit are set lighter than the
 * magnitude, so the eye takes the order of magnitude first and the precision
 * only if it looks for it.
 */
export function Money({
  paise,
  className = "",
  tone = "default",
}: {
  paise: number;
  className?: string;
  tone?: "default" | "yellow" | "muted" | "loss";
}) {
  const { sign, whole, fraction, unit } = splitAmount(paise);
  const colour = {
    default: "text-black",
    yellow: "text-black",
    muted: "text-black/70",
    loss: "text-signal-loss-ink",
  }[tone];
  return (
    <span className={`tnum font-display font-extrabold tracking-tighter ${colour} ${className}`}>
      {sign}
      <span className="opacity-80">₹</span>
      {whole}
      <span className="opacity-80">
        {fraction}
        {unit}
      </span>
    </span>
  );
}

/* ------------------------------------------------------------ stat tiles */

export function Stat({
  label,
  value,
  sub,
  tone = "default",
  hint,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "default" | "yellow" | "muted" | "loss";
  hint?: string;
}) {
  const colour = {
    default: "text-black",
    yellow: "text-black",
    muted: "text-black/70",
    loss: "text-signal-loss-ink",
  }[tone];
  return (
    <div className="min-w-0" title={hint}>
      <Label>{label}</Label>
      <div
        className={`tnum mt-2 font-display text-3xl font-extrabold tracking-tighter ${colour}`}
      >
        {value}
      </div>
      {sub && <div className="mt-1 truncate text-xs text-black/60">{sub}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ misc */

export function Bar({
  value,
  max,
  tone = "yellow",
}: {
  value: number;
  max: number;
  tone?: "yellow" | "muted" | "loss";
}) {
  const width = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const fill = { yellow: "bg-cyber", muted: "bg-sage", loss: "bg-signal-loss" }[tone];
  return (
    <div className="h-3 w-full overflow-hidden rounded-neo border-2 border-black bg-white">
      <div
        className={`h-full ${fill} transition-[width] duration-500`}
        style={{ width: `${width}%`, borderRight: width > 0 && width < 100 ? "2px solid #000" : "none" }}
      />
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 font-display text-xs font-extrabold uppercase tracking-label">
      <span className="h-3 w-3 animate-pulse border-2 border-black bg-cyber" />
      {label ?? "Working"}
    </div>
  );
}

/**
 * Placeholder rows while data is in flight.
 *
 * Soft, not bordered. A skeleton drawn in the same 2px black as real content
 * reads as content that has arrived and is empty, which is worse than an
 * obvious placeholder - the eye stops on it and waits for meaning. Grey bars of
 * uneven width read as "not here yet" without anyone having to think about it.
 */
export function Skeleton({ rows = 3 }: { rows?: number }) {
  // Uneven widths, deterministic per row. Equal bars look like a table with no
  // data; ragged ones look like text that has not loaded.
  const widths = ["82%", "64%", "91%", "73%", "58%", "86%"];
  return (
    <div className="space-y-3 p-6" role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-4 animate-pulse rounded-full bg-black/10"
          style={{ width: widths[i % widths.length] }}
        />
      ))}
    </div>
  );
}

/** A stat tile that has not arrived. Same box, no number. */
export function StatSkeleton({ label }: { label?: string }) {
  return (
    <div className="card p-6" role="status" aria-label="Loading">
      {label ? <Label>{label}</Label> : <div className="h-3 w-24 animate-pulse rounded-full bg-black/10" />}
      <div className="mt-3 h-8 w-32 animate-pulse rounded-full bg-black/10" />
      <div className="mt-3 h-3 w-40 animate-pulse rounded-full bg-black/10" />
    </div>
  );
}

export function Empty({ title, body }: { title: string; body?: string }) {
  return (
    <div className="px-6 py-14 text-center">
      <p className="font-display text-sm font-extrabold uppercase tracking-tighter">{title}</p>
      {body && <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-black/60">{body}</p>}
    </div>
  );
}

export function ErrorNote({ message, requestId }: { message: string; requestId?: string }) {
  return (
    <div className="rounded-neo border-2 border-black bg-signal-loss px-5 py-4 text-black shadow-hard-sm">
      <div className="label-invert">Request failed</div>
      <p className="mt-2 text-sm font-semibold">{message}</p>
      {requestId && <p className="mt-1 font-mono text-[11px] opacity-70">request {requestId}</p>}
    </div>
  );
}

export function LiquidBase({ className = "" }: { className?: string }) {
  return <div className={`h-1 bg-black ${className}`} aria-hidden />;
}
