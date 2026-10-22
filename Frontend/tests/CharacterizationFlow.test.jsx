import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, expect, test, vi, beforeEach, afterEach } from "vitest";
import App from "../src/App";
// Real output of the ML service's characterization engine for its synthetic
// Kepler-227 b test light curve (see ml_service/tests/test_planet_characterization.py),
// not a hand-written mock -- so these tests exercise the actual report shape.
import REPORT from "./fixtures/characterization_report.json";

const SESSION_KEY = "exoplanet_prediction_session_v1";

const LIGHT_CURVE_RESULT = {
  dataset_type: "light_curve",
  filename: "k227.csv",
  object_id: "K00752.01",
  diagnostics: {
    n_points_used: 4900, n_points_dropped: 0, baseline_days: 100,
    bls_period_days: 9.488, bls_duration_hours: 2.6, bls_depth_ppm: 479,
    bls_transit_snr: 0.1, num_transits_observed: 10,
  },
  extracted_features: {},
  suggested_parameters: {},
  characterisation: {
    status: "computed", bls_period_days: 9.488, bls_duration_hours: 2.6, bls_depth_ppm: 479,
    bls_transit_snr: 0.1, num_transits_observed: 10, odd_even_depth_ratio: 1.0,
    secondary_eclipse_depth_ppm: 2.0, note: "vetting note",
  },
  physics_validation: { status: "not_implemented", message: "later" },
  warnings: [],
  features: {
    koi_srad: { value: 0.927, unit: "Solar radii", source: "nasa_koi_catalog", status: "catalog", note: "" },
    koi_steff: { value: 5455, unit: "K", source: "nasa_koi_catalog", status: "catalog", note: "" },
  },
  characterization: REPORT,
};

const FINAL_RESULT = {
  prediction: 1, weighted_probability: 0.9, random_forest_probability: 0.88,
  cnn_probability: 0.92, weights: { random_forest: 0.5, cnn: 0.5 }, model_version: "1.0",
};

function seedSession(extra = {}) {
  window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({
    lightCurveResult: LIGHT_CURVE_RESULT,
    finalResult: FINAL_RESULT,
    manualParameters: { koi_srad: 0.927, koi_steff: 5455 },
    ...extra,
  }));
}

function overriddenReport() {
  const rep = JSON.parse(JSON.stringify(REPORT));
  delete rep.inputs;
  rep.parameters.stellar_radius = {
    ...rep.parameters.stellar_radius, value: 1.2, display: "1.2 ± 0.05", provenance: "manual_override",
    original: { value: 0.927, provenance: "catalog", display: "0.927 +0.105 / −0.061", uncertainty: null },
  };
  rep.parameters.planet_radius = { ...rep.parameters.planet_radius, display: "2.95 +0.17 / −0.16", depends_on_override: ["stellar_radius"] };
  rep.overrides.applied = { stellar_radius: { value: 1.2, err_plus: 0.05, err_minus: 0.05, note: "" } };
  rep.overrides.recomputed_outputs = ["planet_radius", "semi_major_axis"];
  return rep;
}

