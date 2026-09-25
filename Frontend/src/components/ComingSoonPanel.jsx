/**
 * Explicit "not implemented" panel. The message is always sourced from the
 * backend's own response (physics_validation.message / characterisation.message)
 * rather than hardcoded here, so the UI never claims more than the system
 * actually implements.
 */
export default function ComingSoonPanel({ title, message }) {
  return (
    <div className="coming-soon">
      <span className="badge">Not yet implemented</span>
      <h3 style={{ margin: "0 0 8px", color: "var(--text-primary)" }}>{title}</h3>
      <p style={{ margin: 0 }}>{message}</p>
    </div>
  );
}
