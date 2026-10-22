import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, expect, test, vi, beforeEach, afterEach } from "vitest";
import App from "../src/App";
import REPORT from "./fixtures/characterization_report.json";

const SESSION_KEY = "exoplanet_prediction_session_v1";

const MANUAL = { koi_period: 9.488, koi_srad: 0.927, koi_steff: 5455, koi_score: 0.9 };

const LIGHT_CURVE_RESULT = {
  dataset_type: "light_curve",
  filename: "k227.csv",
  object_id: "K00752.01",
  diagnostics: {
    n_points_used: 4900, n_points_dropped: 0, baseline_days: 100,
    bls_period_days: 9.488, bls_duration_hours: 2.6, bls_depth_ppm: 479,
    bls_transit_snr: 28.72, bls_noise_ppm: 150.3, bls_n_in_transit: 77, bls_sde: 14.2, num_transits_observed: 10,
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
  catalog_resolution: {
    requested_identifier: "K00752.01", identifier_type: "koi_name", match_status: "matched_koi",
    matched_kepid: 10797460, matched_kepoi_name: "K00752.01", matched_kepler_name: "Kepler-227 b",
    n_candidate_rows: 1, note: "Matched.",
  },
  features: {
    koi_period: { value: 9.488, unit: "days", source: "bls", status: "estimated", note: "" },
    koi_srad: { value: 0.927, unit: "Solar radii", source: "nasa_koi_catalog", status: "catalog", note: "" },
    koi_steff: { value: 5455, unit: "K", source: "nasa_koi_catalog", status: "catalog", note: "" },
    koi_score: { value: null, unit: "", source: "", status: "unavailable", note: "" },
  },
  characterization: REPORT,
};

const FINAL_RESULT = {
  prediction: 1, weighted_probability: 0.9, random_forest_probability: 0.88,
  cnn_probability: 0.92, weights: { random_forest: 0.5, cnn: 0.5 }, model_version: "1.0",
};

const PHYSICS = {
  object_id: "K00752.01", overall_status: "REVIEW_REQUIRED",
  summary: { tests_passed: 2, tests_review_required: 1, tests_not_evaluated: 0, message: "2 of 3 test(s) passed, 1 require investigation, 0 could not be evaluated." },
  tests: [
    { test_id: "planet_size", name: "Planet Size Validation", status: "PASS", summary: "Depth consistent." },
    { test_id: "transit_duration", name: "Transit Duration Validation", status: "REVIEW_REQUIRED", summary: "Duration differs by 40%." },
    { test_id: "orbital_physics", name: "Orbital Physics Validation", status: "PASS", summary: "Orbit consistent." },
  ],
  issues: [], recommendations: [], generated_at: "2026-01-01T00:00:00+00:00",
};

function seed(extra = {}) {
  window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({
    lightCurveResult: LIGHT_CURVE_RESULT, finalResult: FINAL_RESULT, manualParameters: MANUAL, ...extra,
  }));
}

const CURRENT_KEY = JSON.stringify(MANUAL, Object.keys(MANUAL).sort());

