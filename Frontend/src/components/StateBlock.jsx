/** Shared empty / error / loading state block. Never used to fabricate data. */
export default function StateBlock({ icon, title, description, variant = "default", action }) {
  return (
    <div className={`state-block${variant === "error" ? " error" : ""}`}>
      <span className="state-icon" aria-hidden="true">
        {icon}
      </span>
      <div className="state-title">{title}</div>
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}
