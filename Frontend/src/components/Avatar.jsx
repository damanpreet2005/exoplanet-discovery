import { useState } from "react";

function initialsFor(name, username) {
  const parts = (name || "").trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (username || "?").slice(0, 2).toUpperCase();
}

// Only http(s) or same-origin paths -- never javascript:/data: URLs.
function isSafeImageUrl(url) {
  if (typeof url !== "string" || !url) return false;
  if (url.startsWith("/") && !url.startsWith("//")) return true;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

/** Profile picture, falling back to an initials avatar when absent or broken. */
export default function Avatar({ user, size = 40, className = "" }) {
  const [failed, setFailed] = useState(false);
  const src = user?.profile_picture;
  const style = { width: size, height: size, fontSize: Math.round(size * 0.4) };

  if (isSafeImageUrl(src) && !failed) {
    return (
      <img
        className={`avatar${className ? ` ${className}` : ""}`}
        src={src}
        alt=""
        style={style}
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <span className={`avatar avatar-initials${className ? ` ${className}` : ""}`} style={style} aria-hidden="true">
      {initialsFor(user?.name, user?.username)}
    </span>
  );
}
