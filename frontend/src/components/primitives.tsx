/**
 * Design primitives for Hyper-Saturated Fluid.
 *
 * The system's own rule is "unapologetically loud but structurally disciplined",
 * and the discipline has to live somewhere. It lives here: the yellow is used
 * for one thing at a time, glass floats only over colour, and dense numeric
 * surfaces sit in the void where they can actually be read.
 */

import type { ReactNode } from "react";

import { splitAmount } from "../lib/format";

/* ---------------------------------------------------------------- labels */

export function Label({ children, dark = false }: { children: ReactNode; dark?: boolean }) {
  return <div className={dark ? "label-dark" : "label"}>{children}</div>;
}

/* ------------------------------------------------------------------ glass */

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
  /** Set when the card sits on the saturated hero rather than the void. */
  onColour?: boolean;
}) {
  return (
    <div
      className={[
        onColour ? "glass-void" : strong ? "glass-strong" : "glass",
        "shadow-2xl shadow-black/40",
        float ? "animate-float" : "",
        className,
      ].join(" ")}
    >
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
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-4 border-b border-white/[0.06] px-6 py-4">
          <div>
            {title && <Label>{title}</Label>}
            {hint && <p className="mt-1 text-xs text-white/35">{hint}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

/* ---------------------------------------------------------------- buttons */

type ButtonProps = {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "solid" | "ghost" | "dark";
  title?: string;
  className?: string;
  type?: "button" | "submit";
};

export function Button({
  children,
  onClick,
  disabled,
  variant = "solid",
  title,
  className = "",
  type = "button",
}: ButtonProps) {
  const base =
    variant === "solid" ? "pill-solid" : variant === "dark" ? "pill-dark" : "pill-ghost";
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${disabled ? "cursor-not-allowed opacity-40 hover:shadow-none" : ""} ${className}`}
    >
      {children}
    </button>
  );
}

/* ----------------------------------------------------------------- badges */

const SEVERITY: Record<string, string> = {
  critical: "bg-signal-loss/15 text-signal-loss border-signal-loss/30",
  high: "bg-cyber/15 text-cyber border-cyber/30",
  medium: "bg-signal-info/15 text-signal-info border-signal-info/30",
  low: "bg-white/10 text-white/60 border-white/15",
};

export function Severity({ level }: { level: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-label ${
        SEVERITY[level] ?? SEVERITY.low
      }`}
    >
      {level}
    </span>
  );
}

export function Tag({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "yellow" | "good" | "bad" | "info";
}) {
  const tones = {
    neutral: "border-white/12 bg-white/[0.04] text-white/55",
    yellow: "border-cyber/30 bg-cyber/10 text-cyber",
    good: "border-signal-calm/30 bg-signal-calm/10 text-signal-calm",
    bad: "border-signal-loss/30 bg-signal-loss/10 text-signal-loss",
    info: "border-signal-info/30 bg-signal-info/10 text-signal-info",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

/* ----------------------------------------------------------------- money */

/**
 * A headline amount.
 *
 * The fractional part and the unit are set lighter than the magnitude. It is a
 * small thing that does most of the work in making a figure feel designed
 * rather than printed - the eye gets the order of magnitude immediately and the
 * precision only if it looks for it.
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
    default: "text-white",
    yellow: "text-cyber",
    muted: "text-white/45",
    loss: "text-signal-loss",
  }[tone];
  return (
    <span className={`tnum ${colour} ${className}`}>
      {sign}
      <span className="opacity-45">₹</span>
      {whole}
      <span className="opacity-45">
        {fraction}
        {unit}
      </span>
    </span>
  );
}

/* ------------------------------------------------------------- stat tiles */

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
    default: "text-white",
    yellow: "text-cyber",
    muted: "text-white/45",
    loss: "text-signal-loss",
  }[tone];
  return (
    <div className="min-w-0" title={hint}>
      <Label>{label}</Label>
      <div className={`tnum mt-2 text-3xl font-bold tracking-tight ${colour}`}>{value}</div>
      {sub && <div className="mt-1 truncate text-xs text-white/35">{sub}</div>}
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
  const pctWidth = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const fill = {
    yellow: "bg-cyber",
    muted: "bg-white/25",
    loss: "bg-signal-loss",
  }[tone];
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.07]">
      <div
        className={`h-full rounded-full ${fill} transition-[width] duration-700 ease-liquid`}
        style={{ width: `${pctWidth}%` }}
      />
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-sm text-white/40">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyber opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-cyber" />
      </span>
      {label ?? "Working"}
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-6">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="relative overflow-hidden rounded-full bg-white/[0.05]" style={{ height: 12 }}>
          <div className="absolute inset-y-0 w-1/3 animate-sweep bg-gradient-to-r from-transparent via-white/[0.08] to-transparent" />
        </div>
      ))}
    </div>
  );
}

export function Empty({ title, body }: { title: string; body?: string }) {
  return (
    <div className="px-6 py-14 text-center">
      <p className="text-sm font-medium text-white/60">{title}</p>
      {body && <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-white/30">{body}</p>}
    </div>
  );
}

export function ErrorNote({ message, requestId }: { message: string; requestId?: string }) {
  return (
    <div className="rounded-[20px] border border-signal-loss/25 bg-signal-loss/[0.06] px-5 py-4">
      <Label>Request failed</Label>
      <p className="mt-2 text-sm text-white/75">{message}</p>
      {requestId && (
        <p className="mt-1 font-mono text-[11px] text-white/25">request {requestId}</p>
      )}
    </div>
  );
}

/**
 * The liquid seam between a saturated section and the void.
 *
 * Asymmetric by design - a symmetric curve reads as a rounded box, which is
 * exactly the generic look the system is trying to avoid.
 */
export function LiquidBase({ className = "" }: { className?: string }) {
  return (
    <div
      className={`h-16 bg-onyx ${className}`}
      style={{ borderRadius: "0 120px 0 0" }}
      aria-hidden
    />
  );
}