describe("Planet characterization dashboard", () => {
  let originalFetch;

  beforeEach(() => {
    originalFetch = global.fetch;
    window.history.pushState({}, "", "/");
  });

  afterEach(() => {
    global.fetch = originalFetch;
    window.sessionStorage.clear();
  });

  async function openDashboard() {
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Planet Characterization" }));
    return screen.findByTestId("characterization-dashboard");
  }

  function openView(label) {
    const nav = screen.getByRole("navigation", { name: "Characterization sections" });
    fireEvent.click(within(nav).getByRole("button", { name: label }));
  }

  test("dashboard has a section sidebar, a summary strip and backend-computed values", async () => {
    seedSession();
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    await openDashboard();

    const nav = screen.getByRole("navigation", { name: "Characterization sections" });
    for (const label of ["Overview", "Planetary Properties", "Orbital Analysis", "Host Star", "Transit Analysis",
      "Physical Consistency", "Data Sources", "Expert Override"]) {
      expect(within(nav).getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(within(nav).getByRole("button", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("char-summary")).toHaveTextContent(REPORT.parameters.planet_radius.display);
    expect(screen.getByTestId("char-insights")).toBeInTheDocument();

    // Values are the engine's own rounded display strings, not recomputed client-side.
    const radius = screen.getByTestId("char-param-planet_radius");
    expect(radius).toHaveTextContent(REPORT.parameters.planet_radius.display);
    expect(radius).toHaveTextContent("R⊕");
    expect(within(radius).getByText("Derived")).toBeInTheDocument();
    // Model-estimated mass is labelled as such.
    expect(within(screen.getByTestId("char-param-planet_mass")).getByText("Model estimate")).toBeInTheDocument();
    // The light curve is plotted from the engine's folded data.
    const chart = screen.getByTestId("transit-lightcurve-chart");
    expect(chart.querySelectorAll("circle.chart-point")).toHaveLength(REPORT.transit_fit.folded.phase_hours.length);

    // Missing data is shown as unavailable, never as zero.
    openView("Host Star");
    expect(screen.getByTestId("char-param-stellar_metallicity")).toHaveTextContent("Unavailable");
    expect(window.location.search).toBe("?view=star");
    // No recompute request is fired just by viewing the page.
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes("characterization"))).toBe(false);
  });

  test("mass-dependent and transit-density values explain their basis, source and confidence", async () => {
    seedSession();
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    await openDashboard();
    openView("Planetary Properties");
    for (const name of ["planet_mass", "planet_density", "planet_surface_gravity", "escape_velocity"]) {
      const row = screen.getByTestId(`char-param-${name}`);
      const p = REPORT.parameters[name];
      expect(row).toHaveTextContent(p.display);
      expect(row).toHaveTextContent("Model estimate");
      expect(row).toHaveTextContent("Low confidence");
      expect(within(row).getByText("How this was determined")).toBeInTheDocument();
      expect(row).toHaveTextContent("Estimated from an empirical model, not measured.");
      expect(row).toHaveTextContent(p.reason);
    }
    // The dependents say how much of their uncertainty the mass causes.
    expect(screen.getByTestId("char-param-planet_density")).toHaveTextContent(/mass contributes \d+% of its uncertainty/);
    expect(screen.getByTestId("char-param-planet_mass")).toHaveTextContent(/radial-velocity or transit-timing mass/);

    // Long-cadence fixture: the ingress is unresolved, so no light-curve-only
    // density is claimed -- shown as unavailable with the reason and the remedy.
    openView("Host Star");
    const rho = screen.getByTestId("char-param-stellar_density_transit");
    expect(rho).toHaveTextContent("Unavailable");
    expect(rho).toHaveTextContent(/shorter than half the 29.4-minute exposure/);
    expect(rho).toHaveTextContent(/1-minute data/);
    openView("Physical Consistency");
    expect(screen.getByText(/the transit shape is not resolved/)).toBeInTheDocument();
  });

  test("mass sources: measured, catalogue-derived and unavailable are distinguished", async () => {
    const rep = JSON.parse(JSON.stringify(REPORT));
    rep.parameters.planet_mass = { ...rep.parameters.planet_mass, provenance: "catalog", evidence: "measured",
      reliability: "reliable", value: 7.0, display: "7.0 ± 0.7", reason: "",
      method: "Measured planet mass (radial velocities or transit-timing variations) from the NASA Exoplanet Archive.",
      source: "NASA Exoplanet Archive, confirmed-planet composite table (pscomppars)" };
    rep.parameters.stellar_mass = { ...rep.parameters.stellar_mass, provenance: "catalog", evidence: "catalogue_derived",
      value: 0.919, display: "0.919 +0.052 / −0.046", equation: "",
      method: "Isochrone-model stellar mass from the Kepler DR25 stellar catalogue (DSEP stellar models), fitted to the star's Teff, log g and [Fe/H]; a model-derived catalogue value, not a direct (e.g. binary-orbit) measurement.",
      source: "NASA Exoplanet Archive, Kepler Q1-Q17 DR25 stellar table (q1_q17_dr25_ks)" };
    rep.parameters.stellar_metallicity = { ...rep.parameters.stellar_metallicity, status: "unavailable", value: null,
      display: "Unavailable", provenance: "unavailable", evidence: "unavailable",
      reason: "The local KOI catalogue has no metallicity and the Archive's Kepler DR25 stellar table returned none for this star." };
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({
      lightCurveResult: { ...LIGHT_CURVE_RESULT, characterization: rep },
      finalResult: FINAL_RESULT, manualParameters: { koi_srad: 0.927, koi_steff: 5455 },
    }));
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    await openDashboard();
    openView("Planetary Properties");
    const mass = screen.getByTestId("char-param-planet_mass");
    expect(mass).toHaveTextContent("7.0 ± 0.7");
    expect(within(mass).getByText("Measured")).toBeInTheDocument();
    expect(mass).toHaveTextContent("A direct measurement, taken from a catalogue.");
    expect(mass).toHaveTextContent(/pscomppars/);
    expect(mass).not.toHaveTextContent("Model estimate");

    openView("Host Star");
    const star = screen.getByTestId("char-param-stellar_mass");
    expect(star).toHaveTextContent("0.919 +0.052 / −0.046 M☉");
    expect(within(star).getByText("Catalogue")).toBeInTheDocument();
    expect(star).toHaveTextContent(/derived from observations through a model or calibration/);
    expect(star).toHaveTextContent(/Isochrone-model stellar mass/);
    const feh = screen.getByTestId("char-param-stellar_metallicity");
    expect(feh).toHaveTextContent("Unavailable");
    expect(feh).toHaveTextContent(/returned none for this star/);
  });

  test("each analytical view renders its own panels", async () => {
    seedSession();
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    await openDashboard();

    openView("Orbital Analysis");
    expect(screen.getByTestId("orbit-schematic")).toHaveTextContent(/Illustrative diagram, not an observed image/);
    expect(screen.getByTestId("char-param-semi_major_axis")).toHaveTextContent(REPORT.parameters.semi_major_axis.display);

    openView("Transit Analysis");
    expect(screen.getByTestId("timing-chart")).toBeInTheDocument();
    expect(screen.getByTestId("char-section-transit_signal")).toBeInTheDocument();

    openView("Physical Consistency");
    expect(screen.getByTestId("tension-chart")).toHaveTextContent(REPORT.catalog_comparison[0].label);
    expect(screen.getByText(/Not yet run for the submitted parameters/i)).toBeInTheDocument();

    openView("Data Sources");
    expect(screen.getByText(REPORT.assumptions[0].text)).toBeInTheDocument();
  });

  test("classifications show their basis, inputs and the habitability disclaimer", async () => {
    seedSession();
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    await openDashboard();
    openView("Planetary Properties");
    const panel = screen.getByTestId("char-classifications");
    expect(panel).toHaveTextContent(REPORT.classifications[0].category);
    expect(panel).toHaveTextContent(`${Math.round(REPORT.classifications[0].probability * 100)}%`);
    expect(within(panel).getAllByText(/planet_radius/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/do not establish composition, atmosphere,\s+habitability/i).length).toBeGreaterThan(0);
    expect(screen.getByTestId("radius-scale")).toBeInTheDocument();
  });

  test("a report without folded light-curve data says so instead of drawing a curve", async () => {
    const rep = JSON.parse(JSON.stringify(REPORT));
    delete rep.transit_fit.folded;
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({
      lightCurveResult: { ...LIGHT_CURVE_RESULT, characterization: rep },
      finalResult: FINAL_RESULT, manualParameters: { koi_srad: 0.927, koi_steff: 5455 },
    }));
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    await openDashboard();
    expect(screen.getByText("Light curve unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("transit-lightcurve-chart")).not.toBeInTheDocument();
  });

  test("results page links to the dashboard instead of embedding the full report", async () => {
    seedSession();
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Detection & Prediction" }));
    const teaser = await screen.findByTestId("results-characterization");
    expect(teaser).toHaveTextContent(REPORT.parameters.planet_radius.display);
    expect(teaser).toHaveTextContent(REPORT.classifications[0].category);
    expect(within(teaser).getByRole("link", { name: /Open Planet Characterization/i })).toHaveAttribute("href", "/characterisation");
    expect(screen.queryByTestId("characterization-dashboard")).not.toBeInTheDocument();
  });

  test("expert override sends the stored inputs snapshot and shows the recomputed report", async () => {
    seedSession();
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => overriddenReport() });
    await openDashboard();
    openView("Expert Override");
    const panel = await screen.findByTestId("characterization-override-panel");

    fireEvent.change(within(panel).getByLabelText(/^Stellar radius \(/i), { target: { value: "1.2" } });
    fireEvent.change(within(panel).getByLabelText(/Stellar radius uncertainty/i), { target: { value: "0.05" } });
    fireEvent.click(within(panel).getByRole("button", { name: /Recompute characterization/i }));

    expect(await screen.findByTestId("char-recomputed")).toHaveTextContent(/Overridden: stellar_radius/);
    openView("Host Star");
    expect(screen.getByTestId("char-param-stellar_radius")).toHaveTextContent("Expert override");

    const call = global.fetch.mock.calls.find(([url]) => String(url).includes("/api/v1/characterization/recompute"));
    const body = JSON.parse(call[1].body);
    expect(body.inputs.schema_version).toBe(REPORT.inputs.schema_version);
    expect(body.overrides).toEqual({ stellar_radius: { value: 1.2, uncertainty: 0.05 } });
    expect(body.config.bond_albedo).toBe(0.3);
  });

  test("restoring automatic values drops the override without another request", async () => {
    seedSession({
      characterizationReport: overriddenReport(),
      characterizationOverrides: { stellar_radius: { value: 1.2, uncertainty: 0.05 } },
    });
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    await openDashboard();
    expect(screen.getByTestId("char-param-stellar_radius")).toHaveTextContent("Expert override");

    openView("Expert Override");
    fireEvent.click(screen.getByRole("button", { name: /Restore automatic values/i }));
    openView("Host Star");
    expect(screen.getByTestId("char-param-stellar_radius")).toHaveTextContent("Catalogue");
    expect(screen.getByTestId("char-param-stellar_radius")).toHaveTextContent("0.927");
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes("characterization"))).toBe(false);
  });

  test("an invalid override is rejected client-side before any request", async () => {
    seedSession();
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    await openDashboard();
    openView("Expert Override");
    const panel = await screen.findByTestId("characterization-override-panel");
    fireEvent.change(within(panel).getByLabelText(/Bond albedo/i), { target: { value: "1.4" } });
    fireEvent.click(within(panel).getByRole("button", { name: /Recompute characterization/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Bond albedo/);
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes("characterization"))).toBe(false);
  });

  test("a backend rejection is shown, not swallowed", async () => {
    seedSession();
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ error: { code: "CHARACTERIZATION_VALIDATION_ERROR", message: "outside the physical range" } }),
    });
    await openDashboard();
    openView("Expert Override");
    const panel = await screen.findByTestId("characterization-override-panel");
    fireEvent.change(within(panel).getByLabelText("Eccentricity"), { target: { value: "0.995" } });
    fireEvent.click(within(panel).getByRole("button", { name: /Recompute characterization/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/outside the physical range/);
  });

  test("a session without a characterization report says so explicitly", async () => {
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({
      lightCurveResult: { ...LIGHT_CURVE_RESULT, characterization: undefined },
      finalResult: FINAL_RESULT, manualParameters: {},
    }));
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Detection & Prediction" }));
    expect(await screen.findByText(/No characterization report is attached/i)).toBeInTheDocument();
  });
});

