import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Avatar from "../components/Avatar";
import Icon from "../components/Icon";
import StateBlock from "../components/StateBlock";
import StatusPill from "../components/StatusPill";
import { useAuth } from "../context/AuthContext";

function formatDate(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

/**
 * User Dashboard (phase 1): profile details and logout only. The profile is
 * fetched from the protected GET /api/v1/auth/me, which identifies the user
 * from the verified access token -- this page never sends a user id.
 */
export default function AccountPage() {
  const { loadProfile, logout } = useAuth();
  const navigate = useNavigate();
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState(null);
  const [loggingOut, setLoggingOut] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setProfile(await loadProfile());
    } catch (err) {
      setError(err.message || "Could not load your profile.");
    }
  }, [loadProfile]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleLogout() {
    setLoggingOut(true);
    await logout();
    navigate("/login", { replace: true });
  }

  const logoutButton = (
    <button type="button" className="btn btn-ghost account-logout" onClick={handleLogout} disabled={loggingOut}>
      <Icon name="logout" size={18} />
      {loggingOut ? "Logging out…" : "Log out"}
    </button>
  );

  return (
    <div className="fade-in">
      <header className="page-header analysis-header">
        <div>
          <h1 className="page-title">User Dashboard</h1>
          <p className="page-subtitle">Your Exo Discovery account details.</p>
        </div>
        <div className="analysis-actions">{logoutButton}</div>
      </header>

      {error && !profile && (
        <div className="panel">
          <StateBlock
            variant="error"
            icon={<Icon name="error" size={32} />}
            title="Could not load your profile"
            description={error}
            action={
              <button type="button" className="btn btn-ghost" onClick={load}>
                Try again
              </button>
            }
          />
        </div>
      )}

      {!error && !profile && (
        <div className="panel">
          <StateBlock icon={<Icon name="progress_activity" size={32} className="icon-spin" />} title="Loading your profile…" />
        </div>
      )}

      {profile && (
        <div className="account-grid">
          <section className="ws-panel account-profile" aria-labelledby="account-profile-heading" id="profile">
            <Avatar user={profile} size={88} className="account-avatar" />
            <div className="account-identity">
              <h2 id="account-profile-heading" className="account-name">
                {profile.name}
              </h2>
              <p className="account-username">@{profile.username}</p>
            </div>
          </section>

          <section className="ws-panel" aria-labelledby="account-details-heading">
            <div className="ws-panel-head">
              <h3 id="account-details-heading">
                <Icon name="badge" size={20} /> Account details
              </h3>
            </div>
            <dl className="kv-list">
              <div>
                <dt>Full name</dt>
                <dd>{profile.name}</dd>
              </div>
              <div>
                <dt>Username</dt>
                <dd>@{profile.username}</dd>
              </div>
              <div>
                <dt>Email address</dt>
                <dd>{profile.email}</dd>
              </div>
              <div>
                <dt>Member since</dt>
                <dd>{formatDate(profile.created_at)}</dd>
              </div>
              <div>
                <dt>Account status</dt>
                <dd>
                  <StatusPill state={profile.is_active ? "ok" : "bad"}>{profile.is_active ? "Active" : "Inactive"}</StatusPill>
                </dd>
              </div>
            </dl>
          </section>
        </div>
      )}
    </div>
  );
}
