/**
 * API client.
 *
 * Two things worth noting.
 *
 * The session token lives in memory, not localStorage. A token in localStorage
 * is readable by any script that gets injected, and the whole point of scoping
 * sessions was that a stolen one shouldn't be useful. Keeping it in a module
 * variable means it dies with the tab, which is the correct lifetime for
 * something that authorises money movement.
 *
 * Errors are normalised into one shape so screens can render a failure without
 * each of them inventing its own handling. The API deliberately returns thin
 * error bodies; this preserves that rather than guessing at detail.
 */

/**
 * Where the API lives.
 *
 * Empty in development, where Vite proxies /api to the local backend, and empty
 * in any deployment that puts the two behind one origin. Set VITE_API_BASE when
 * the frontend is served from somewhere the backend is not - a static host in
 * front of a separate API - and remember the backend's CORS list has to name
 * that origin back, or the browser will block every call and it will look like
 * the API is down.
 */
const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");


import type {
  Attention, AuthResponse, ChainVerdict, ChaosResult, Cohort, ExecutionReport,
  ExperimentResult, Incident, IncidentDetail, Overview, SystemInfo, WindTunnel,
} from "./types";

let token: string | null = null;
let role: "demo" | "operator" | null = null;

/**
 * What survives a refresh, and what deliberately does not.
 *
 * The token itself stays in a module variable - never localStorage, never
 * sessionStorage. Anything readable by an injected script is a credential you
 * have handed away, and this one authorises money movement.
 *
 * What IS persisted is a single flag saying the visitor previously chose the
 * demo role. That is not a credential: a demo session is unauthenticated by
 * design, anyone can open one, and it carries no execute scope. So on reload we
 * silently mint a fresh demo session and the judge never sees a login wall
 * twice. The operator role has no such shortcut - it always costs the access
 * code again, because that is the one that can move money.
 */
const ROLE_FLAG = "reversa.role";

function rememberDemo() {
  try {
    sessionStorage.setItem(ROLE_FLAG, "demo");
  } catch {
    /* private mode, storage disabled - the app still works, just re-prompts */
  }
}

export function preferredRole(): "demo" | null {
  try {
    return sessionStorage.getItem(ROLE_FLAG) === "demo" ? "demo" : null;
  } catch {
    return null;
  }
}

export function signOut() {
  token = null;
  role = null;
  try {
    sessionStorage.removeItem(ROLE_FLAG);
  } catch {
    /* nothing to clear */
  }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId?: string,
    readonly detail?: unknown,
  ) {
    super(message);
  }
}

export function currentRole(): "demo" | "operator" | null {
  return role;
}

export function can(scope: "read" | "simulate" | "execute"): boolean {
  if (role === "operator") return true;
  return role === "demo" && scope !== "execute";
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  attempt = 0,
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(API_BASE + path, { ...init, headers });
  const requestId = res.headers.get("X-Request-Id") ?? undefined;

  if (res.status === 401 && attempt === 0 && role === "demo") {
    // Demo sessions are unauthenticated and cheap to re-mint, so an expired one
    // (or a server restart with a fresh secret) should not interrupt a
    // walkthrough. An operator session is NOT silently re-opened - losing it
    // means re-entering the access code, which is the point of having one.
    await openSession();
    return request<T>(path, init, attempt + 1);
  }

  if (!res.ok) {
    let code = `http_${res.status}`;
    let detail: unknown;
    try {
      const body = await res.json();
      detail = body?.detail ?? body;
      const d = body?.detail ?? body;
      if (typeof d === "object" && d && "error" in d) code = String(d.error);
      else if (typeof body?.error === "string") code = body.error;
    } catch {
      /* thin or empty error body - keep the status code */
    }
    throw new ApiError(res.status, code, describe(res.status, code), requestId, detail);
  }

  return (await res.json()) as T;
}

