import { Link } from "react-router-dom";
import Icon from "./Icon";

// The four analytical stages, in workflow order. Upload and manual entry
// are part of the journey but are inputs, not analysis stages.
export const STAGES = [
  { to: "/results", label: "Transit Detection & ML Prediction", short: "Detection & Prediction", icon: "insights" },
  { to: "/physics-validation", label: "Physics Validation", short: "Physics Validation", icon: "science" },
  { to: "/characterisation", label: "Planet Characterization", short: "Characterization", icon: "radar" },
  { to: "/report", label: "Final Discovery Report", short: "Discovery Report", icon: "summarize" },
];

/**
 * Previous / next stage links shown at the foot of every analytical page.
 * Not a numbered stepper: it only offers the neighbouring stages by name.
 */
export default function StageNav({ current }) {
  const i = STAGES.findIndex((s) => s.to === current);
  const prev = i > 0 ? STAGES[i - 1] : null;
  const next = i >= 0 && i < STAGES.length - 1 ? STAGES[i + 1] : null;
  return (
    <nav className="stage-nav" aria-label="Analysis stages">
      {prev ? (
        <Link to={prev.to} className="stage-nav-link prev">
          <Icon name="arrow_back" size={18} />
          <span>
            <span className="stage-nav-kicker">Previous</span>
            <span className="stage-nav-label">{prev.label}</span>
          </span>
        </Link>
      ) : <span />}
      {next && (
        <Link to={next.to} className="stage-nav-link next">
          <span>
            <span className="stage-nav-kicker">Next</span>
            <span className="stage-nav-label">{next.label}</span>
          </span>
          <Icon name="arrow_forward" size={18} />
        </Link>
      )}
    </nav>
  );
}
