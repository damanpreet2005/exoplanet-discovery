/** Linear scale mapping [d0, d1] onto [r0, r1]. */
export function scaleLinear([d0, d1], [r0, r1]) {
  const span = d1 - d0 || 1;
  return (v) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** Log10 scale mapping [d0, d1] (both > 0) onto [r0, r1]. */
export function scaleLog([d0, d1], [r0, r1]) {
  const l0 = Math.log10(d0);
  const l1 = Math.log10(d1);
  return (v) => r0 + ((Math.log10(v) - l0) / (l1 - l0 || 1)) * (r1 - r0);
}

/** "Nice" round tick values covering [min, max] (about `count` ticks). */
export function niceTicks(min, max, count = 5) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) return [min];
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) {
    ticks.push(Math.abs(v) < step * 1e-9 ? 0 : Number(v.toPrecision(12)));
  }
  return ticks;
}

export function extent(values) {
  const finite = values.filter((v) => Number.isFinite(v));
  return finite.length ? [Math.min(...finite), Math.max(...finite)] : [NaN, NaN];
}

export function fmtTick(v) {
  const abs = Math.abs(v);
  if (abs >= 1000) return v.toFixed(0);
  if (abs >= 10 || v === 0) return String(Number(v.toFixed(1)));
  return String(Number(v.toPrecision(3)));
}