describe("Final Discovery Report", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    window.history.pushState({}, "", "/");
  });
  afterEach(() => {
    global.fetch = originalFetch;
    window.sessionStorage.clear();
  });

  test("consolidates the real outputs of every stage, with links back to them", async () => {
    seed({ physicsResult: PHYSICS, physicsCandidateKey: CURRENT_KEY });
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Discovery Report" }));
    await screen.findByRole("heading", { name: "Final Discovery Report" });

    expect(screen.getByTestId("report-overview")).toHaveTextContent(REPORT.classifications[0].category);
    expect(screen.getByTestId("report-overview")).toHaveTextContent(REPORT.parameters.planet_radius.display);
    expect(screen.getByTestId("report-prediction")).toHaveTextContent("90.0%");
    const physics = screen.getByTestId("report-physics");
    expect(physics).toHaveTextContent(PHYSICS.summary.message);
    expect(within(physics).getByText("Transit Duration Validation")).toBeInTheDocument();
    expect(screen.getByTestId("report-characterization")).toHaveTextContent(REPORT.parameters.planet_mass.display);

    // A REVIEW_REQUIRED check is evidence against, never counted as support.
    expect(screen.getByTestId("report-evidence")).toHaveTextContent("Transit Duration Validation: Duration differs by 40%.");
    // Candidate status is never overstated.
    expect(screen.getByTestId("report-limitations")).toHaveTextContent(/Neither the classifier score nor the physics checks confirm it as a planet/);
    expect(screen.getByTestId("report-limitations")).toHaveTextContent(/Low-confidence or unreliable values .*Planet mass/);

    expect(within(screen.getByTestId("report-physics")).getByRole("link", { name: /View details/ })).toHaveAttribute("href", "/physics-validation");
    expect(within(screen.getByTestId("report-characterization")).getByRole("link", { name: /View details/ })).toHaveAttribute("href", "/characterisation");
  });

  test("says physics validation was not run instead of inventing a result", async () => {
    seed();
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Discovery Report" }));
    expect(await screen.findByTestId("report-physics")).toHaveTextContent(/Not run for the submitted parameters/);
    expect(screen.getByTestId("report-limitations")).toHaveTextContent(/Physics validation has not been run/);
  });

  test("a stale physics report from different parameters is not shown", async () => {
    seed({ physicsResult: PHYSICS, physicsCandidateKey: "{\"other\":1}" });
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Discovery Report" }));
    expect(await screen.findByTestId("report-physics")).toHaveTextContent(/Not run/);
    expect(screen.queryByText(PHYSICS.summary.message)).not.toBeInTheDocument();
  });

  test("is unavailable before a completed prediction", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Discovery Report" }));
    expect(await screen.findByText(/Available after a completed prediction/)).toBeInTheDocument();
  });
});

describe("Transit Detection & ML Prediction page", () => {
  test("an unavailable BLS SNR is shown as unavailable, never as a number", async () => {
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({
      lightCurveResult: { ...LIGHT_CURVE_RESULT, diagnostics: { ...LIGHT_CURVE_RESULT.diagnostics, bls_transit_snr: null, bls_noise_ppm: null } },
      finalResult: FINAL_RESULT, manualParameters: MANUAL,
    }));
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Detection & Prediction" }));
    const cell = await screen.findByTestId("bls-snr");
    expect(cell).toHaveTextContent("Unavailable");
    expect(cell).not.toHaveTextContent("threshold");
    expect(screen.getByTestId("bls-snr-definition")).toHaveTextContent(/per-point noise could not be estimated/);
    window.sessionStorage.clear();
  });

  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    window.history.pushState({}, "", "/");
  });
  afterEach(() => {
    global.fetch = originalFetch;
    window.sessionStorage.clear();
  });

  test("lower sections are structured panels with attributed inputs, not raw JSON", async () => {
    seed();
    global.fetch = vi.fn().mockImplementation(async (url) => ({
      ok: true,
      json: async () => (String(url).includes("feature-schema")
        ? { order_configured: true, features: [
          { canonical: "koi_period", display: "Orbital Period", unit: "days" },
          { canonical: "koi_srad", display: "Stellar Radius", unit: "Solar radii" },
          { canonical: "koi_steff", display: "Stellar Effective Temperature", unit: "K" },
          { canonical: "koi_score", display: "KOI Score", unit: "" },
        ] }
        : {}),
    }));
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Detection & Prediction" }));
    await screen.findByRole("heading", { name: /Transit Detection & ML Prediction/ });

    expect(screen.getByTestId("results-target")).toHaveTextContent("Kepler-227 b");
    expect(screen.getByTestId("results-detection").querySelector("[data-testid='transit-lightcurve-chart']")).not.toBeNull();
    expect(screen.getByTestId("results-findings")).toHaveTextContent(/ML ensemble predicts class 1/);
    expect(screen.getByTestId("results-findings")).toHaveTextContent(/Physics validation not run/);
    // The BLS SNR is shown exactly as the backend computed it, with its definition.
    expect(screen.getByTestId("bls-snr")).toHaveTextContent("28.7");
    expect(screen.getByTestId("bls-snr")).toHaveTextContent("≥ 7.1 threshold");
    expect(screen.getByTestId("bls-snr-definition")).toHaveTextContent(/not an SNR, and\s+neither is a probability/);

    const inputs = screen.getByTestId("results-model-inputs");
    const radiusRow = (await within(inputs).findByText("Stellar Radius")).closest("tr");
    expect(radiusRow).toHaveTextContent("0.927");
    expect(radiusRow).toHaveTextContent("Catalogue");
    expect(within(inputs).getByText("Orbital Period").closest("tr")).toHaveTextContent("Light curve");
    // Filled in by the user where the automatic value was unavailable.
    expect(within(inputs).getByText("KOI Score").closest("tr")).toHaveTextContent("Manual entry");
    // Raw data only inside the collapsed developer view.
    expect(inputs.querySelector("details pre.raw-json")).not.toBeNull();
    expect(screen.queryByText("Step 3")).not.toBeInTheDocument();
  });
});

