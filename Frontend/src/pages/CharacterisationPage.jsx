import { Link } from "react-router-dom";
import StateBlock from "../components/StateBlock";
import Icon from "../components/Icon";
import { useAnalysis, STATUS } from "../context/AnalysisContext";

export default function CharacterisationPage() {
  const { status, result } = useAnalysis();

  return (
    <div className="fade-in">
      <header className="page-header">
        <h1 className="page-title">Characterisation</h1>
        <p className="page-subtitle">
          Transit-signal vetting diagnostics computed entirely from the light curve of the most
          recently analyzed candidate — not a physical characterisation (radius, mass, temperature
          would require stellar parameters, which this pipeline never requests or assumes).
        </p>
      </header>

      {status !== STATUS.SUCCESS || !result ? (
        <div className="panel">
          <StateBlock
            icon={<Icon name="radar" size={32} />}
            title="Available after analysis"
            description="Upload a light curve to see vetting diagnostics here."
            action={
              <Link to="/" className="btn btn-primary" style={{ marginTop: 12 }}>
                Go to Upload
              </Link>
            }
          />
        </div>
      ) : (
        <div className="panel">
          <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginTop: 0 }}>
            {result.characterisation.note}
          </p>
          <dl className="candidate-detail">
            <div>
              <dt>BLS period</dt>
              <dd>{result.characterisation.bls_period_days.toFixed(4)} days</dd>
            </div>
            <div>
              <dt>Transit duration</dt>
              <dd>{result.characterisation.bls_duration_hours.toFixed(2)} hours</dd>
            </div>
            <div>
              <dt>Transit depth</dt>
              <dd>{result.characterisation.bls_depth_ppm.toFixed(1)} ppm</dd>
            </div>
            <div>
              <dt>Transit SNR</dt>
              <dd>{result.characterisation.bls_transit_snr.toFixed(2)}</dd>
            </div>
            <div>
              <dt>Odd/even depth ratio</dt>
              <dd>{result.characterisation.odd_even_depth_ratio.toFixed(3)}</dd>
            </div>
            <div>
              <dt>Secondary eclipse depth</dt>
              <dd>{result.characterisation.secondary_eclipse_depth_ppm.toFixed(1)} ppm</dd>
            </div>
          </dl>
        </div>
      )}
    </div>
  );
}
