import { useState } from "react";

import {
  Button, ErrorNote, Label, Panel, Skeleton, Spinner, Tag,
} from "../components/primitives";
import { useAsync } from "../hooks/useAsync";
import { ApiError, api, can } from "../lib/api";
import { count, lakhs } from "../lib/format";
import type { PolicyResponse } from "../lib/types";

const EXAMPLE = `Prioritize customers above Rs 5,000.
Don't contact customers likely to recover naturally.
During an active UPI outage, wait until recovery stabilizes.
Escalate transactions above Rs 50,000.
Never use voice calls.`;

/**
 * The policy screen.
 *
 * Merchant writes English, sees the deterministic rules it became, and can run
 * the wind tunnel with those rules in force before any of it governs real
 * money. The compiled rules are shown in full rather than summarised — a policy
 * you cannot read is a policy you cannot trust.
 */
export function Policies() {
  const [text, setText] = useState(EXAMPLE);
  const [result, setResult] = useState<PolicyResponse | null>(null);
  const [busy, setBusy] = useState<"compile" | "simulate" | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const capabilities = useAsync(() => api.policyCapabilities(), []);
  const incidents = useAsync(() => api.incidents(), []);

  const target = incidents.data?.filter((i) => !i.ambiguous)
    .sort((a, b) => b.revenue_exposed_paise - a.revenue_exposed_paise)[0];

  const run = async (mode: "compile" | "simulate") => {
    setBusy(mode);
    setError(null);
    try {
      setResult(
        mode === "compile"
          ? await api.compilePolicy(text, "Merchant policy")
          : await api.simulatePolicy(target!.id, text, "Merchant policy"),
      );
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "network", "Request failed."));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      <Label>Natural language, deterministic enforcement</Label>
      <h1 className="mt-2 text-4xl font-bold tracking-tight">Policies</h1>
      <p className="mt-3 max-w-3xl text-sm leading-relaxed text-black/60">
        Write what you want in plain English. It compiles into structured rules that
        deterministic code evaluates — the text is never executed, and the rule
        vocabulary has no way to express permitting anything.
      </p>

      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_1fr]">
        {/* -------------------------------------------------- the editor */}
        <Panel title="Your policy" hint="One instruction per line.">
          <div className="p-6">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              spellCheck={false}
              rows={10}
              className="w-full resize-y rounded-neo border-2 border-black bg-white p-4 font-mono text-[13px] leading-relaxed shadow-hard-inset outline-none"
            />
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Button onClick={() => run("compile")} disabled={busy !== null || !text.trim()}
                      variant="ghost">
                {busy === "compile" ? "Compiling…" : "Compile"}
              </Button>
              <Button onClick={() => run("simulate")}
                      disabled={busy !== null || !text.trim() || !target}>
                {busy === "simulate" ? "Simulating…" : "Compile & simulate ▸"}
              </Button>
              <Button variant="ghost" disabled title="Deploying requires an operator session">
                Deploy
              </Button>
              {!can("execute") && (
                <span className="text-[11px] text-black/60">
                  demo session — compile and simulate only
                </span>
              )}
            </div>
          </div>
        </Panel>

        {/* -------------------------------------------- what policy can do */}
        <Panel title="What a policy can and cannot do" hint="The guarantee, stated up front.">
          {capabilities.loading && <Skeleton rows={6} />}
          {capabilities.data && (
            <div className="grid gap-6 p-6 sm:grid-cols-2">
              <div>
                <Label>Can</Label>
                <ul className="mt-3 space-y-2">
                  {capabilities.data.can.map((c) => (
                    <li key={c} className="flex gap-2.5 text-[12px] leading-relaxed text-black/60">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-cyber" />
                      {c}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <Label>Cannot</Label>
                <ul className="mt-3 space-y-2">
                  {capabilities.data.cannot.map((c) => (
                    <li key={c} className="flex gap-2.5 text-[12px] leading-relaxed text-black/60">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-signal-loss/60" />
                      {c}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </Panel>
      </div>

      {error && (
        <div className="mt-6">
          <ErrorNote message={error.message} requestId={error.requestId} />
        </div>
      )}
      {busy && (
        <div className="mt-6">
          <Spinner label={busy === "simulate" ? "Compiling and re-solving the cohort" : "Compiling"} />
        </div>
      )}

      {result && (
        <>
          <Panel
            className="mt-6"
            title="Compiled rules"
            hint={`Compiled by the ${result.path === "llm" ? "language model" : "deterministic compiler"}, then validated against the schema.`}
            action={
              <div className="flex gap-2">
                <Tag tone={result.validation.ok ? "good" : "bad"}>
                  {result.validation.ok ? "valid" : "rejected"}
                </Tag>
                <Tag tone="neutral">{result.policy.rules.length} rules</Tag>
              </div>
            }
          >
            <div className="divide-y divide-black/10">
              {result.policy.rules.map((rule) => (
                <div key={rule.priority} className="px-6 py-4">
                  <code className="font-mono text-[13px] text-black">{rule.describe}</code>
                  {rule.source_span && (
                    <p className="mt-2 text-[11px] italic text-black/60">
                      from: “{rule.source_span}”
                    </p>
                  )}
                </div>
              ))}
              {result.policy.rules.length === 0 && (
                <div className="px-6 py-10 text-center text-sm text-black/60">
                  Nothing in that text compiled to a rule.
                </div>
              )}
            </div>

            {(result.policy.warnings.length > 0 || result.validation.errors.length > 0) && (
              <div className="border-t border-black/15 p-6">
                <Label>What the compiler could not do</Label>
                <ul className="mt-3 space-y-2">
                  {result.validation.errors.map((e) => (
                    <li key={e} className="flex gap-2.5 text-[12px] leading-relaxed text-signal-loss-ink">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-signal-loss" />
                      {e}
                    </li>
                  ))}
                  {result.policy.warnings.map((w) => (
                    <li key={w} className="flex gap-2.5 text-[12px] leading-relaxed text-black/60">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-cyber" />
                      {w}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {result.injection_signals.length > 0 && (
              <div className="border-t border-black bg-signal-loss/10 p-6">
                <Label>Prompt-injection patterns detected in this text</Label>
                <div className="mt-3 flex flex-wrap gap-2">
                  {result.injection_signals.map((s) => (
                    <Tag key={s} tone="bad">{s.replace(/_/g, " ")}</Tag>
                  ))}
                </div>
                <p className="mt-3 max-w-3xl text-[12px] leading-relaxed text-black/60">
                  The text was treated as data throughout — it went into a
                  nonce-delimited block and never into the instruction channel. It
                  could not have granted a permission regardless: every effect in
                  the rule vocabulary narrows, so there is no rule shape that
                  expresses “allow”.
                </p>
              </div>
            )}
          </Panel>

          {result.run && (
            <Panel
              className="mt-6"
              title="What your policy costs"
              hint="The same cohort, solved with your rules in force. Compare before deploying."
            >
              <div className="overflow-x-auto">
                <table className="w-full min-w-[820px] text-left">
                  <thead>
                    <tr className="border-b border-black/15">
                      {["Scenario", "Incremental", "Actions", "Cost", "Net", ""].map((h) => (
                        <th key={h} className="label px-6 py-3 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-black/10">
                    {result.run.scenarios.map((s) => {
                      const mine = s.key === "policy";
                      return (
                        <tr key={s.key} className={mine ? "bg-cyber/20" : "row-hover"}>
                          <td className="px-6 py-4">
                            <span className={`text-sm font-semibold ${mine ? "text-black" : ""}`}>
                              {s.label}
                            </span>
                          </td>
                          <td className="tnum px-6 py-4 text-sm font-bold">
                            {lakhs(s.incremental_recovery_paise)}
                          </td>
                          <td className="tnum px-6 py-4 text-sm text-black/60">
                            {count(s.action_count)}
                          </td>
                          <td className="tnum px-6 py-4 text-sm text-black/60">
                            {lakhs(s.cost_paise)}
                          </td>
                          <td className="tnum px-6 py-4 text-sm">
                            {lakhs(s.net_incremental_paise)}
                          </td>
                          <td className="px-6 py-4 text-[11px] text-black/60">
                            {mine ? s.notes.join(" · ") : ""}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