function describe(status: number, code: string): string {
  switch (code) {
    case "unauthenticated":
      return "Session expired. Reload to continue.";
    case "insufficient_scope":
      return "This demo session can simulate but not execute.";
    case "rate_limited":
      return "Too many requests in a short window. Give it a moment.";
    case "cohort_has_no_actionable_candidates":
      return "Every payment in this cohort is blocked by a compliance gate.";
    case "unknown_incident":
      return "That incident is no longer in the current scan.";
    default:
      return status >= 500
        ? "The server hit an unexpected error."
        : `Request failed (${code}).`;
  }
}

export async function openSession(accessCode?: string): Promise<AuthResponse> {
  const res = await fetch(API_BASE + "/api/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(accessCode ? { access_code: accessCode } : {}),
  });
  if (!res.ok) {
    let code = "auth_failed";
    try {
      const body = await res.json();
      code = body?.detail?.error ?? code;
    } catch {
      /* thin error body */
    }
    throw new ApiError(
      res.status,
      code,
      code === "invalid_access_code"
        ? "That access code was not accepted."
        : "Could not reach the Reversa API.",
    );
  }
  const body = (await res.json()) as AuthResponse;
  token = body.token;
  role = body.role;
  if (role === "demo") rememberDemo();
  return body;
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  system: () => request<SystemInfo>("/api/system"),
  overview: () => request<Overview>("/api/overview"),
  attention: () => request<Attention>("/api/attention"),

  incidents: () =>
    request<{ incidents: Incident[] }>("/api/incidents").then((r) => r.incidents),
  incident: (id: string) => request<IncidentDetail>(`/api/incidents/${id}`),
  cohort: (id: string) => request<Cohort>(`/api/incidents/${id}/cohort`),
  review: (incidentId: string) =>
    request<import("./types").ReviewQueue>(
      `/api/review?incident=${encodeURIComponent(incidentId)}`,
    ),

  investigation: (id: string) =>
    request<import("./types").Investigation>(`/api/incidents/${id}/investigation`),
  rescan: () =>
    request<{ incidents: Incident[]; scan_ms: number }>("/api/incidents/scan", {
      method: "POST",
      body: JSON.stringify({ force: true }),
    }),

  windTunnel: (incidentId: string, capacity?: Record<string, number>) =>
    request<WindTunnel>("/api/windtunnel", {
      method: "POST",
      body: JSON.stringify({ incident_id: incidentId, capacity }),
    }),

  chaos: (body: {
    incident_id: string;
    volume_multiplier: number;
    capacity_multiplier: number;
    arrivals_per_minute: number;
  }) => request<ChaosResult>("/api/chaos", { method: "POST", body: JSON.stringify(body) }),

  execute: (body: {
    incident_id: string;
    scenario: string;
    holdout_fraction?: number;
    exploration_fraction?: number;
  }) =>
    request<ExecutionReport>("/api/experiments/execute", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  experiments: () =>
    request<{ experiments: { id: string; name: string; status: string; results: ExperimentResult | Record<string, never> }[] }>(
      "/api/experiments",
    ).then((r) => r.experiments),

  experiment: (id: string) =>
    request<{ id: string; name: string; results: ExperimentResult }>(
      `/api/experiments/${id}`,
    ),

  audit: (limit = 120) =>
    request<{ events: import("./types").AuditEntry[] }>(`/api/audit?limit=${limit}`).then(
      (r) => r.events,
    ),

  verifyChain: () => request<ChainVerdict>("/api/audit/verify"),

  policyCapabilities: () =>
    request<import("./types").PolicyCapabilities>("/api/policies/capabilities"),

  compilePolicy: (text: string, name: string) =>
    request<import("./types").PolicyResponse>("/api/policies/compile", {
      method: "POST",
      body: JSON.stringify({ text, name }),
    }),

  simulatePolicy: (incidentId: string, text: string, name: string) =>
    request<import("./types").PolicyResponse>("/api/policies/simulate", {
      method: "POST",
      body: JSON.stringify({ incident_id: incidentId, text, name }),
    }),

  evaluation: () => request<import("./types").Evaluation>("/api/evaluation"),
};
