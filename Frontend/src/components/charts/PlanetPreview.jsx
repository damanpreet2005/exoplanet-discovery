import { useEffect, useMemo, useRef } from "react";
import Icon from "../Icon";

/**
 * Small rotating, shaded sphere illustrating what a planet of the engine's
 * radius-based category might look like. It is an artist's-impression style
 * illustration, driven only by computed values:
 *   - archetype (surface vs. banded atmosphere) <- composition candidate class
 *   - colour temperature                         <- equilibrium temperature
 * It is never presented as an image of the planet, and nothing is drawn when
 * the category is unavailable or the object is too large to be a planet.
 *
 * Rendered on a plain <canvas> (no 3D library): a procedural texture is
 * sampled onto an orthographic sphere with Lambert shading each frame.
 */

const TEX_W = 256;
const TEX_H = 128;
const SIZE = 360; // internal canvas resolution (px): 2x the ~180 px display size, sharp on retina

const ARCHETYPES = [
  { key: "rocky", match: /Rocky/i, label: "Rocky world" },
  { key: "subneptune", match: /sub-Neptune/i, label: "Sub-Neptune" },
  { key: "neptune", match: /Neptune-like/i, label: "Neptune-like world" },
  { key: "giant", match: /Gas-giant/i, label: "Gas giant" },
];

export function planetArchetype(report) {
  const comp = (report?.classifications || []).find((c) => c.name === "composition_candidate");
  const size = (report?.classifications || []).find((c) => c.name === "size_category");
  if (size?.status === "computed" && /Exceeds planetary radii/i.test(size.category || "")) {
    return { key: null, reason: "Too large to be a planet (likely a stellar companion), so no planet is drawn." };
  }
  if (comp?.status !== "computed" || !comp.category) {
    return { key: null, reason: "No illustration: the planet's size category could not be determined." };
  }
  const a = ARCHETYPES.find((x) => x.match.test(comp.category));
  return a ? { key: a.key, label: a.label, category: comp.category } : { key: null, reason: "No illustration for this category." };
}

// ---- deterministic procedural texture -----------------------------------

function hashSeed(text) {
  let h = 2166136261;
  for (const ch of String(text || "planet")) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return h >>> 0;
}

function rng(seed) {
  let s = seed || 1;
  return () => {
    s ^= s << 13; s ^= s >>> 17; s ^= s << 5;
    return ((s >>> 0) % 100000) / 100000;
  };
}

/** Tileable-in-longitude value noise, a few octaves, returns 0..1. */
function makeNoise(seed) {
  const r = rng(seed);
  const GX = 32;
  const GY = 16;
  const grid = Array.from({ length: GY + 1 }, () => Array.from({ length: GX }, () => r()));
  const smooth = (t) => t * t * (3 - 2 * t);
  const sample = (u, v, scale) => {
    const x = u * GX * scale;
    const y = v * GY * scale;
    const x0 = Math.floor(x);
    const y0 = Math.min(Math.floor(y), GY - 1);
    const fx = smooth(x - x0);
    const fy = smooth(y - y0);
    const g = (ix, iy) => grid[Math.min(iy, GY)][((ix % GX) + GX) % GX];
    const a = g(x0, y0) + (g(x0 + 1, y0) - g(x0, y0)) * fx;
    const b = g(x0, y0 + 1) + (g(x0 + 1, y0 + 1) - g(x0, y0 + 1)) * fx;
    return a + (b - a) * fy;
  };
  return (u, v) => (sample(u, v, 0.25) * 0.55 + sample(u, v, 0.5) * 0.3 + sample(u, v, 1) * 0.15);
}

const mix = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

