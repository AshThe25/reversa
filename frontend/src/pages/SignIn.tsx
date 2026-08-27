import { useEffect, useState } from "react";

import { Label, Tag } from "../components/primitives";
import { ApiError, openSession } from "../lib/api";

/**
 * The way in.
 *
 * Two doors, and the difference between them is the product's whole safety
 * story rather than a permissions detail:
 *
 *   Demo — one click, no credential, read + simulate. Every strategy is
 *     explorable and there is no path from this browser to moving money. That is
 *     enforced server-side; the disabled buttons are a courtesy.
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
    <div className="dot-field relative grid min-h-full place-items-center bg-cyber px-5 py-12">
      <div className="relative z-10 w-full max-w-[460px]">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center border-2 border-black bg-black font-display text-lg font-extrabold text-cyber">
            R
          </span>
          <span className="font-display text-xl font-extrabold uppercase tracking-tighter">Reversa</span>
        </div>

        <h1 className="mt-10 font-display text-5xl font-extrabold uppercase leading-[0.92] tracking-tighter">
          Revenue
          <br />
          recovery,
          <br />
          <span className="text-stroke">before reality.</span>
        </h1>
        <p className="mt-4 text-[13px] leading-relaxed text-black/45">
          Evaluate dunning strategies against the affected cohort before a
          single customer is contacted, then measure which one produced
          incremental revenue against a randomised holdout.
        </p>

        <div className="card-lg mt-10 bg-white p-6">
          <button
            onClick={() => enter("demo")}
            disabled={busy !== null}
            className="btn w-full bg-black py-4 text-base text-white"
          >
            {busy === "demo" ? "Opening session…" : "Continue as guest"}
          </button>

          <p className="mt-3 text-center text-[11px] leading-relaxed text-black/35">
            Read and model. Every strategy is explorable; deploying one is
            refused server-side.
          </p>

          <div className="my-6 flex items-center gap-3">
            <span className="h-px flex-1 bg-black/[0.03]" />
            <span className="label">or</span>
            <span className="h-px flex-1 bg-black/[0.03]" />
          </div>

          {!showCode ? (
            <button
              onClick={() => setShowCode(true)}
              className="btn w-full bg-white py-4 text-sm"
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
                className="mt-2 w-full rounded-neo border-2 border-black bg-white px-4 py-3 font-mono text-[14px] outline-none placeholder:text-black/30"
              />
              <button
                type="submit"
                disabled={busy !== null || !code.trim()}
                className="btn mt-3 w-full bg-cyber py-4 text-sm"
              >
                {busy === "operator" ? "Verifying…" : "Enter"}
              </button>
              <p className="mt-3 text-center text-[11px] leading-relaxed text-black/30">
                Operator sessions carry the execute scope and can move money in
                Razorpay test mode. They are never restored automatically — this
                code is asked for again after every reload.
              </p>
            </form>
          )}

          {error && (
            <p className="mt-4 rounded-[16px] border border-black bg-signal-loss/10 px-4 py-3 text-[12px] text-black/75">
              {error}
            </p>
          )}
        </div>

        <div className="mt-6 flex flex-wrap gap-2">
          <Tag tone="neutral">No account needed</Tag>
          <Tag tone="neutral">Holdout-measured</Tag>
          <Tag tone="neutral">Hash-chained audit</Tag>
        </div>

        <p className="mt-8 text-[11px] leading-relaxed text-black/50">
          The session token is held in memory and never written to browser storage.
          Anything an injected script can read is a credential you have already
          given away, and this one authorises money movement.
        </p>
      </div>
    </div>
  );
}
