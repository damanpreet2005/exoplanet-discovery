import { BrowserRouter, Routes, Route } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Starfield from "./components/Starfield";
import { AnalysisProvider } from "./context/AnalysisContext";
import UploadPage from "./pages/UploadPage";
import ManualParamsPage from "./pages/ManualParamsPage";
import ResultsPage from "./pages/ResultsPage";
import PhysicsPage from "./pages/PhysicsPage";
import CharacterisationPage from "./pages/CharacterisationPage";
import StatusPage from "./pages/StatusPage";

export default function App() {
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
        </div>
      </BrowserRouter>
    </AnalysisProvider>
  );
}
