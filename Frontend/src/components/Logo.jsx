import { useId } from "react";

/**
 * The Exo Discovery mark: a host star at one focus of an elliptical orbital
 * path, with a single orbiting exoplanet further along that path -- the
 * minimal visual grammar of a Kepler orbit diagram. The star is
 * deliberately off-center (at the ellipse's focus, as a real orbit's
 * primary body is -- not at its geometric center) rather than concentric
 * with the ring: a centered circle-in-ellipse reads as an eye at small
 * sizes, which an off-center focus avoids while also being the
 * astronomically correct placement.
 *
 * Inline SVG (not an <img> to a static file) so it can pick up the live
 * --color-accent-* design tokens and always match the current theme,
 * including at the small sizes used in the collapsed navigation dock.
 */
export default function Logo({ size = 28, className = "" }) {
  const uid = useId();
  const coreGradientId = `exo-logo-core-${uid}`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <radialGradient id={coreGradientId} cx="35%" cy="35%" r="70%">
          <stop offset="0%" stopColor="var(--color-accent-primary, #62c3b5)" />
          <stop offset="100%" stopColor="var(--color-accent-secondary, #8bafd9)" />
        </radialGradient>
      </defs>
      {/* Orbital path */}
      <ellipse
        cx="16"
        cy="16"
        rx="13"
        ry="5.6"
        transform="rotate(-18 16 16)"
        stroke="var(--color-accent-secondary, #8bafd9)"
        strokeWidth="1.3"
        strokeOpacity="0.78"
      />
      {/* Host star, at the ellipse's focus */}
      <circle cx="4.8" cy="19.6" r="4.2" fill={`url(#${coreGradientId})`} />
      {/* Orbiting exoplanet, elsewhere along the path */}
      <circle cx="14.3" cy="10.7" r="2.2" fill="var(--color-accent-primary, #62c3b5)" />
    </svg>
  );
}