describe("Evidence separation for a catalogue-informed prediction", () => {
  // Pure noise uploaded under a confirmed planet's Object ID: the light curve
  // shows no significant transit, the classifier still says class 1 because of
  // the catalogue's koi_score.
  const NOISE_REPORT = JSON.parse(JSON.stringify(REPORT));
  NOISE_REPORT.parameters.transit_snr = { ...NOISE_REPORT.parameters.transit_snr, value: 5.0, display: "5.0", reliability: "unreliable" };
  const NOISE_RESULT = {
    ...LIGHT_CURVE_RESULT,
    diagnostics: { ...LIGHT_CURVE_RESULT.diagnostics, bls_transit_snr: 4.5, bls_noise_ppm: 150, bls_n_in_transit: 160, bls_sde: 5.8 },
    features: { ...LIGHT_CURVE_RESULT.features, koi_score: { value: 1.0, unit: "", source: "nasa_koi_catalog", status: "catalog", note: "" } },
    characterization: NOISE_REPORT,
  };
  const CATALOGUE_INFORMED = {
    ...FINAL_RESULT, weighted_probability: 0.929,
    catalog_dependence: { feature: "koi_score", value: 1.0, rf_importance: 0.576, neutral_value: 0.334, weighted_probability_with_neutral_value: 0.184 },
  };

  beforeEach(() => {
    window.history.pushState({}, "", "/");
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({
      lightCurveResult: NOISE_RESULT, finalResult: CATALOGUE_INFORMED, manualParameters: { ...MANUAL, koi_score: 1.0 },
    }));
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
  });
  afterEach(() => window.sessionStorage.clear());

  test("results page reports no detection and a catalogue-informed classification", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Detection & Prediction" }));
    const findings = await screen.findByTestId("results-findings");
    expect(findings).toHaveTextContent("No significant transit detected");
    expect(findings).not.toHaveTextContent("Significant transit detected");
    expect(findings).toHaveTextContent("ML ensemble predicts class 1 (catalogue-informed)");
    expect(screen.getByTestId("detection-chip")).toHaveTextContent("No significant transit detected");
    const dep = screen.getByTestId("catalog-dependence");
    expect(dep).toHaveTextContent("58% of the Random Forest's feature importance");
    expect(dep).toHaveTextContent("18.4%");
    expect(dep).toHaveTextContent(/not as independent evidence from the uploaded light curve/);
  });

  test("the report keeps the ML classification out of the light-curve evidence", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Discovery Report" }));
    const evidence = await screen.findByTestId("report-evidence");
    expect(evidence).toHaveTextContent(/Against or needing review.*No significant transit detected in the uploaded light curve/);
    expect(within(evidence).queryByText(/ML ensemble assigns/)).toBeNull();
    expect(screen.getByTestId("report-ml-evidence")).toHaveTextContent(/catalogue-informed.*not independent evidence/);
    expect(screen.getByTestId("report-overview")).toHaveTextContent("ML prediction (catalogue-informed)");
    expect(screen.getByTestId("report-limitations")).toHaveTextContent(/dominated by koi_score/);
  });
});
