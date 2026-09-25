export default function StatusPill({ state, children }) {
  // state: "ok" | "bad" | "pending"
  return (
    <span className={`status-pill ${state}`}>
      <span className="status-dot" />
      {children}
    </span>
  );
}
