import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { Shell } from "./components/Shell";
import { ErrorNote, Spinner } from "./components/primitives";
import { openSession } from "./lib/api";
import { TourProvider } from "./lib/tour";
import { Audit } from "./pages/Audit";
import { Autopsy } from "./pages/Autopsy";
import { CommandCentre } from "./pages/CommandCentre";
import { Evaluation } from "./pages/Evaluation";
import { Experiments } from "./pages/Experiments";
import { Futures } from "./pages/Futures";
import { IncidentDetail } from "./pages/IncidentDetail";
import { Incidents } from "./pages/Incidents";
import { Landing } from "./pages/Landing";
import { Policies } from "./pages/Policies";
import { Portfolio } from "./pages/Portfolio";

/**
 * A session is opened before anything renders.
 *
 * Every route except the landing page needs one, and the demo session is
 * deliberately capped at read+simulate - so a visitor can drive the entire
 * product and still has no path to executing a strategy. That is enforced
 * server-side; this just gets the token.
 */
export function App() {
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    openSession()
      .then(() => setReady(true))
      .catch(() =>
        setFailed(
          "Could not reach the Reversa API. Start it with: uvicorn reversa.main:app --port 8000",
        ),
      );
  }, []);

  if (failed) {
    return (
      <div className="grid min-h-full place-items-center p-8">
        <div className="max-w-lg">
          <ErrorNote message={failed} />
        </div>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="grid min-h-full place-items-center">
        <Spinner label="Opening session" />
      </div>
    );
  }

  return (
    <TourProvider>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route
          path="*"
          element={
            <Shell>
              <Routes>
                <Route path="/command" element={<CommandCentre />} />
                <Route path="/incidents" element={<Incidents />} />
                <Route path="/incidents/:id" element={<IncidentDetail />} />
                <Route path="/futures" element={<Futures />} />
                <Route path="/portfolio" element={<Portfolio />} />
                <Route path="/experiments" element={<Experiments />} />
                <Route path="/autopsy" element={<Autopsy />} />
                <Route path="/policies" element={<Policies />} />
                <Route path="/audit" element={<Audit />} />
                <Route path="/evaluation" element={<Evaluation />} />
                <Route path="*" element={<Navigate to="/command" replace />} />
              </Routes>
            </Shell>
          }
        />
      </Routes>
    </TourProvider>
  );
}
