import { useState } from "react";
import { ChartFrame, ChartUnavailable, LegendItem } from "./ChartFrame";

const S = 320;
const C = S / 2;

function val(p) {
  return p && p.status === "computed" && Number.isFinite(p.value) ? p.value : null;
}

/**
 * Illustrative top-down view of the orbit. The orbit's semi-major axis and
 * eccentricity, and the habitable-zone boundaries, are drawn to a common
 * linear AU scale from the engine's computed values; the star and planet
 * markers are NOT to scale and the orbit's orientation is arbitrary. It is
 * a diagram, never an image of the system.
 */
export default function OrbitSchematic({ parameters }) {
  const a = val(parameters?.semi_major_axis);
  const e = val(parameters?.eccentricity) ?? 0;
  const hz = {
    ci: val(parameters?.hz_inner_conservative),
    co: val(parameters?.hz_outer_conservative),
    oi: val(parameters?.hz_inner_optimistic),
    oo: val(parameters?.hz_outer_optimistic),
  };
  const hasHz = hz.ci && hz.co;
  const [showHz, setShowHz] = useState(true);

  if (!a) {
    return (
      <ChartUnavailable
        title="Orbit diagram unavailable"
        reason="Needs a semi-major axis, which requires the orbital period and a stellar mass."
      />
    );
  }

  const apo = a * (1 + e);
  const extentAu = (showHz && hasHz ? Math.max(apo, hz.oo || hz.co) : apo) * 1.1;
  const k = (C - 12) / extentAu;
  const rx = a * k;
  const ry = a * Math.sqrt(1 - e * e) * k;
  const cx = C - a * e * k; // star sits at a focus
  const tiny = rx < 14;

  return (
    <ChartFrame
      testId="orbit-schematic"
      title="Orbit schematic (illustrative)"
      legend={
        <>
          <LegendItem kind="key-line">Planet orbit</LegendItem>
          {hasHz && showHz && <LegendItem kind="key-band">Habitable zone (conservative / optimistic)</LegendItem>}
        </>
      }
      caption={`Illustrative diagram, not an observed image. Orbit (a = ${parameters.semi_major_axis.display} AU${e ? `, e = ${e}` : ", circular"}) and habitable-zone radii share one linear AU scale; star and planet markers are not to scale and the orientation is arbitrary.`}
    >
      {hasHz && (
        <div className="seg-toggle" role="group" aria-label="Diagram scale">
          <button type="button" className={showHz ? "active" : ""} aria-pressed={showHz} onClick={() => setShowHz(true)}>Include habitable zone</button>
          <button type="button" className={!showHz ? "active" : ""} aria-pressed={!showHz} onClick={() => setShowHz(false)}>Zoom to orbit</button>
        </div>
      )}
      <svg viewBox={`0 0 ${S} ${S}`} className="orbit-svg" role="img" aria-label="Illustrative orbit diagram">
        {showHz && hasHz && (
          <>
            {hz.oi && hz.oo && <circle className="orbit-hz-opt" cx={C} cy={C} r={((hz.oi + hz.oo) / 2) * k} strokeWidth={(hz.oo - hz.oi) * k} />}
            <circle className="orbit-hz" cx={C} cy={C} r={((hz.ci + hz.co) / 2) * k} strokeWidth={(hz.co - hz.ci) * k} />
          </>
        )}
        <ellipse className="orbit-path" cx={cx} cy={C} rx={Math.max(rx, 1)} ry={Math.max(ry, 1)} />
        <circle className="orbit-star" cx={C} cy={C} r={7} />
        <circle className="orbit-planet" cx={cx + rx} cy={C} r={4} />
        <line className="orbit-scale" x1={C} x2={C + extentAu * 0.5 * k} y1={S - 14} y2={S - 14} />
        <text className="chart-tick" x={C + extentAu * 0.25 * k} y={S - 20} textAnchor="middle">
          {Number((extentAu * 0.5).toPrecision(2))} AU
        </text>
      </svg>
      {tiny && showHz && <p className="chart-caption">At this scale the orbit lies deep inside the habitable zone — use “Zoom to orbit” to see it.</p>}
    </ChartFrame>
  );
}