describe("Light-curve chart hover", () => {
  test("highlights the bin under the pointer, in SVG coordinates", async () => {
    const { default: TransitLightCurveChart } = await import("../src/components/charts/TransitLightCurveChart");
    const folded = REPORT.transit_fit.folded;
    render(<TransitLightCurveChart folded={folded} />);
    const svg = screen.getByRole("img", { name: /Phase-folded transit light curve/ });
    // Simulate an SVG drawn at 2x its viewBox width, offset 100 px from the page edge.
    svg.getScreenCTM = () => ({ a: 2, d: 2, e: 100, f: 0 });
    const points = svg.querySelectorAll("circle.chart-point");
    const target = 10;
    const cx = Number(points[target].getAttribute("cx"));
    fireEvent.mouseMove(svg.querySelector("rect.chart-hit"), { clientX: 100 + cx * 2, clientY: 50 });
    expect(points[target].getAttribute("class")).toContain("is-active");
    expect(screen.getByRole("status")).toHaveTextContent(`${folded.phase_hours[target] >= 0 ? "+" : ""}${folded.phase_hours[target].toFixed(2)} h`);
  });
});

describe("Illustrative planet above Key findings", () => {
  test("maps the engine's composition category to an archetype, labelled as illustrative", async () => {
    const { planetArchetype } = await import("../src/components/charts/PlanetPreview");
    expect(planetArchetype(REPORT).key).toBe("subneptune");           // fixture: Volatile-rich sub-Neptune candidate
    const as = (category) => ({ classifications: [{ name: "composition_candidate", status: "computed", category }] });
    expect(planetArchetype(as("Rocky / terrestrial candidate")).key).toBe("rocky");
    expect(planetArchetype(as("Neptune-like (ice/gas giant) candidate")).key).toBe("neptune");
    expect(planetArchetype(as("Gas-giant candidate")).key).toBe("giant");
    // Never drawn without a computed category, or for an object too large to be a planet.
    expect(planetArchetype({ classifications: [] }).key).toBeNull();
    expect(planetArchetype({ classifications: [
      { name: "size_category", status: "computed", category: "Exceeds planetary radii (~2 R_Jup): likely stellar companion" },
      { name: "composition_candidate", status: "computed", category: "Gas-giant candidate" },
    ] }).key).toBeNull();
  });

  test("renders above Key findings with its basis stated", async () => {
    seedSession();
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Planet Characterization" }));
    const insights = await screen.findByTestId("char-insights");
    const preview = within(insights).getByTestId("planet-preview");
    expect(preview).toHaveTextContent("Sub-Neptune");
    expect(preview).toHaveTextContent(/Illustrative only.*not an image of the planet/);
    expect(within(preview).getByRole("img", { name: /Illustration of a sub-neptune/i })).toBeInTheDocument();
    // It sits before the Key findings block.
    const blocks = insights.querySelectorAll(".insight-block");
    expect(blocks[0]).toContainElement(preview);
    expect(blocks[1]).toHaveTextContent("Key findings");
  });
});
