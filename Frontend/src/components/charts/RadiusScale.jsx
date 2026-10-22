import { ChartFrame, ChartUnavailable, LegendItem } from "./ChartFrame";
import { scaleLog } from "./chartUtils";

// Solar-system reference radii in Earth radii (mean radii, IAU/NASA fact
// sheets) -- fixed physical references, not classification thresholds.
const REFERENCES = [
  { name: "Earth", r: 1.0 },
  { name: "Neptune", r: 3.865 },
  { name: "Jupiter", r: 10.97 },
];

const W = 380;
const H = 100;
const L = 20;
const R = 20;

/** The planet's radius (with its 68% interval) on a log axis next to solar-system references. */
export default function RadiusScale({ radius }) {
  if (!radius || radius.status !== "computed" || !(radius.value > 0)) {
    return (
      <ChartUnavailable
        title="Radius comparison unavailable"
        reason="Needs a computed planet radius, which requires the fitted radius ratio and a stellar radius."
      />
    );
  }
  const lo = radius.uncertainty ? radius.value - radius.uncertainty.lower : null;
  const hi = radius.uncertainty ? radius.value + radius.uncertainty.upper : null;
  const dMin = Math.min(0.3, (lo > 0 ? lo : radius.value) / 1.5);
  const dMax = Math.max(30, (hi || radius.value) * 1.5);
  const x = scaleLog([dMin, dMax], [L, W - R]);
  const ticks = [0.3, 1, 3, 10, 30].filter((t) => t >= dMin && t <= dMax);
  const cy = 50;

  return (
    <ChartFrame
      testId="radius-scale"
      title="Planet radius in context"
      legend={
        <>
          <LegendItem kind="key-dot accent">This candidate ±1σ</LegendItem>
          <LegendItem kind="key-tick">Solar-system reference</LegendItem>
        </>
      }
      caption="Log scale, Earth radii. References are fixed solar-system radii for comparison only; the size category above comes from the engine's own classification rules."
    >
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Planet radius ${radius.display} Earth radii on a log scale`}>
        <line className="chart-axis" x1={L} x2={W - R} y1={cy} y2={cy} />
        {ticks.map((t) => (
          <text key={t} className="chart-tick" x={x(t)} y={H - 6} textAnchor="middle">{t} R⊕</text>
        ))}
        {REFERENCES.filter((ref) => ref.r >= dMin && ref.r <= dMax).map((ref) => (
          <g key={ref.name}>
            <line className="chart-ref" x1={x(ref.r)} x2={x(ref.r)} y1={cy - 12} y2={cy + 12} />
            <text className="chart-ref-label" x={x(ref.r)} y={cy - 18} textAnchor="middle">{ref.name}</text>
          </g>
        ))}
        {lo > 0 && hi && <line className="chart-interval" x1={x(lo)} x2={x(hi)} y1={cy} y2={cy} />}
        <circle className="chart-point accent" cx={x(radius.value)} cy={cy} r={6} />
        <text className="chart-value-label" x={x(radius.value)} y={cy + 26} textAnchor="middle">{radius.display} R⊕</text>
      </svg>
    </ChartFrame>
  );
}
