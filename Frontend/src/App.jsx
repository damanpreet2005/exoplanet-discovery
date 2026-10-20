import { useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Starfield from "./components/Starfield";
import WelcomeOverlay from "./components/WelcomeOverlay";
import { AnalysisProvider } from "./context/AnalysisContext";
import UploadPage from "./pages/UploadPage";
import ManualParamsPage from "./pages/ManualParamsPage";
import ResultsPage from "./pages/ResultsPage";
import PhysicsPage from "./pages/PhysicsPage";
import CharacterisationPage from "./pages/CharacterisationPage";
import StatusPage from "./pages/StatusPage";

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
    <AnalysisProvider>
      <BrowserRouter>
        <div className="app-shell">
          <Starfield />
          <Sidebar />
          <main className="app-main">
            <Routes>
              <Route path="/" element={<UploadPage />} />
              <Route path="/manual-parameters" element={<ManualParamsPage />} />
              <Route path="/results" element={<ResultsPage />} />
              <Route path="/physics-validation" element={<PhysicsPage />} />
              <Route path="/characterisation" element={<CharacterisationPage />} />
              <Route path="/status" element={<StatusPage />} />
            </Routes>
          </main>
          {showWelcome && <WelcomeOverlay onDone={() => setShowWelcome(false)} />}
        </div>
      </BrowserRouter>
    </AnalysisProvider>
  );
}
