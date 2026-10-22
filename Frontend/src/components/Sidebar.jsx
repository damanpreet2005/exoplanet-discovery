import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import Logo from "./Logo";
import Icon from "./Icon";

// A floating, collapsible navigation dock (not an edge-attached sidebar --
// see .dock in index.css). Collapsed to icons-only at rest; hovering (or,
// for keyboard users, focusing into it) expands it to reveal labels via a
// pure-CSS width transition (:hover / :has(:focus-visible) on .dock -- keyboard
// focus expands it, the focus left by a mouse click does not), so no
// JS-driven expand/collapse state is needed for desktop/keyboard. Touch
// devices (no hover) get a permanently-expanded dock instead of a fragile
// tap-to-toggle gesture -- see the `(hover: none)` media query in index.css.
//
// `title`/`aria-label` double as the "subtle tooltip" requirement: they
// identify each icon immediately on hover/focus, before or independent of
// the dock's own width animation finishing. Icons are Google Material
// Symbols Rounded (see Icon.jsx) chosen for what each destination does --
// never decorative emoji.
//
// Narrow screens (<= 768px, see index.css) have no room for a side dock, so
// the same panel becomes a floating top bar whose link list is toggled by
// the menu button. `open` only matters there: the toggle is hidden and the
// list always shown at wider widths. It closes on navigation, Escape, or a
// tap outside the panel.
const WORKFLOW_ITEMS = [
  { to: "/", label: "Upload & Analyze", icon: "satellite_alt", end: true },
  { to: "/manual-parameters", label: "Manual Parameters", icon: "tune" },
  { to: "/results", label: "Detection & Prediction", icon: "insights" },
  { to: "/physics-validation", label: "Physics Validation", icon: "science" },
  { to: "/characterisation", label: "Planet Characterization", icon: "radar" },
  { to: "/report", label: "Discovery Report", icon: "summarize" },
];

const SYSTEM_ITEMS = [{ to: "/status", label: "System Status", icon: "monitor_heart" }];

function DockLink({ to, label, icon, end }) {
  return (
    <li>
      <NavLink
        to={to}
        end={end}
        title={label}
        aria-label={label}
        className={({ isActive }) => "dock-link" + (isActive ? " active" : "")}
      >
        <Icon name={icon} size={20} className="dock-icon" />
        <span className="dock-label">{label}</span>
      </NavLink>
    </li>
  );
}

export default function Sidebar() {
  const [open, setOpen] = useState(false);
  const dockRef = useRef(null);
  const location = useLocation();

  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!open) return undefined;
    function handleKeyDown(event) {
      if (event.key === "Escape") setOpen(false);
    }
    function handlePointerDown(event) {
      if (dockRef.current && !dockRef.current.contains(event.target)) setOpen(false);
    }
    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [open]);

  return (
    <aside className="dock" aria-label="Primary navigation" data-open={open} ref={dockRef}>
      <div className="dock-panel">
        <div className="dock-brand" title="Exo Discovery">
          <span className="dock-brand-mark">
            <Logo size={26} />
          </span>
          <span className="dock-label dock-brand-label">Exo Discovery</span>
          <button
            type="button"
            className="dock-toggle"
            aria-expanded={open}
            aria-controls="dock-nav"
            aria-label={open ? "Close navigation menu" : "Open navigation menu"}
            onClick={() => setOpen((value) => !value)}
          >
            <Icon name={open ? "close" : "menu"} size={22} />
          </button>
        </div>

        <nav className="dock-nav" id="dock-nav">
          <ul className="dock-list">
            {WORKFLOW_ITEMS.map((item) => (
              <DockLink key={item.to} {...item} />
            ))}
          </ul>

          <div className="dock-divider" role="separator" aria-hidden="true" />

          <ul className="dock-list">
            {SYSTEM_ITEMS.map((item) => (
              <DockLink key={item.to} {...item} />
            ))}
          </ul>
        </nav>
      </div>
    </aside>
  );
}
