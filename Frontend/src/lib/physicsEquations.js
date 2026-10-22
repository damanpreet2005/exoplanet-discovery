/**
 * Presentation metadata for the three Stage 2 physics checks, keyed by the
 * backend's `test_id`. The equations, constants and tolerances transcribe
 * ml_service/app/physics_validation.py and app/astrophysics.py exactly; all
 * numbers shown next to them (inputs, derived values, results, status) come
 * from the backend report -- nothing is computed here.
 */

const G_CONST = { sym: "G", name: "Gravitational constant", value: "6.67430 × 10⁻¹¹", unit: "m³ kg⁻¹ s⁻²", source: "Physical constant" };
const RATIO_CONST = { sym: "R_\\oplus / R_\\odot", name: "Earth-to-Sun radius ratio", value: "0.0091577", unit: "—", source: "6.371 × 10⁶ m ÷ 6.957 × 10⁸ m" };

const K_DEF = "k = \\frac{R_\\oplus}{R_\\odot}\\,\\frac{R_p}{R_\\star}";
const MASS_DEF = "M_\\star = \\frac{g\\,R_\\star^{2}}{G}, \\qquad g = 10^{\\log g}\\ \\mathrm{cm\\,s^{-2}}";
const KEPLER_A = "a = \\left(\\frac{G\\,M_\\star\\,P^{2}}{4\\pi^{2}}\\right)^{1/3}";

const SI_NOTES = [
  "log g is in cgs units: g [m s⁻²] = 10^(log g) ÷ 100.",
  "R⋆ is converted to metres with R☉ = 6.957 × 10⁸ m; M⋆ is reported in solar masses (M☉ = 1.98892 × 10³⁰ kg).",
  "P is converted to seconds (1 day = 86 400 s) inside Kepler's law; a is reported in AU (1.495978707 × 10¹¹ m).",
];

