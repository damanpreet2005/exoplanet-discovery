import { Link, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import StateBlock from "../components/StateBlock";
import PhysicsStatusBadge from "../components/PhysicsStatusBadge";
import PhysicsTestCard from "../components/PhysicsTestCard";
import Icon from "../components/Icon";
import StageNav from "../components/StageNav";
import { useAnalysis, FINAL_STATUS, PHYSICS_STATUS } from "../context/AnalysisContext";

export default function PhysicsPage() {
  const {
    result, finalStatus, finalResult, physicsStatus, physicsResult, physicsError,
    startPhysicsValidation, physicsResultIsCurrent,
  } = useAnalysis();
  const navigate = useNavigate();

  const hasCandidate = finalStatus === FINAL_STATUS.SUCCESS && Boolean(finalResult);

  useEffect(() => {
    if (!hasCandidate) {
      navigate("/results", { replace: true });
    }
  }, [hasCandidate, navigate]);

  if (!hasCandidate) {
    return null; // redirecting
  }

  const showDashboard = physicsStatus === PHYSICS_STATUS.SUCCESS && physicsResultIsCurrent && physicsResult;
  const showLoading = physicsStatus === PHYSICS_STATUS.RUNNING;
  const showError = physicsStatus === PHYSICS_STATUS.ERROR;
  const showPrompt = !showDashboard && !showLoading && !showError;

  return (
    <div className="fade-in">
      <header className="analysis-header">
        <div>
          <h1 className="page-title">Physics Validation</h1>
          <div className="analysis-meta">
            <span className="meta-chip"><Icon name="target" size={15} /> {result?.object_id || "No object ID on this session"}</span>
            {showDashboard && <PhysicsStatusBadge status={physicsResult.overall_status} />}
          </div>
          <p className="page-subtitle">
            Three independent physical-plausibility checks of the candidate's reported transit and orbital
            geometry, run separately from the Random Forest + CNN classification. A promising classifier
            prediction does not by itself mean these checks pass.
          </p>
        </div>
        <div className="analysis-actions">
          <Link to="/results" className="btn btn-ghost">
            <Icon name="arrow_back" size={16} /> Back to Results
          </Link>
        </div>
      </header>

      {showPrompt && (
        <div className="panel">
          <StateBlock
            icon={<Icon name="science" size={32} />}
            title="Run Stage 2 Physics Validation"
            description="Compute the three physics checks for this candidate's submitted parameters."
            action={
              <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={() => startPhysicsValidation()}>
                <Icon name="science" size={16} /> Start Physics Validation
              </button>
            }
          />
        </div>
      )}

      {showLoading && (
        <div className="panel">
          <StateBlock
            icon={<Icon name="progress_activity" size={32} className="icon-spin" />}
            title="Running physics validation…"
            description="Computing the three checks against the submitted candidate parameters."
          />
        </div>
      )}

      {showError && (
        <div className="panel">
          <StateBlock
            variant="error"
            icon={<Icon name="error" size={32} />}
            title={physicsError?.code || "Physics validation failed"}
            description={physicsError?.message || "Could not reach the validation service."}
            action={
              <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={() => startPhysicsValidation(true)}>
                <Icon name="refresh" size={16} /> Retry
              </button>
            }
          />
        </div>
      )}

      {showDashboard && (
        <>
          <div className="summary-row">
            <div className="summary-tile">
              <div className="value" style={{ color: "var(--success)" }}>{physicsResult.summary.tests_passed}</div>
              <div className="label">Tests Passed</div>
            </div>
            <div className="summary-tile">
              <div className="value" style={{ color: "var(--warning)" }}>{physicsResult.summary.tests_review_required}</div>
              <div className="label">Review Required</div>
            </div>
            <div className="summary-tile">
              <div className="value" style={{ color: "var(--text-muted)" }}>{physicsResult.summary.tests_not_evaluated}</div>
              <div className="label">Not Evaluated</div>
            </div>
            <div className="summary-tile" style={{ flex: "2 1 260px" }}>
              <div className="value" style={{ fontSize: "1rem" }}>{physicsResult.summary.message}</div>
              <div className="label">Overall Summary</div>
            </div>
          </div>

          <div className="physics-stages">
            {physicsResult.tests.map((test) => (
              <PhysicsTestCard key={test.test_id} test={test} />
            ))}
          </div>

          <div className="panel">
            <h3 style={{ marginTop: 0 }}>Issues & Recommendations</h3>
            {physicsResult.issues.length === 0 ? (
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                No physical inconsistencies or missing-data issues were found across the three checks.
              </p>
            ) : (
              <>
                <ul className="physics-issues-list">
                  {physicsResult.issues.map((issue, i) => <li key={i}>{issue}</li>)}
                </ul>
                <h4 style={{ marginBottom: 8 }}>Suggested Next Steps</h4>
                <ul className="physics-issues-list">
                  {physicsResult.recommendations.map((rec, i) => <li key={i}>{rec}</li>)}
                </ul>
              </>
            )}
          </div>

          <p style={{ color: "var(--text-muted)", fontSize: "0.78rem", textAlign: "center" }}>
            Generated {new Date(physicsResult.generated_at).toLocaleString()}
          </p>

          <div style={{ display: "flex", justifyContent: "center", gap: 12, marginTop: 8, flexWrap: "wrap" }}>
            <button className="btn btn-ghost" onClick={() => startPhysicsValidation(true)}>
              <Icon name="refresh" size={16} /> Re-run Validation
            </button>
          </div>
        </>
      )}

      <StageNav current="/physics-validation" />
    </div>
  );
}
