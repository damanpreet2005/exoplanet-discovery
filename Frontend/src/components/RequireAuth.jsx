import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import Icon from "./Icon";
import StateBlock from "./StateBlock";

/**
 * Client-side gate for private routes. This only decides what to render --
 * the real protection is the backend, which rejects unauthenticated calls to
 * every private endpoint regardless of what the browser shows.
 */
export default function RequireAuth({ children }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="panel">
        <StateBlock icon={<Icon name="progress_activity" size={32} className="icon-spin" />} title="Restoring your session…" />
      </div>
    );
  }
  if (status !== "authenticated") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return children;
}
