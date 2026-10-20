import Icon from "./Icon";

const STEPS = [
  { n: 1, label: "Upload Light Curve" },
  { n: 2, label: "Planet & Stellar Parameters" },
  { n: 3, label: "Prediction Results" },
];

export default function StepIndicator({ current }) {
  return (
    <div className="step-indicator">
      {STEPS.map((step, i) => (
        <div key={step.n} className={`step-item${step.n === current ? " active" : ""}${step.n < current ? " done" : ""}`}>
          <span className="step-dot">
            {step.n < current ? <Icon name="check" size={14} /> : step.n}
          </span>
          <span className="step-label">
            Step {step.n} — {step.label}
          </span>
          {i < STEPS.length - 1 && <span className="step-connector" aria-hidden="true" />}
        </div>
      ))}
    </div>
  );
}
