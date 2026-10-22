import { ChartFrame, ChartUnavailable, LegendItem } from "./ChartFrame";

const UNIT_DISPLAY = { "days (uploaded time system)": "d" };

/**
 * This analysis vs the KOI catalogue, per parameter, as the engine's own
 * tension (difference in combined standard deviations). Rows without a
 * tension (no catalogue uncertainty) show the values only.
 */
export default function TensionChart({ rows }) {
  if (!rows?.length) {
    return (
      <ChartUnavailable
        title="Catalogue comparison unavailable"
        reason="The object did not match a KOI catalogue row, so there are no catalogue values to compare with."
      />
    );
  }
  const maxT = Math.max(3, ...rows.map((r) => Math.abs(r.tension_sigma ?? 0)));
  const span = Math.ceil(maxT);
  const pos = (t) => 50 + (t / span) * 50;
  return (
    <ChartFrame
      testId="tension-chart"
      title="This analysis vs KOI catalogue"
      legend={
        <>
          <LegendItem kind="key-dot">Consistent</LegendItem>
          <LegendItem kind="key-dot warn">Flagged</LegendItem>
        </>
      }
      caption="Tension = (this analysis − catalogue) / combined 1σ uncertainty, as computed by the characterization engine."
    >
      <div className="tension-rows">
        <div className="tension-row tension-axis" aria-hidden="true">
          <span />
          <div className="tension-track">
            {[-span, 0, span].map((t) => <span key={t} className="tension-tick" style={{ left: `${pos(t)}%` }}>{t > 0 ? `+${t}` : t}σ</span>)}
          </div>
          <span />
        </div>
        {rows.map((r) => {
          const unit = UNIT_DISPLAY[r.unit] || r.unit;
          const has = r.tension_sigma !== null && r.tension_sigma !== undefined;
          return (
            <div className="tension-row" key={r.parameter}>
              <span className="tension-label">{r.label}</span>
              <div className="tension-track">
                <span className="tension-zero" style={{ left: "50%" }} />
                {has && (
                  <span
                    className={`tension-dot${r.consistent === false ? " warn" : ""}`}
                    style={{ left: `${pos(r.tension_sigma)}%` }}
                    title={`${r.tension_sigma}σ`}
                  />
                )}
              </div>
              <span className="tension-values">
                {r.engine_value} vs {r.catalog_value} {unit}
                <em>{has ? `${r.tension_sigma}σ` : "no σ"}{r.consistent === false ? " · flagged" : ""}</em>
              </span>
            </div>
          );
        })}
      </div>
    </ChartFrame>
  );
}
