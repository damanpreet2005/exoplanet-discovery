import Icon from "./Icon";

const CONFIG = {
  PASS: { icon: "check_circle", label: "Pass", className: "physics-badge pass" },
  REVIEW_REQUIRED: { icon: "warning", label: "Review Required", className: "physics-badge review" },
  NOT_EVALUATED: { icon: "do_not_disturb_on", label: "Not Evaluated", className: "physics-badge unevaluated" },
  PARTIAL: { icon: "warning", label: "Partial", className: "physics-badge review" },
};

/**
 * Status is always communicated through an icon + text label together,
 * never color alone (see PART 2.B of the physics-validation spec).
 */
export default function PhysicsStatusBadge({ status, size }) {
  const cfg = CONFIG[status] || { icon: "help", label: status || "Unknown", className: "physics-badge unevaluated" };
  return (
    <span className={`${cfg.className}${size === "lg" ? " lg" : ""}`}>
      <Icon name={cfg.icon} size={size === "lg" ? 18 : 16} filled className="physics-badge-icon" />
      {cfg.label}
    </span>
  );
}
