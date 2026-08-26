import { useNavigate } from "react-router-dom";

import {
  Button, ErrorNote, Label, Panel, Severity, Skeleton, Tag,
} from "../components/primitives";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { count, lakhs, pct, sci, timeIST } from "../lib/format";

export function Incidents() {
  const navigate = useNavigate();
  const { data, loading, error, reload } = useAsync(() => api.incidents(), []);

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Detection</Label>
          <h1 className="mt-2 text-4xl font-bold tracking-tight">Incidents</h1>
          <p className="mt-3 max-w-3xl text-sm leading-relaxed text-white/40">
            Each row is a slice of the payment stream whose success rate broke against
            a per-hour, seasonality-aware baseline — significant after
            Benjamini-Hochberg correction across every slice and window tested that
            tick, and large enough to be worth an operator's attention.
          </p>
        </div>
        <Button variant="ghost" onClick={reload}>
          Re-scan
        </Button>
      </div>

      {error && (
        <div className="mt-6">
          <ErrorNote message={error.message} requestId={error.requestId} />
        </div>
      )}

      <Panel className="mt-8">
        {loading && <Skeleton rows={6} />}
        {data && data.length === 0 && (
          <div className="px-6 py-16 text-center text-sm text-white/40">
            No slice cleared both the significance and the effect-size floor.
          </div>
        )}
        {data && data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1000px] text-left">
              <thead>
                <tr className="border-b border-white/[0.06]">
                  {["Severity", "Slice", "Window (IST)", "Success rate", "Payments", "Revenue exposed", "q-value", ""].map((h) => (
                    <th key={h} className="label px-6 py-3 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {data.map((inc) => (
                  <tr key={inc.id} className="row-hover">
                    <td className="px-6 py-4">
                      <Severity level={inc.severity} />
                    </td>
                    <td className="px-6 py-4">
                      <p className="text-sm font-semibold">{inc.slice}</p>
                      <p className="mt-0.5 text-[11px] text-white/30">{inc.label}</p>
                    </td>
                    <td className="tnum px-6 py-4 text-sm text-white/60">
                      {timeIST(inc.window_start)}–{timeIST(inc.window_end)}
                    </td>
                    <td className="px-6 py-4">
                      <span className="tnum text-sm">
                        <span className="text-white/40">{pct(inc.baseline_success_rate)}</span>
                        <span className="mx-1.5 text-white/20">→</span>
                        <span className="font-semibold text-signal-loss">
                          {pct(inc.observed_success_rate)}
                        </span>
                      </span>
                    </td>
                    <td className="tnum px-6 py-4 text-sm text-white/60">
                      {count(inc.affected_payment_count)}
                    </td>
                    <td className="tnum px-6 py-4 text-sm font-bold text-signal-loss">
                      {lakhs(inc.revenue_exposed_paise)}
                    </td>
                    <td className="tnum px-6 py-4 font-mono text-[11px] text-white/35">
                      {sci(inc.q_value)}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <Button variant="ghost" onClick={() => navigate(`/incidents/${inc.id}`)}>
                        Investigate →
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <div className="mt-6 flex flex-wrap gap-2">
        <Tag tone="neutral">Beta-binomial tail, dispersion fitted per slice</Tag>
        <Tag tone="neutral">Scan statistic over 5 / 15 / 45 minute windows</Tag>
        <Tag tone="neutral">FDR-controlled at q ≤ 0.05</Tag>
        <Tag tone="neutral">Child slices rolled up to the scope that explains them</Tag>
      </div>
    </div>
  );
}
