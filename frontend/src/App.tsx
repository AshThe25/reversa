import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { Shell } from "./components/Shell";
import { ErrorNote, Spinner } from "./components/primitives";
import { openSession, preferredRole, signOut } from "./lib/api";
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
import { SignIn } from "./pages/SignIn";
import { Policies } from "./pages/Policies";
import { Portfolio } from "./pages/Portfolio";

/**
 * Auth gate.
 *
 * Nothing renders until there is a session, and the two roles differ in the
 * only way that matters: a guest session carries read + simulate and can never
 * execute, which is enforced server-side.
 *
 * A returning guest is signed straight back in rather than shown the door
 * twice — a demo session is unauthenticated by design, so re-minting one is
 * free and costs nothing in safety. An operator session is deliberately NOT
 * restored; that one can move money, so it costs the access code every time.
 */
export function App() {
  const [ready, setReady] = useState(false);
  const [checking, setChecking] = useState(true);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    if (preferredRole() !== "demo") {
      setChecking(false);
      return;
    }
    openSession()
      .then(() => setReady(true))
      .catch(() =>
        setFailed(
          "Could not reach the Reversa API. Start it with: uvicorn reversa.main:app --port 8000",
        ),
      )
      .finally(() => setChecking(false));
  }, []);

  if (failed) {
    return (
      <div className="ambient grid min-h-full place-items-center p-8">
        <div className="above max-w-lg">
          <ErrorNote message={failed} />
        </div>
      </div>
    );
  }

  if (checking) {
    return (
      <div className="ambient grid min-h-full place-items-center">
        <Spinner label="Restoring session" />
      </div>
    );
  }

  if (!ready) {
    return <SignIn onAuthenticated={() => setReady(true)} />;
  }

  return (
    <TourProvider>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route
          path="*"
          element={
            <Shell onSignOut={() => { signOut(); setReady(false); }}>
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
