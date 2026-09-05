import { useEffect, useState } from "react";

import { Button, Label } from "./primitives";

/**
 * Asks, once, why someone is leaving.
 *
 * Fires on exit intent - the cursor leaving through the top of the window,
 * which on a desktop browser means they are reaching for the tab bar or the
 * address bar. Not on scroll, not on a timer, and never more than once per
 * person: a prompt that reappears is a prompt that gets dismissed without being
 * read, and then it has cost attention and bought nothing.
 *
 * It cannot block anyone from leaving. There is no beforeunload handler here on
 * purpose - hijacking the close button to beg for feedback is the kind of thing
 * that makes people remember a product for the wrong reason.
 *
 * Answers go to the console and to localStorage rather than to a server. There
 * is no feedback endpoint, and inventing one that quietly ships a stranger's
 * text somewhere would be a worse decision than collecting nothing.
 */
const SEEN_KEY = "reversa.exit.asked";

const REASONS = [
  "I did not understand what it does",
  "I was looking for something else",
  "Too much on screen",
  "Something looked broken",
  "Just browsing",
];

export function ExitPrompt() {
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState(false);
  const [reason, setReason] = useState<string | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => {
    try {
      if (localStorage.getItem(SEEN_KEY) === "1") return;
    } catch {
      /* storage blocked; the prompt simply may appear again next visit */
    }

    const onLeave = (e: MouseEvent) => {
      // Only the top edge, and only from inside the document. Leaving sideways
      // is usually reaching for a second monitor.
      if (e.clientY > 0 || e.relatedTarget) return;
      setOpen(true);
      try {
        localStorage.setItem(SEEN_KEY, "1");
      } catch {
        /* nothing to do; worst case it asks once more another day */
      }
      document.removeEventListener("mouseout", onLeave);
    };

    // A grace period, so it cannot fire while someone is still arriving.
    const timer = window.setTimeout(
      () => document.addEventListener("mouseout", onLeave),
      20_000,
    );
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("mouseout", onLeave);
    };
  }, []);

  if (!open) return null;

  const close = () => setOpen(false);

  const submit = () => {
    // eslint-disable-next-line no-console
    console.info("[reversa] exit feedback", { reason, note });
    try {
      localStorage.setItem(
        "reversa.exit.answer",
        JSON.stringify({ reason, note, at: new Date().toISOString() }),
      );
    } catch {
      /* recorded in the console either way */
    }
    setSent(true);
    window.setTimeout(close, 1400);
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-end justify-center p-4 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-label="Before you go"
    >
      <button
        aria-label="Close"
        onClick={close}
        className="absolute inset-0 cursor-default bg-black/40"
      />
      <div className="card relative w-full max-w-lg animate-rise bg-white p-6 shadow-hard">
        {sent ? (
          <p className="py-6 text-center text-sm font-semibold">
            Thank you — that is genuinely useful.
          </p>
        ) : (
          <>
            <Label>Before you go</Label>
            <h2 className="mt-2 font-display text-xl font-extrabold uppercase tracking-tighter">
              What did not land?
            </h2>
            <p className="mt-2 text-[13px] leading-relaxed text-black/70">
              One click is plenty. It helps me work out which part of this is not
              explaining itself.
            </p>

            <div className="mt-4 flex flex-wrap gap-2">
              {REASONS.map((r) => (
                <button
                  key={r}
                  onClick={() => setReason(r)}
                  className={`chip ${reason === r ? "bg-cyber" : "bg-white"}`}
                >
                  {r}
                </button>
              ))}
            </div>

            <label htmlFor="exit-note" className="label mt-5 block">
              Anything else (optional)
            </label>
            <textarea
              id="exit-note"
              value={note}
              onChange={(e) => setNote(e.target.value.slice(0, 500))}
              rows={3}
              className="mt-2 w-full rounded-neo border-2 border-black bg-white p-3 text-[13px]"
            />

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <Button variant="dark" onClick={submit} disabled={!reason && !note.trim()}>
                Send
              </Button>
              <button onClick={close} className="link-quiet">
                No thanks
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
