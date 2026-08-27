import { useEffect, useState } from "react";

import { Label, Tag } from "../components/primitives";
import { ApiError, openSession } from "../lib/api";

/**
 * The way in.
 *
 * Two doors, and the difference between them is the product's whole safety
 * story rather than a permissions detail:
 *
 *   Demo — one click, no credential, read + simulate. Every future in the wind
 *     tunnel is explorable and there is no path from this browser to moving
 *     money. That is enforced server-side; the disabled buttons are a courtesy.
 *
 *   Operator — an access code, and the execute scope that comes with it.
 *
 * A judge should never be stuck at a login wall, so the demo door is the
 * primary action and the operator door is folded away until asked for.
 */
export function SignIn({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [busy, setBusy] = useState<"demo" | "operator" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCode, setShowCode] = useState(false);
  const [code, setCode] = useState("");

  useEffect(() => {
    document.title = "Sign in · Reversa";
    // Put it back on the way out, or the tab keeps saying "Sign in" for the
    // rest of the session.
    return () => {
      document.title = "Reversa";
    };
  }, []);

  const enter = async (mode: "demo" | "operator") => {
    setBusy(mode);
    setError(null);
    try {
      await openSession(mode === "operator" ? code : undefined);
      onAuthenticated();
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Could not reach the Reversa API.",
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="ambient relative grid min-h-full place-items-center px-5 py-12">
      <div className="above w-full max-w-[440px]">
        <div className="flex items-center gap-3">
          <span className="orb grid h-9 w-9 place-items-center text-[13px] font-black text-onyx">
            R
          </span>
          <span className="text-[15px] font-bold tracking-tight">REVERSA</span>
        </div>

        <h1 className="mt-9 text-4xl font-bold leading-[1.05] tracking-tight">
          Revenue recovery,
          <br />
          <span className="text-white/35">before reality.</span>
        </h1>
        <p className="mt-4 text-[13px] leading-relaxed text-white/45">
          Test recovery strategies against a simulation of the affected cohort
          before spending a customer interaction — then prove which one created
          incremental revenue.
        </p>

        <div className="surface mt-9 p-6">
          <button
            onClick={() => enter("demo")}
            disabled={busy !== null}
            className="pill-solid w-full justify-center py-3 text-[15px] font-semibold disabled:opacity-50"
          >
            {busy === "demo" ? "Opening session…" : "Continue as guest"}
          </button>

          <p className="mt-3 text-center text-[11px] leading-relaxed text-white/35">
            Read and simulate. You can run every future in the wind tunnel;
            deploying a strategy is refused server-side.
          </p>

          <div className="my-6 flex items-center gap-3">
            <span className="h-px flex-1 bg-white/[0.07]" />
            <span className="label">or</span>
            <span className="h-px flex-1 bg-white/[0.07]" />
          </div>

          {!showCode ? (
            <button
              onClick={() => setShowCode(true)}
              className="pill-ghost w-full justify-center py-3 text-[14px]"
            >
              Sign in as operator
            </button>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (code.trim()) enter("operator");
              }}
            >
              <Label>Access code</Label>
              <input
                autoFocus
                type="password"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="Operator access code"
                autoComplete="one-time-code"
                className="mt-2 w-full rounded-full border border-white/10 bg-black/40 px-5 py-3
                           text-[14px] text-white/85 outline-none transition-colors
                           placeholder:text-white/25 focus:border-cyber/45"
              />
              <button
                type="submit"
                disabled={busy !== null || !code.trim()}
                className="pill-ghost mt-3 w-full justify-center py-3 text-[14px] disabled:opacity-40"
              >
                {busy === "operator" ? "Verifying…" : "Enter"}
              </button>
              <p className="mt-3 text-center text-[11px] leading-relaxed text-white/30">
                Operator sessions carry the execute scope and can move money in
                Razorpay test mode. They are never restored automatically — this
                code is asked for again after every reload.
              </p>
            </form>
          )}

          {error && (
            <p className="mt-4 rounded-[16px] border border-signal-loss/25 bg-signal-loss/[0.06] px-4 py-3 text-[12px] text-white/75">
              {error}
            </p>
          )}
        </div>

        <div className="mt-6 flex flex-wrap gap-2">
          <Tag tone="neutral">No account needed</Tag>
          <Tag tone="neutral">Holdout-measured</Tag>
          <Tag tone="neutral">Hash-chained audit</Tag>
        </div>

        <p className="mt-8 text-[11px] leading-relaxed text-white/25">
          The session token is held in memory and never written to browser
          storage — anything an injected script can read is a credential you have
          already given away, and this one authorises money movement.
        </p>
      </div>
    </div>
  );
}
