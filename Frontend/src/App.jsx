import { useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Starfield from "./components/Starfield";
import WelcomeOverlay from "./components/WelcomeOverlay";
import RequireAuth from "./components/RequireAuth";
import AnalysisSessionGuard from "./components/AnalysisSessionGuard";
import { AnalysisProvider } from "./context/AnalysisContext";
import { AuthProvider } from "./context/AuthContext";
import UploadPage from "./pages/UploadPage";
import ManualParamsPage from "./pages/ManualParamsPage";
import ResultsPage from "./pages/ResultsPage";
import PhysicsPage from "./pages/PhysicsPage";
import CharacterisationPage from "./pages/CharacterisationPage";
import DiscoveryReportPage from "./pages/DiscoveryReportPage";
import StatusPage from "./pages/StatusPage";
import AuthPage from "./pages/AuthPage";
import AccountPage from "./pages/AccountPage";
import HistoryPage from "./pages/HistoryPage";

function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}

export default function App() {
  // Shown on every load/refresh (not just first-ever visit), per spec --
  // skipped entirely for reduced-motion users rather than shown instantly,
  // since an unskippable timed overlay is itself a motion-sensitive UX
  // regardless of whether it animates. This only controls whether the
  // overlay renders; it never gates the rest of the app's mount, routing,
  // or data fetching below -- those proceed immediately either way.
  // Also skipped under the test runner (Vitest sets MODE to "test") so the
  // ~2s launch timer never fires after a test has already unmounted --
  // WelcomeOverlay itself is covered directly by its own test instead.
  const [showWelcome, setShowWelcome] = useState(
    () => !prefersReducedMotion() && import.meta.env.MODE !== "test"
  );

  return (
    <AuthProvider>
      <AnalysisProvider>
        <AnalysisSessionGuard />
        <BrowserRouter>
          <div className="app-shell">
            <Starfield />
            <Sidebar />
            <main className="app-main">
              <Routes>
                {/* The analysis workflow requires a signed-in user (the gateway
                    enforces the same rule on its analysis endpoints). */}
                <Route path="/" element={<RequireAuth><UploadPage /></RequireAuth>} />
                <Route path="/manual-parameters" element={<RequireAuth><ManualParamsPage /></RequireAuth>} />
                <Route path="/results" element={<RequireAuth><ResultsPage /></RequireAuth>} />
                <Route path="/physics-validation" element={<RequireAuth><PhysicsPage /></RequireAuth>} />
                <Route path="/characterisation" element={<RequireAuth><CharacterisationPage /></RequireAuth>} />
                <Route path="/report" element={<RequireAuth><DiscoveryReportPage /></RequireAuth>} />
                <Route path="/history" element={<RequireAuth><HistoryPage /></RequireAuth>} />
                {/* Public: system status and the account pages. */}
                <Route path="/status" element={<StatusPage />} />
                <Route path="/login" element={<AuthPage mode="login" />} />
                <Route path="/signup" element={<AuthPage mode="signup" />} />
                <Route
                  path="/account"
                  element={
                    <RequireAuth>
                      <AccountPage />
                    </RequireAuth>
                  }
                />
              </Routes>
            </main>
            {showWelcome && <WelcomeOverlay onDone={() => setShowWelcome(false)} />}
          </div>
        </BrowserRouter>
      </AnalysisProvider>
    </AuthProvider>
  );
}
