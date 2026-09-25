import { useCallback, useEffect, useState } from "react";
import StatusPill from "../components/StatusPill";
import { getGatewayHealth, getGatewayReadiness } from "../api/client";

export default function StatusPage() {
  const [health, setHealth] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    const [h, r] = await Promise.all([getGatewayHealth(), getGatewayReadiness()]);
    setHealth(h);
    setReadiness(r);
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const gatewayState = !health ? "pending" : health.ok ? "ok" : "bad";
  const mlState =
    !readiness || !readiness.ok
      ? "bad"
      : readiness.body?.dependencies?.ml_service === "ready"
      ? "ok"
      : "bad";

  return (
    <div className="fade-in">
      <header className="page-header">
        <h1 className="page-title">System Status</h1>
        <p className="page-subtitle">
          Live status of the API gateway and its ML service dependency, read directly from the
          gateway's health/readiness endpoints.
        </p>
      </header>

      <div className="panel">
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: 6 }}>
              API Gateway (Node.js + Express)
            </div>
            <StatusPill state={loading ? "pending" : gatewayState}>
              {loading ? "Checking…" : gatewayState === "ok" ? "Alive" : "Unreachable"}
            </StatusPill>
          </div>
          <div>
            <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: 6 }}>
              ML Service (FastAPI)
            </div>
            <StatusPill state={loading ? "pending" : mlState}>
              {loading ? "Checking…" : mlState === "ok" ? "Ready" : "Unavailable"}
            </StatusPill>
          </div>
          <button className="btn btn-ghost" onClick={refresh} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>
    </div>
  );
}
