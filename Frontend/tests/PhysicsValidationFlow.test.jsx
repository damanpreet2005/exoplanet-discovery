import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, test, vi, beforeEach, afterEach } from "vitest";
import App from "../src/App";

const SESSION_KEY = "exoplanet_prediction_session_v1";

const FAKE_LIGHT_CURVE_RESULT = {
  dataset_type: "light_curve",
  filename: "kepler_001.csv",
  object_id: "KIC 11904151",
  diagnostics: {
    n_points_used: 3000, n_points_dropped: 0, baseline_days: 40,
    bls_period_days: 5.0, bls_duration_hours: 2.88, bls_depth_ppm: 8000,
    bls_transit_snr: 12.5, num_transits_observed: 7,
  },
  extracted_features: {},
  suggested_parameters: {},
  characterisation: {
    status: "computed", bls_period_days: 5.0, bls_duration_hours: 2.88, bls_depth_ppm: 8000,
    bls_transit_snr: 12.5, num_transits_observed: 7, odd_even_depth_ratio: 1.02,
    secondary_eclipse_depth_ppm: 5.0, note: "note",
  },
  physics_validation: { status: "not_implemented", message: "later" },
  warnings: [],
};

const FAKE_FINAL_RESULT = {
  prediction: 1, weighted_probability: 0.9, random_forest_probability: 0.88,
  cnn_probability: 0.92, weights: { random_forest: 0.5, cnn: 0.5 }, model_version: "1.0",
};

const FAKE_MANUAL_PARAMETERS = {
  koi_score: 1.0, koi_period: 365.25, koi_time0bk: 170.5, koi_impact: 0.0,
  koi_duration: 13.0, koi_depth: 83.9, koi_prad: 1.0, koi_teq: 278.0,
  koi_insol: 1.0, koi_model_snr: 20.0, koi_tce_plnt_num: 1, koi_steff: 5772.0,
  koi_slogg: 4.438, koi_srad: 1.0, ra: 291.9, dec: 48.1, koi_kepmag: 15.0,
};

const FAKE_PHYSICS_REPORT = {
  object_id: "KIC 11904151",
  overall_status: "PASS",
  summary: {
    tests_passed: 3, tests_review_required: 0, tests_not_evaluated: 0,
    message: "3 of 3 test(s) passed, 0 require investigation, 0 could not be evaluated.",
  },
  tests: [
    {
      test_id: "planet_size", name: "Planet Size Validation", status: "PASS",
      summary: "Observed transit depth is consistent.",
      observed: { transit_depth: { value: 83.9, unit: "ppm" } },
      expected: { transit_depth: { value: 83.9, unit: "ppm" } },
      discrepancy: { absolute: { value: 0.1, unit: "ppm" }, relative: 0.001, relative_valid: true, note: "x" },
      tolerance: { relative_tolerance: 0.3, rationale: "r" },
      assumptions: ["a1"],
      missing_data: [],
      calculation: { equation: "eq", inputs: {}, derived: {} },
      consistency_checks: [],
    },
    {
      test_id: "transit_duration", name: "Transit Duration Validation", status: "PASS",
      summary: "Observed duration is consistent.",
      observed: { transit_duration: { value: 13.0, unit: "hours" } },
      expected: { transit_duration: { value: 13.0, unit: "hours" } },
      discrepancy: { absolute: { value: 0.0, unit: "hours" }, relative: 0.0, relative_valid: true, note: "x" },
      tolerance: { relative_tolerance: 0.25, rationale: "r" },
      assumptions: ["a2"],
      missing_data: [],
      calculation: { equation: "eq", inputs: {}, derived: {} },
      consistency_checks: [],
    },
    {
      test_id: "orbital_physics", name: "Orbital Physics Validation", status: "PASS",
      summary: "Orbit is self-consistent.",
      observed: { orbital_period: { value: 365.25, unit: "days" } },
      expected: {},
      discrepancy: null,
      tolerance: { relative_tolerance: null, rationale: "r" },
      assumptions: ["a3"],
      missing_data: [],
      calculation: { equation: "eq", inputs: {}, derived: { stellar_mass: { value: 1.0, unit: "Solar masses" } } },
      consistency_checks: ["a/Rstar > 1: the orbit is larger than the star, as required."],
    },
  ],
  issues: [],
  recommendations: [],
  generated_at: "2026-01-01T00:00:00+00:00",
};

