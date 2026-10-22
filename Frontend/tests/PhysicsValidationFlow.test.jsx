import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, expect, test, vi, beforeEach, afterEach } from "vitest";
import App from "../src/App";

const SESSION_KEY = "exoplanet_prediction_session_v1";

// The Physics Validation dashboard typesets every equation with KaTeX -- the
// heaviest render in the app. Under a full parallel test run on a slow CI
// runner it can take longer than Testing Library's default 1 s wait (and the
// whole flow longer than Vitest's default 5 s per test), so both get headroom.
// They only lengthen a run that is genuinely failing.
const DASHBOARD_WAIT = { timeout: 10000 };
vi.setConfig({ testTimeout: 20000 });

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
    fireEvent.click(screen.getByRole("link", { name: "Detection & Prediction" }));
    await screen.findByRole("heading", { name: /Transit Detection & ML Prediction/i });

    fireEvent.click(screen.getByRole("button", { name: /Start Physics Validation/i }));

    await screen.findByRole("heading", { name: /Physics Validation/i }, DASHBOARD_WAIT);

    // Real backend values are shown, not fabricated/hardcoded placeholders.
    expect(await screen.findByText(/Planet Size Validation/i, {}, DASHBOARD_WAIT)).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("link", { name: "Physics Validation" }));

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
    fireEvent.click(screen.getByRole("link", { name: "Physics Validation" }));
    fireEvent.click(await screen.findByRole("button", { name: /Start Physics Validation/i }));

    expect(await screen.findByText(/down/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retry/i })).toBeInTheDocument();
  });

  test("starting a new prediction clears the previous physics report so a new candidate never shows stale results", async () => {
    seedSession({ physicsResult: FAKE_PHYSICS_REPORT, physicsCandidateKey: JSON.stringify(FAKE_MANUAL_PARAMETERS, Object.keys(FAKE_MANUAL_PARAMETERS).sort()) });
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ features: [], order_configured: true }) });

    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Detection & Prediction" }));
    await screen.findByRole("heading", { name: /Transit Detection & ML Prediction/i });

    // The previously-computed, matching report is recognized as current.
    expect(screen.getByRole("button", { name: /View Physics Validation/i })).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: /New Prediction/i })[0]);
    await screen.findByRole("heading", { name: /^Upload Light Curve$/i });

    expect(JSON.parse(window.sessionStorage.getItem(SESSION_KEY) || "null")).toBeNull();
  });
  test("each stage renders its equation, the actual input values, and never shows Pass for an unevaluated check", async () => {
    const report = JSON.parse(JSON.stringify(FAKE_PHYSICS_REPORT));
    report.tests[0].calculation = {
      equation: "delta_ppm ~= ...",
      inputs: {
        koi_depth: { value: 83.9, unit: "ppm" },
        koi_prad: { value: 1.0, unit: "Earth radii" },
        koi_srad: { value: 1.0, unit: "Solar radii" },
      },
      derived: { radius_ratio_k: { value: 0.0091577, unit: "Rp/Rstar" }, expected_depth: { value: 83.86, unit: "ppm" } },
    };
    report.tests[0].expected = { transit_depth: { value: 83.86, unit: "ppm" } };
    report.tests[1] = {
      ...report.tests[1], status: "NOT_EVALUATED", summary: "Could not be evaluated: koi_impact is missing.",
      expected: {}, discrepancy: null, missing_data: ["koi_impact"],
    };
    report.overall_status = "PARTIAL";
    seedSession({
      physicsResult: report,
      physicsCandidateKey: JSON.stringify(FAKE_MANUAL_PARAMETERS, Object.keys(FAKE_MANUAL_PARAMETERS).sort()),
    });
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });

    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Physics Validation" }));
    const stage = await screen.findByTestId("physics-stage-planet_size", {}, DASHBOARD_WAIT);

    // Rendered mathematics, not a plain-text equation string.
    expect(stage.querySelector(".stage-equation .katex")).not.toBeNull();
    expect(stage).not.toHaveTextContent("delta_ppm ~=");
    // Parameter table shows the value the backend actually used, its unit and its source.
    const depthRow = within(stage).getByText("Observed transit depth").closest("tr");
    expect(depthRow).toHaveTextContent("83.9");
    expect(depthRow).toHaveTextContent("ppm");
    expect(depthRow).toHaveTextContent("Manual entry");
    expect(within(stage).getByText("Planet radius").closest("tr")).toHaveTextContent("R⊕");
    // Result area: observed vs expected from the report, with the stated tolerance.
    const result = screen.getByTestId("physics-result-planet_size");
    expect(result).toHaveTextContent("83.86 ppm");
    expect(result).toHaveTextContent("≤ 30% relative");

    const unevaluated = screen.getByTestId("physics-result-transit_duration");
    expect(unevaluated).toHaveTextContent(/Not evaluated/);
    expect(unevaluated).toHaveTextContent("koi_impact");
    expect(within(unevaluated).queryByText("Pass")).toBeNull();
    const impactRow = within(screen.getByTestId("physics-stage-transit_duration")).getByText("Impact parameter").closest("tr");
    expect(impactRow).toHaveTextContent(/Missing/);
  });
});

