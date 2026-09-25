import ComingSoonPanel from "../components/ComingSoonPanel";
import { useAnalysis } from "../context/AnalysisContext";

const FALLBACK_MESSAGE = "Physics validation module — coming in a future implementation stage.";

export default function PhysicsPage() {
  const { result } = useAnalysis();
  return (
    <div className="fade-in">
      <header className="page-header">
        <h1 className="page-title">Physics Validation</h1>
        <p className="page-subtitle">
          Once implemented, this stage will check candidates against physical plausibility
          constraints before they are treated as validated. The ML classifier alone does not
          prove physical validity.
        </p>
      </header>
      <div className="panel">
        <ComingSoonPanel
          title="Physics Validation"
          message={result?.physics_validation?.message || FALLBACK_MESSAGE}
        />
      </div>
    </div>
  );
}