/** Palette by archetype, shifted by equilibrium temperature (K). */
function palette(key, teq) {
  const hot = teq != null && teq >= 1000;
  const ultra = teq != null && teq >= 2000;
  const cold = teq != null && teq < 200;
  switch (key) {
    case "rocky":
      // >= 2000 K: largely molten surface; 1000-2000 K: dark basaltic crust, dim lava
      if (ultra) return { lo: [40, 22, 18], hi: [120, 60, 40], glow: [255, 120, 40], glowAt: 0.58 };
      if (hot) return { lo: [42, 34, 31], hi: [112, 94, 82], glow: [235, 100, 38], glowAt: 0.6 };
      return cold ? { lo: [150, 155, 165], hi: [225, 230, 238] } : { lo: [92, 78, 66], hi: [170, 150, 128] };
    case "subneptune":
      return hot ? { lo: [150, 140, 130], hi: [205, 190, 170] }
        : cold ? { lo: [170, 200, 215], hi: [225, 238, 245] } : { lo: [120, 170, 185], hi: [185, 215, 222] };
    case "neptune":
      return hot ? { lo: [70, 90, 130], hi: [150, 160, 190] }
        : cold ? { lo: [90, 140, 200], hi: [175, 210, 240] } : { lo: [45, 85, 170], hi: [110, 160, 225] };
    case "giant":
    default:
      if (ultra) return { lo: [120, 40, 25], hi: [240, 140, 70], glow: [255, 150, 60], glowAt: 0.62 };
      return hot ? { lo: [95, 55, 45], hi: [190, 130, 95] }
        : cold ? { lo: [170, 175, 185], hi: [235, 230, 215] } : { lo: [165, 120, 80], hi: [235, 215, 180] };
  }
}

function buildTexture(key, teq, seed) {
  const noise = makeNoise(seed);
  const pal = palette(key, teq);
  const tex = new Float32Array(TEX_W * TEX_H * 3);
  const banded = key !== "rocky";
  const bandFreq = key === "giant" ? 11 : key === "neptune" ? 7 : 5;
  const bandContrast = key === "giant" ? 0.55 : key === "neptune" ? 0.35 : 0.18; // sub-Neptunes: hazy
  for (let j = 0; j < TEX_H; j++) {
    const v = j / (TEX_H - 1);
    const lat = (v - 0.5) * Math.PI;
    for (let i = 0; i < TEX_W; i++) {
      const u = i / TEX_W;
      const n = noise(u, v);
      let t;
      if (banded) {
        const turbulence = (n - 0.5) * 1.2;
        t = 0.5 + bandContrast * Math.sin(lat * bandFreq + turbulence * 2.5) + (n - 0.5) * 0.35;
      } else {
        // mottled crust (higher contrast than the hazy gaseous worlds)
        t = Math.pow(n, 1.3) * 1.35 - 0.05;
      }
      t = Math.max(0, Math.min(1, t));
      let c = mix(pal.lo, pal.hi, t);
      if (pal.glow && n > pal.glowAt) c = mix(c, pal.glow, Math.min(1, (n - pal.glowAt) * 4)); // lava / hot spots
      if (key === "rocky" && teq != null && teq < 273 && Math.abs(lat) > 1.15) c = mix(c, [235, 240, 245], 0.8); // polar ice
      const k = (j * TEX_W + i) * 3;
      tex[k] = c[0]; tex[k + 1] = c[1]; tex[k + 2] = c[2];
    }
  }
  return tex;
}

/**
 * Per-pixel sphere geometry, computed once: texture latitude row, base
 * longitude, Lambert shade, atmospheric rim and edge coverage (for an
 * anti-aliased limb). Each frame then only shifts the longitude.
 */
function buildGeometry(atmospheric) {
  const r = SIZE / 2 - 3;
  const light = [-0.55, -0.35, 0.76];   // lit from the upper left
  const n = SIZE * SIZE;
  const g = { lon: new Float32Array(n), row: new Int32Array(n), shade: new Float32Array(n),
              rim: new Float32Array(n), cover: new Float32Array(n), halo: new Float32Array(n) };
  for (let py = 0; py < SIZE; py++) {
    for (let px = 0; px < SIZE; px++) {
      const i = py * SIZE + px;
      const x = (px - SIZE / 2 + 0.5) / r;
      const y = (py - SIZE / 2 + 0.5) / r;
      const d = Math.sqrt(x * x + y * y);
      g.cover[i] = Math.max(0, Math.min(1, (1 - d) * r + 0.5));          // ~1 px soft edge
      g.halo[i] = atmospheric && d > 1 ? Math.max(0, 1 - (d - 1) * 16) : 0;
      if (d >= 1 + 1 / r) continue;
      const dd = Math.min(d, 1);
      const xs = d > 0 ? (x / d) * dd : 0;
      const ys = d > 0 ? (y / d) * dd : 0;
      const z = Math.sqrt(Math.max(0, 1 - dd * dd));
      g.lon[i] = Math.atan2(xs, z);
      g.row[i] = Math.min(TEX_H - 1, Math.floor((Math.asin(-ys) / Math.PI + 0.5) * (TEX_H - 1)));
      g.shade[i] = 0.12 + 0.88 * Math.max(0, xs * light[0] + ys * light[1] + z * light[2]);
      g.rim[i] = atmospheric ? Math.pow(1 - z, 3) * 0.35 : 0;
    }
  }
  return g;
}

