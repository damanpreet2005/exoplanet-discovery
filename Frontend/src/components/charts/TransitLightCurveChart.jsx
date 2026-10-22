import { useState } from "react";
import { ChartFrame, ChartTooltip, ChartUnavailable, LegendItem } from "./ChartFrame";
import { extent, fmtTick, niceTicks, scaleLinear } from "./chartUtils";

const W = 640;
const H = 280;
const M = { l: 80, r: 14, t: 12, b: 44 };

/**
 * Phase-folded transit light curve: the binned, detrended photometry and the
 * best-fit limb-darkened model, exactly as exported by the characterization
 * engine (`transit_fit.folded`). Nothing here is simulated -- with no folded
 * data the chart says so instead of drawing a curve.
 */
export default function TransitLightCurveChart({ folded, compact = false }) {
  const [hover, setHover] = useState(null);

  if (!folded || !folded.phase_hours?.length) {
    return (
      <ChartUnavailable
        title="Light curve unavailable"
        reason="A phase-folded light curve needs a successful transit-model fit. This session has none (no transit was fitted, or it was analysed before the folded curve was exported) — re-upload the light curve to plot it."
      />
    );
  }

  const xs = folded.phase_hours;
  const ys = folded.flux_ppm;
  const es = folded.flux_err_ppm;
  const [x0, x1] = extent([...xs, ...folded.model_phase_hours]);
  const [yLo] = extent([...ys.map((y, i) => y - es[i]), ...folded.model_flux_ppm]);
  const [, yHi] = extent(ys.map((y, i) => y + es[i]));
  const pad = (yHi - yLo) * 0.08 || 10;
  const x = scaleLinear([x0, x1], [M.l, W - M.r]);
  const y = scaleLinear([yLo - pad, yHi + pad], [H - M.b, M.t]);
  const xTicks = niceTicks(x0, x1, 6);
  const yTicks = niceTicks(yLo - pad, yHi + pad, 5);
  const modelPath = folded.model_phase_hours
    .map((p, i) => `${i ? "L" : "M"}${x(p).toFixed(1)},${y(folded.model_flux_ppm[i]).toFixed(1)}`)
    .join("");

  function handleMove(event) {
    // Map the pointer into SVG user units through the SVG's own transform.
    // (The hover target is the plot-area rect, which starts after the left
    // margin, so its bounding box is not the SVG's -- using it offset the
    // highlighted bin from the pointer.)
    const svg = event.currentTarget.ownerSVGElement;
    const ctm = svg?.getScreenCTM?.();
    let px;
    if (ctm) {
      px = (event.clientX - ctm.e) / ctm.a;
    } else {
      const rect = svg.getBoundingClientRect();
      px = ((event.clientX - rect.left) / rect.width) * W;
    }
    let best = 0;
    for (let i = 1; i < xs.length; i++) if (Math.abs(x(xs[i]) - px) < Math.abs(x(xs[best]) - px)) best = i;
    setHover(best);
  }

  return (
    <ChartFrame
      testId="transit-lightcurve-chart"
      title={compact ? null : "Phase-folded transit"}
      legend={
        <>
          <LegendItem kind="key-dot">Binned data ±1σ</LegendItem>
          <LegendItem kind="key-line">Best-fit model</LegendItem>
        </>
      }
      caption={`${xs.length} bins of ${folded.bin_width_hours} h from ${folded.n_points.toLocaleString()} detrended points around each transit, folded on the fitted ephemeris. Flux relative to the out-of-transit baseline.`}
    >
      <div className="chart-plot">
        <svg viewBox={`0 0 ${W} ${H}`} className="chart-wide" role="img" aria-label="Phase-folded transit light curve with best-fit model">
          {yTicks.map((t) => (
            <g key={`y${t}`}>
              <line className="chart-grid" x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} />
              <text className="chart-tick" x={M.l - 8} y={y(t)} dy="0.32em" textAnchor="end">{fmtTick(t)}</text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text key={`x${t}`} className="chart-tick" x={x(t)} y={H - M.b + 22} textAnchor="middle">{fmtTick(t)}</text>
          ))}
          <line className="chart-axis" x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} />
          <text className="chart-axis-label" x={(M.l + W - M.r) / 2} y={H - 4} textAnchor="middle">Hours from mid-transit</text>
          <text className="chart-axis-label" transform={`translate(14 ${(M.t + H - M.b) / 2}) rotate(-90)`} textAnchor="middle">Relative flux (ppm)</text>

          {xs.map((p, i) => (
            <line key={`e${i}`} className="chart-errbar" x1={x(p)} x2={x(p)} y1={y(ys[i] - es[i])} y2={y(ys[i] + es[i])} />
          ))}
          {xs.map((p, i) => (
            <circle key={`p${i}`} className={`chart-point${hover === i ? " is-active" : ""}`} cx={x(p)} cy={y(ys[i])} r={hover === i ? 4.5 : 3} />
          ))}
          <path className="chart-model" d={modelPath} />
          {hover !== null && <line className="chart-crosshair" x1={x(xs[hover])} x2={x(xs[hover])} y1={M.t} y2={H - M.b} />}
          <rect
            className="chart-hit" x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b}
            onMouseMove={handleMove} onMouseLeave={() => setHover(null)}
          />
        </svg>
        {hover !== null && (
          <ChartTooltip x={(x(xs[hover]) / W) * 100} y={(y(ys[hover]) / H) * 100}>
            <strong>{xs[hover] >= 0 ? "+" : ""}{xs[hover].toFixed(2)} h</strong>
            <span>{ys[hover].toFixed(0)} ± {es[hover].toFixed(0)} ppm</span>
            <span className="chart-tooltip-muted">{folded.n_per_bin[hover]} points</span>
          </ChartTooltip>
        )}
      </div>
      <details className="chart-table-toggle">
        <summary>Data table</summary>
        <div className="table-scroll">
          <table className="feature-table">
            <thead><tr><th>Hours from mid-transit</th><th>Flux (ppm)</th><th>± (ppm)</th><th>Points</th></tr></thead>
            <tbody>
              {xs.map((p, i) => (
                <tr key={p}><td className="value">{p.toFixed(2)}</td><td className="value">{ys[i].toFixed(1)}</td><td className="value">{es[i].toFixed(1)}</td><td className="value">{folded.n_per_bin[i]}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </ChartFrame>
  );
}
