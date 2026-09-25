import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Upload & Analyze", icon: "📡", end: true },
  { to: "/manual-parameters", label: "Manual Parameters", icon: "🧮" },
  { to: "/results", label: "Results", icon: "🛰️" },
  { to: "/physics-validation", label: "Physics Validation", icon: "⚛️" },
  { to: "/characterisation", label: "Characterisation", icon: "🔭" },
  { to: "/status", label: "System Status", icon: "🩺" },
];

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true" />
        <span>Exoplanet Discovery</span>
      </div>
      <ul className="nav-list">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}
            >
              <span className="nav-icon" aria-hidden="true">
                {item.icon}
              </span>
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </aside>
  );
}