describe("Circular Planet Size check", () => {
  afterEach(() => window.sessionStorage.clear());

  test("is flagged as not independent when Rp was derived from the depth", async () => {
    const lc = {
      ...FAKE_LIGHT_CURVE_RESULT,
      features: {
        koi_prad: { value: 1.0, unit: "Earth radii", source: "derived_rp_eq_rstar_sqrt_depth", status: "derived", note: "" },
        koi_depth: { value: 83.9, unit: "ppm", source: "box_least_squares", status: "estimated", note: "" },
      },
    };
    window.history.pushState({}, "", "/");
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({
      lightCurveResult: lc, finalResult: FAKE_FINAL_RESULT, manualParameters: FAKE_MANUAL_PARAMETERS,
      physicsResult: FAKE_PHYSICS_REPORT,
      physicsCandidateKey: JSON.stringify(FAKE_MANUAL_PARAMETERS, Object.keys(FAKE_MANUAL_PARAMETERS).sort()),
    }));
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Physics Validation" }));
    const stage = await screen.findByTestId("physics-stage-planet_size", {}, DASHBOARD_WAIT);
    expect(within(stage).getByTestId("physics-circular")).toHaveTextContent("Not independent");
    expect(stage).toHaveTextContent(/cannot fail/);
    expect(screen.getByTestId("physics-stage-transit_duration").querySelector("[data-testid='physics-circular']")).toBeNull();
  });

  test("is not flagged when the radius was supplied independently", async () => {
    const lc = { ...FAKE_LIGHT_CURVE_RESULT, features: {
      koi_prad: { value: 2.0, unit: "Earth radii", source: "derived_rp_eq_rstar_sqrt_depth", status: "derived", note: "" },
      koi_depth: { value: 83.9, unit: "ppm", source: "box_least_squares", status: "estimated", note: "" },
    } };   // submitted koi_prad (1.0) differs from the derived 2.0 -> user-entered
    window.history.pushState({}, "", "/");
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({
      lightCurveResult: lc, finalResult: FAKE_FINAL_RESULT, manualParameters: FAKE_MANUAL_PARAMETERS,
      physicsResult: FAKE_PHYSICS_REPORT,
      physicsCandidateKey: JSON.stringify(FAKE_MANUAL_PARAMETERS, Object.keys(FAKE_MANUAL_PARAMETERS).sort()),
    }));
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Physics Validation" }));
    const stage = await screen.findByTestId("physics-stage-planet_size", {}, DASHBOARD_WAIT);
    expect(within(stage).queryByTestId("physics-circular")).toBeNull();
  });
});

describe("Physics result formatting", () => {
  afterEach(() => window.sessionStorage.clear());

  test("an exact match shows a residual of 0, not floating-point noise", async () => {
    const report = JSON.parse(JSON.stringify(FAKE_PHYSICS_REPORT));
    report.tests[0].observed.transit_depth.value = 495.9;
    report.tests[0].expected.transit_depth.value = 495.9;
    report.tests[0].discrepancy.absolute = { value: 5.684e-14, unit: "ppm" };
    window.history.pushState({}, "", "/");
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({
      lightCurveResult: FAKE_LIGHT_CURVE_RESULT, finalResult: FAKE_FINAL_RESULT, manualParameters: FAKE_MANUAL_PARAMETERS,
      physicsResult: report,
      physicsCandidateKey: JSON.stringify(FAKE_MANUAL_PARAMETERS, Object.keys(FAKE_MANUAL_PARAMETERS).sort()),
    }));
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Physics Validation" }));
    const result = await screen.findByTestId("physics-result-planet_size", {}, DASHBOARD_WAIT);
    expect(result).toHaveTextContent(/Residual\s*0 ppm/);
    expect(result).not.toHaveTextContent("e-14");
  });
});
