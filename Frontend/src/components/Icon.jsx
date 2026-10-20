/**
 * Thin wrapper around Google Material Symbols Rounded (loaded via Google
 * Fonts in index.html -- see .material-symbols-rounded in index.css for the
 * required font-variation-settings). Centralizing it here is what keeps
 * icon sizing, weight, and alignment consistent everywhere instead of each
 * call site repeating font-variation-settings by hand.
 *
 * Decorative by default (aria-hidden, since the adjacent text already
 * labels it). Pass `label` for an icon-only control (e.g. an icon-only
 * button with no visible text) so it's announced to assistive tech.
 */
export default function Icon({ name, size = 20, filled = false, label, className = "", style }) {
  return (
    <span
      className={`material-symbols-rounded${filled ? " icon-filled" : ""}${className ? ` ${className}` : ""}`}
      style={{ fontSize: size, ...style }}
      aria-hidden={label ? undefined : "true"}
      role={label ? "img" : undefined}
      aria-label={label}
    >
      {name}
    </span>
  );
}
