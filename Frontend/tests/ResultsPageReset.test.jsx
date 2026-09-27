import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, test, beforeEach } from "vitest";
import App from "../src/App";

const SESSION_KEY = "exoplanet_prediction_session_v1";

const FAKE_LIGHT_CURVE_RESULT = {
  dataset_type: "light_curve",
  filename: "kepler_001.csv",
  diagnostics: {
    n_points_used: 3000, n_points_dropped: 0, baseline_days: 40,
    bls_period_days: 5.0, bls_duration_hours: 2.88, bls_depth_ppm: 8000,
    bls_transit_snr: 12.5, num_transits_observed: 7,
  },
  extracted_features: {},
  suggested_parameters: { koi_period: 5.0, koi_time0bk: 2.5, koi_duration: 2.88, koi_depth: 8000, koi_model_snr: 12.5 },
  characterisation: {
    status: "computed", bls_period_days: 5.0, bls_duration_hours: 2.88, bls_depth_ppm: 8000,
    bls_transit_snr: 12.5, num_transits_observed: 7, odd_even_depth_ratio: 1.02,
    secondary_eclipse_depth_ppm: 5.0, note: "note",
  },
  physics_validation: { status: "not_implemented", message: "later" },
  warnings: ["best-effort"],
};

const FAKE_FINAL_RESULT = {
  prediction: 1, weighted_probability: 0.9, random_forest_probability: 0.88,
  cnn_probability: 0.92, weights: { random_forest: 0.5, cnn: 0.5 }, model_version: "1.0",
};

const FAKE_MANUAL_PARAMETERS = { koi_score: 1.0, koi_period: 5.0 };

beforeEach(() => {
  window.sessionStorage.setItem(
    SESSION_KEY,
    JSON.stringify({
      lightCurveResult: FAKE_LIGHT_CURVE_RESULT,
      finalResult: FAKE_FINAL_RESULT,
      manualParameters: FAKE_MANUAL_PARAMETERS,
    })
  );
});

describe("ResultsPage 'New Prediction' reset", () => {
  test("a completed session renders the Results page directly (no redirect)", async () => {
    render(<App />);
    const resultsLink = screen.getByRole("link", { name: /Results/i });
    fireEvent.click(resultsLink);
    expect(await screen.findByRole("heading", { name: /Step 3.*Prediction Results/i })).toBeInTheDocument();
    expect(screen.getByText("Predicted class")).toBeInTheDocument();
  });

  test("clicking New Prediction clears the session and returns to Page 1", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: /Results/i }));
    await screen.findByRole("heading", { name: /Step 3.*Prediction Results/i });

    fireEvent.click(screen.getAllByRole("button", { name: /New Prediction/i })[0]);

    expect(await screen.findByRole("heading", { name: /Step 1.*Upload Light Curve/i })).toBeInTheDocument();
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();

    // And the cleared session actually redirects away from Results again.
    fireEvent.click(screen.getByRole("link", { name: /Results/i }));
    expect(await screen.findByRole("heading", { name: /Step 1.*Upload Light Curve/i })).toBeInTheDocument();
  });
});
