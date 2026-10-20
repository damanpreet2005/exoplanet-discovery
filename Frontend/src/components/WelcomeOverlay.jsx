import { useEffect, useState } from "react";
import Logo from "./Logo";

// Pure visual launch overlay -- it never gates or delays any real work.
// The app underneath mounts and starts its own data/effects immediately and
// independently; this is a fixed-position layer drawn on top for ~2s, then
// it fades out and removes itself. See App.jsx: `showWelcome` only controls
// whether this component is rendered, nothing else.
const VISIBLE_MS = 1800; // time fully visible before the fade-out begins
const FADE_MS = 400; // fade-out duration
// Total on-screen time: ~2.2s, within the requested 1.5-2.5s window.

export default function WelcomeOverlay({ onDone }) {
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const startLeave = setTimeout(() => setLeaving(true), VISIBLE_MS);
    const finish = setTimeout(onDone, VISIBLE_MS + FADE_MS);
    return () => {
      clearTimeout(startLeave);
      clearTimeout(finish);
    };
  }, [onDone]);

  return (
    <div className={"welcome-overlay" + (leaving ? " is-leaving" : "")} role="status" aria-live="polite">
      <div className="welcome-content">
        <span className="welcome-mark">
          <Logo size={44} />
        </span>
        <h1 className="welcome-title">Welcome to Exo Discovery</h1>
        <p className="welcome-subtitle">A scientific environment for candidate discovery and validation</p>
      </div>
    </div>
  );
}
