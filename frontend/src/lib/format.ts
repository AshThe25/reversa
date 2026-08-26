/**
 * Money and number formatting.
 *
 * Every rupee figure in the app goes through here. The backend speaks paise
 * (integers) end to end so nothing is ever a float, and this is the single
 * place that converts - if it were done at call sites, one of them would
 * eventually divide by 100 twice and nobody would notice until a demo.
 *
 * Indian digit grouping is not the western one: 1,23,45,678 rather than
 * 12,345,678. Intl handles it with the en-IN locale; hand-rolled grouping
 * gets it wrong.
 */

const PAISE_PER_RUPEE = 100;
const PAISE_PER_LAKH = 100 * 100_000; // 1e7
const PAISE_PER_CRORE = 100 * 1_00_00_000; // 1e9

/** Compact, for headline tiles: "₹31.72L", "₹1.24Cr". */
export function lakhs(paise: number, digits = 2): string {
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(paise);
  if (abs >= PAISE_PER_CRORE) {
    return `${sign}₹${(abs / PAISE_PER_CRORE).toFixed(digits)}Cr`;
  }
  if (abs >= PAISE_PER_LAKH / 10) {
    return `${sign}₹${(abs / PAISE_PER_LAKH).toFixed(digits)}L`;
  }
  return `${sign}₹${Math.round(abs / PAISE_PER_RUPEE).toLocaleString("en-IN")}`;
}

/** Exact, for tables and tooltips: "₹3,17,240". */
export function rupees(paise: number): string {
  const sign = paise < 0 ? "-" : "";
  return `${sign}₹${Math.round(Math.abs(paise) / PAISE_PER_RUPEE).toLocaleString(
    "en-IN",
  )}`;
}

export function count(n: number): string {
  return n.toLocaleString("en-IN");
}

export function pct(fraction: number, digits = 1): string {
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function signedPct(fraction: number, digits = 2): string {
  const s = (fraction * 100).toFixed(digits);
  return `${fraction >= 0 ? "+" : ""}${s}%`;
}

/** p-values and q-values are astronomically small here; 0.00 would be a lie. */
export function sci(value: number): string {
  if (value === 0) return "0";
  if (value >= 0.001) return value.toFixed(3);
  return value.toExponential(1).replace("e", "e");
}

export function timeIST(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Kolkata",
  });
}

export function dateTimeIST(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Kolkata",
  });
}

export function duration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** "7m 12s" - used for capacity-exhaustion forecasts. */
export function minutesToClock(minutes: number | null): string {
  if (minutes === null || !Number.isFinite(minutes)) return "—";
  const m = Math.floor(minutes);
  const s = Math.round((minutes - m) * 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function titleise(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