export const PHYSICS_STAGES = {
  planet_size: {
    question: "Is the measured transit depth consistent with the sizes of the planet and its star?",
    explanation:
      "A transiting planet blocks a fraction of the stellar disk equal to the ratio of their areas, so the depth should be close to (Rp/R⋆)².",
    equation: "\\delta_{\\mathrm{exp}} \\approx 10^{6}\\left(\\frac{R_\\oplus}{R_\\odot}\\cdot\\frac{R_p}{R_\\star}\\right)^{2}\\ \\mathrm{ppm}",
    derivations: [{ label: "Radius ratio", tex: K_DEF }],
    inputs: [
      { key: "koi_depth", sym: "\\delta_{\\mathrm{obs}}", name: "Observed transit depth" },
      { key: "koi_prad", sym: "R_p", name: "Planet radius" },
      { key: "koi_srad", sym: "R_\\star", name: "Stellar radius" },
    ],
    constants: [RATIO_CONST],
    derived: {
      radius_ratio_k: { sym: "k", name: "Planet-to-star radius ratio" },
      expected_depth: { sym: "\\delta_{\\mathrm{exp}}", name: "Expected transit depth" },
    },
    constraint: (tol) => `\\frac{\\lvert \\delta_{\\mathrm{obs}} - \\delta_{\\mathrm{exp}} \\rvert}{\\delta_{\\mathrm{obs}}} \\le ${tol}`,
    unitNotes: [
      "Rp is in Earth radii and R⋆ in solar radii; multiplying by R⊕/R☉ expresses both in the same unit, so k is dimensionless.",
      "k² is a fraction of the stellar flux; × 10⁶ converts it to parts per million, the unit of the observed depth.",
    ],
  },
  transit_duration: {
    question: "Does the measured transit duration match the duration implied by the orbit and the sizes of the planet and star?",
    explanation:
      "For a circular orbit, the time from first to last contact (T₁₄) follows from the period, the orbit size relative to the star, the radius ratio and the impact parameter.",
    equation: "T_{14} \\approx \\frac{P}{\\pi}\\,\\arcsin\\!\\left(\\frac{\\sqrt{(1+k)^{2}-b^{2}}}{a/R_\\star}\\right)",
    derivations: [
      { label: "Radius ratio", tex: K_DEF },
      { label: "Stellar mass from surface gravity", tex: MASS_DEF },
      { label: "Semi-major axis (Kepler's third law)", tex: KEPLER_A },
    ],
    inputs: [
      { key: "koi_duration", sym: "T_{\\mathrm{obs}}", name: "Observed transit duration" },
      { key: "koi_period", sym: "P", name: "Orbital period" },
      { key: "koi_impact", sym: "b", name: "Impact parameter" },
      { key: "koi_prad", sym: "R_p", name: "Planet radius" },
      { key: "koi_srad", sym: "R_\\star", name: "Stellar radius" },
      { key: "koi_slogg", sym: "\\log g", name: "Stellar surface gravity" },
    ],
    constants: [G_CONST, RATIO_CONST],
    derived: {
      stellar_mass: { sym: "M_\\star", name: "Stellar mass" },
      semi_major_axis: { sym: "a", name: "Semi-major axis" },
      a_over_rstar: { sym: "a/R_\\star", name: "Scaled semi-major axis" },
      radius_ratio_k: { sym: "k", name: "Planet-to-star radius ratio" },
      expected_duration: { sym: "T_{14}", name: "Expected transit duration" },
    },
    constraint: (tol) => `\\frac{\\lvert T_{\\mathrm{obs}} - T_{14} \\rvert}{T_{\\mathrm{obs}}} \\le ${tol}`,
    unitNotes: [
      "With P in days the arcsine term gives T₁₄ in days; × 24 converts it to hours, the unit of the observed duration.",
      ...SI_NOTES,
    ],
  },
  orbital_physics: {
    question: "Are the orbital period and the star's mass consistent with a physically possible transiting orbit?",
    explanation:
      "Kepler's third law gives the orbit size from the period and stellar mass. The orbit must be larger than the star, and the reported impact parameter and radius ratio must allow a transit at that distance.",
    equation: "P^{2} = \\frac{4\\pi^{2}a^{3}}{G\\,M_\\star} \\;\\Longrightarrow\\; a = \\left(\\frac{G\\,M_\\star\\,P^{2}}{4\\pi^{2}}\\right)^{1/3}",
    equationNote: "Assumes the planet's mass is negligible compared with the star's.",
    derivations: [
      { label: "Stellar mass from surface gravity", tex: MASS_DEF },
      { label: "Transit-geometry cross-check (when b and Rp are available)", tex: "\\frac{\\sqrt{(1+k)^{2}-b^{2}}}{a/R_\\star} \\le 1, \\qquad " + K_DEF },
    ],
    inputs: [
      { key: "koi_period", sym: "P", name: "Orbital period" },
      { key: "koi_srad", sym: "R_\\star", name: "Stellar radius" },
      { key: "koi_slogg", sym: "\\log g", name: "Stellar surface gravity" },
      { key: "koi_impact", sym: "b", name: "Impact parameter", crossCheck: true },
      { key: "koi_prad", sym: "R_p", name: "Planet radius", crossCheck: true },
    ],
    constants: [G_CONST],
    derived: {
      stellar_mass: { sym: "M_\\star", name: "Stellar mass" },
      semi_major_axis: { sym: "a", name: "Semi-major axis" },
      a_over_rstar: { sym: "a/R_\\star", name: "Scaled semi-major axis" },
    },
    constraintTex: "a/R_\\star > 1 \\quad\\text{and}\\quad \\frac{\\sqrt{(1+k)^{2}-b^{2}}}{a/R_\\star} \\le 1",
    unitNotes: SI_NOTES,
  },
};

const UNIT_DISPLAY = {
  "Earth radii": "R⊕",
  "Solar radii": "R☉",
  "Solar masses": "M☉",
  dimensionless: "—",
  "Rp/Rstar": "—",
  "log10(cm/s^2)": "dex (cgs)",
};

export function displayUnit(unit) {
  if (!unit) return "—";
  return UNIT_DISPLAY[unit] || unit;
}
