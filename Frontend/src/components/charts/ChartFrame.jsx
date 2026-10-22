import Icon from "../Icon";

/** Shared chrome for every chart: title, legend, caption and the empty state. */
export function ChartFrame({ title, legend, caption, children, testId }) {
  return (
    <figure className="chart" data-testid={testId}>
      {(title || legend) && (
        <div className="chart-head">
          {title && <figcaption className="chart-title">{title}</figcaption>}
          {legend && <div className="chart-legend">{legend}</div>}
        </div>
      )}
      <div className="chart-body">{children}</div>
      {caption && <p className="chart-caption">{caption}</p>}
    </figure>
  );
}

export function LegendItem({ kind, children }) {
  return (
    <span className="chart-legend-item">
      <span className={`chart-key ${kind}`} aria-hidden="true" />
      {children}
    </span>
  );
}

/** Explains which inputs a chart needs instead of drawing anything invented. */
export function ChartUnavailable({ title, reason }) {
  return (
    <div className="chart-unavailable" role="note">
      <Icon name="block" size={20} />
      <div>
        <div className="chart-unavailable-title">{title}</div>
        <p>{reason}</p>
      </div>
    </div>
  );
}

/** Hover read-out positioned over the plot (percent coordinates). */
export function ChartTooltip({ x, y, children }) {
  return (
    <div className="chart-tooltip" style={{ left: `${x}%`, top: `${y}%` }} role="status">
      {children}
    </div>
  );
}