function seedSession(overrides = {}) {
  window.sessionStorage.setItem(
    SESSION_KEY,
    JSON.stringify({
      lightCurveResult: FAKE_LIGHT_CURVE_RESULT,
      finalResult: FAKE_FINAL_RESULT,
      manualParameters: FAKE_MANUAL_PARAMETERS,
      ...overrides,
    })
  );
}

describe("Physics Validation workflow", () => {
  let originalFetch;

  beforeEach(() => {
    originalFetch = global.fetch;
    window.history.pushState({}, "", "/");
  });

  afterEach(() => {
    global.fetch = originalFetch;
    window.sessionStorage.clear();
  });

  test("clicking Start Physics Validation on the results page calls the backend and navigates to the dashboard", async () => {
    seedSession();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => FAKE_PHYSICS_REPORT,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: /Results/i }));
    await screen.findByRole("heading", { name: /Step 3.*Prediction Results/i });

    fireEvent.click(screen.getByRole("button", { name: /Start Physics Validation/i }));

    await screen.findByRole("heading", { name: /Physics Validation/i });

    // Real backend values are shown, not fabricated/hardcoded placeholders.
    expect(await screen.findByText(/Planet Size Validation/i)).toBeInTheDocument();
    expect(screen.getByText(/Transit Duration Validation/i)).toBeInTheDocument();
    expect(screen.getByText(/Orbital Physics Validation/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Pass/i).length).toBeGreaterThan(0);

    const physicsCall = global.fetch.mock.calls.find(([url]) => url.includes("/api/v1/physics-validation"));
    expect(physicsCall).toBeDefined();
    const [, options] = physicsCall;
    const body = JSON.parse(options.body);
    expect(body.koi_period).toBe(365.25);
    expect(body.object_id).toBe("KIC 11904151");
  });

  test("navigating directly to the physics-validation route without clicking Start shows the prompt, not fabricated results", async () => {
    seedSession();
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ features: [], order_configured: true }) });

    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: /Physics Validation/i }));

    expect(await screen.findByText(/Run Stage 2 Physics Validation/i)).toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url]) => url.includes("/api/v1/physics-validation"))).toBe(false);
  });

  test("a backend error on the dashboard shows an error state with a retry option, never a silent failure", async () => {
    seedSession();
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ error: { code: "ML_SERVICE_UNAVAILABLE", message: "down" } }),
    });

    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: /Physics Validation/i }));
    fireEvent.click(await screen.findByRole("button", { name: /Start Physics Validation/i }));

    expect(await screen.findByText(/down/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retry/i })).toBeInTheDocument();
  });

  test("starting a new prediction clears the previous physics report so a new candidate never shows stale results", async () => {
    seedSession({ physicsResult: FAKE_PHYSICS_REPORT, physicsCandidateKey: JSON.stringify(FAKE_MANUAL_PARAMETERS, Object.keys(FAKE_MANUAL_PARAMETERS).sort()) });
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ features: [], order_configured: true }) });

    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: /Results/i }));
    await screen.findByRole("heading", { name: /Step 3.*Prediction Results/i });

    // The previously-computed, matching report is recognized as current.
    expect(screen.getByRole("button", { name: /View Physics Validation/i })).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: /New Prediction/i })[0]);
    await screen.findByRole("heading", { name: /Step 1.*Upload Light Curve/i });

    expect(JSON.parse(window.sessionStorage.getItem(SESSION_KEY) || "null")).toBeNull();
  });
});
