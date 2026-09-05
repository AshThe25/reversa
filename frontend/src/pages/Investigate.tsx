import { Navigate } from "react-router-dom";

import { Spinner } from "../components/primitives";
import { api } from "../lib/api";
import { useAsync } from "../hooks/useAsync";

/**
 * A stable address for "the incident worth looking at".
 *
 * The investigation lives at /incidents/:id, which the walkthrough cannot link
 * to because the id changes every time the world is reseeded. This resolves the
 * worst incident by exposure and hands off, so the tour has one fixed path and
 * the agent's reasoning is something a judge is walked through rather than
 * something they have to go hunting for.
 */
export function Investigate() {
  const { data, loading, error } = useAsync(() => api.incidents(), []);

  if (loading) {
    return (
      <div className="mx-auto max-w-[1600px] px-6 py-16">
        <Spinner label="Finding the worst incident" />
      </div>
    );
  }

  if (error || !data || data.length === 0) {
    return <Navigate to="/incidents" replace />;
  }

  const worst = data.reduce((a, b) =>
    b.revenue_exposed_paise > a.revenue_exposed_paise ? b : a,
  );
  return <Navigate to={`/incidents/${worst.id}`} replace />;
}
