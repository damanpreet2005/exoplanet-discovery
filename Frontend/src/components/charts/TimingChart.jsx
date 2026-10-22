import { useState } from "react";
import { ChartFrame, ChartTooltip, ChartUnavailable, LegendItem } from "./ChartFrame";
import { extent, fmtTick, niceTicks, scaleLinear } from "./chartUtils";

const W = 640;
const H = 220;
const M = { l: 80, r: 14, t: 12, b: 44 };

/** Observed-minus-calculated transit times (minutes) against the linear ephemeris. */
export default function TimingChart({ timing }) {
  const [hover, setHover] = useState(null);
  const rows = (timing?.transits || []).filter((t) => t.o_minus_c_minutes !== null && t.o_minus_c_minutes !== undefined);

  if (rows.length < 2) {
    return (
      <ChartUnavailable
        title="Transit timing unavailable"
        reason="An O − C diagram needs at least two individually timed transits and a fitted linear ephemeris."
      />
    );
  }

  const ex = extent(rows.map((r) => r.epoch));
  const lo = Math.min(0, ...rows.map((r) => r.o_minus_c_minutes - r.error_minutes));
  const hi = Math.max(0, ...rows.map((r) => r.o_minus_c_minutes + r.error_minutes));
  const pad = (hi - lo) * 0.1 || 1;
  const x = scaleLinear([ex[0] - 0.5, ex[1] + 0.5], [M.l, W - M.r]);
  const y = scaleLinear([lo - pad, hi + pad], [H - M.b, M.t]);
  const yTicks = niceTicks(lo - pad, hi + pad, 4);
  const xTicks = niceTicks(ex[0], ex[1], Math.min(rows.length, 8)).filter((t) => Number.isInteger(t));

  return (
    <ChartFrame
      testId="timing-chart"
      title="Transit timing (O − C)"
      legend={<LegendItem kind="key-dot">Timed transit ±1σ</LegendItem>}
      caption={timing.assessment}
    >
      <div className="chart-plot">
        <svg viewBox={`0 0 ${W} ${H}`} className="chart-wide" role="img" aria-label="Observed minus calculated transit times by epoch">
          {yTicks.map((t) => (
            <g key={`y${t}`}>
              <line className={t === 0 ? "chart-zero" : "chart-grid"} x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} />
              <text className="chart-tick" x={M.l - 8} y={y(t)} dy="0.32em" textAnchor="end">{fmtTick(t)}</text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text key={`x${t}`} className="chart-tick" x={x(t)} y={H - M.b + 22} textAnchor="middle">{t}</text>
          ))}
          <line className="chart-axis" x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} />
          <text className="chart-axis-label" x={(M.l + W - M.r) / 2} y={H - 4} textAnchor="middle">Transit epoch</text>
          <text className="chart-axis-label" transform={`translate(14 ${(M.t + H - M.b) / 2}) rotate(-90)`} textAnchor="middle">O − C (min)</text>
          {rows.map((r, i) => (
            <g key={r.epoch} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <line className="chart-errbar" x1={x(r.epoch)} x2={x(r.epoch)} y1={y(r.o_minus_c_minutes - r.error_minutes)} y2={y(r.o_minus_c_minutes + r.error_minutes)} />
              <circle className={`chart-point${hover === i ? " is-active" : ""}`} cx={x(r.epoch)} cy={y(r.o_minus_c_minutes)} r={hover === i ? 5 : 4} />
              <rect className="chart-hit" x={x(r.epoch) - 12} y={M.t} width={24} height={H - M.t - M.b} />
            </g>
          ))}
        </svg>
        {hover !== null && (
          <ChartTooltip x={(x(rows[hover].epoch) / W) * 100} y={(y(rows[hover].o_minus_c_minutes) / H) * 100}>
            <strong>Epoch {rows[hover].epoch}</strong>
            <span>{rows[hover].o_minus_c_minutes.toFixed(1)} ± {rows[hover].error_minutes.toFixed(1)} min</span>
            <span className="chart-tooltip-muted">{rows[hover].n_points} points</span>
          </ChartTooltip>
        )}
      </div>
    </ChartFrame>
  );
}