function drawFrame(ctx, image, tex, geo, rotation) {
  const data = image.data;
  const twoPi = 2 * Math.PI;
  for (let i = 0; i < SIZE * SIZE; i++) {
    const k = i * 4;
    const cover = geo.cover[i];
    if (cover <= 0) {
      const halo = geo.halo[i];
      data[k] = 150; data[k + 1] = 200; data[k + 2] = 230; data[k + 3] = halo * 70;
      continue;
    }
    let u = ((geo.lon[i] + rotation) / twoPi) % 1;
    if (u < 0) u += 1;
    const t = (geo.row[i] * TEX_W + Math.min(TEX_W - 1, Math.floor(u * TEX_W))) * 3;
    const shade = geo.shade[i];
    const rim = geo.rim[i];
    data[k] = Math.min(255, tex[t] * shade + 160 * rim);
    data[k + 1] = Math.min(255, tex[t + 1] * shade + 205 * rim);
    data[k + 2] = Math.min(255, tex[t + 2] * shade + 235 * rim);
    data[k + 3] = 255 * cover;
  }
  ctx.putImageData(image, 0, 0);
}

export default function PlanetPreview({ report }) {
  const canvasRef = useRef(null);
  const arche = planetArchetype(report);
  const teq = report?.parameters?.equilibrium_temperature;
  const teqValue = teq?.status === "computed" ? teq.value : null;
  const radius = report?.parameters?.planet_radius;
  const seed = hashSeed(report?.candidate?.object_id);
  const tex = useMemo(() => (arche.key ? buildTexture(arche.key, teqValue, seed) : null), [arche.key, teqValue, seed]);

  useEffect(() => {
    const canvas = canvasRef.current;
    let ctx = null;
    try {
      ctx = canvas?.getContext?.("2d") ?? null;
    } catch {
      ctx = null;
    }
    // No usable 2D canvas (test environments, restricted browsers): keep the
    // caption, skip the drawing -- never let the illustration break the page.
    if (!ctx || !tex || typeof ctx.createImageData !== "function" || typeof ctx.putImageData !== "function") {
      return undefined;
    }
    const image = ctx.createImageData(SIZE, SIZE);
    const geo = buildGeometry(arche.key !== "rocky");
    const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let rotation = 0.6;
    let frame = null;
    let visible = true;
    let last = 0;
    const tick = (now) => {
      if (visible && now - last > 40) {        // ~25 fps is plenty for a slow spin
        rotation += 0.012;
        drawFrame(ctx, image, tex, geo, rotation);
        last = now;
      }
      frame = requestAnimationFrame(tick);
    };
    drawFrame(ctx, image, tex, geo, rotation);
    const observer = typeof IntersectionObserver !== "undefined"
      ? new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; })
      : null;
    observer?.observe(canvas);
    if (!reduce) frame = requestAnimationFrame(tick);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      observer?.disconnect();
    };
  }, [tex, arche.key]);

  if (!arche.key) {
    return (
      <div className="planet-preview is-empty" data-testid="planet-preview">
        <Icon name="public_off" size={22} />
        <p>{arche.reason}</p>
      </div>
    );
  }
  const temp = teqValue != null ? ` · Teq ≈ ${Math.round(teqValue / 10) * 10} K` : "";
  return (
    <figure className="planet-preview" data-testid="planet-preview">
      <canvas
        ref={canvasRef}
        width={SIZE}
        height={SIZE}
        role="img"
        aria-label={`Illustration of a ${arche.label.toLowerCase()}, based on the radius-based category`}
      />
      <figcaption>
        <strong>{arche.label}</strong>
        <span>{radius?.status === "computed" ? `${radius.display} R⊕` : ""}{temp}</span>
        <em>Illustrative only, from the radius-based category and equilibrium temperature; not an image of the planet.</em>
      </figcaption>
    </figure>
  );
}
