import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, test, beforeEach } from "vitest";
import App from "../src/App";

const SESSION_KEY = "exoplanet_prediction_session_v1";

// A light-curve result where every one of the 17 real model features was
// resolved automatically (light curve + catalog identifier) -- the ML
// service already ran the real prediction as part of the CSV-upload
// response, so Step 2 should be entirely invisible to the user.
const FAKE_READY_RESULT = {
  dataset_type: "light_curve",
  filename: "kepler_227b_like.csv",
  diagnostics: {
    n_points_used: 6000, n_points_dropped: 0, baseline_days: 80,
    bls_period_days: 8.0, bls_duration_hours: 2.4, bls_depth_ppm: 950,
    bls_transit_snr: 12.0, num_transits_observed: 9,
  },
  extracted_features: {},
  suggested_parameters: { koi_period: 8.0, koi_time0bk: 4.0, koi_duration: 2.4, koi_depth: 950, koi_model_snr: 12.0 },
  characterisation: {
    status: "computed", bls_period_days: 8.0, bls_duration_hours: 2.4, bls_depth_ppm: 950,
    bls_transit_snr: 12.0, num_transits_observed: 9, odd_even_depth_ratio: 1.0,
    secondary_eclipse_depth_ppm: 1.0, note: "note",
  },
  physics_validation: { status: "not_implemented", message: "later" },
  warnings: [],
  object_id: "K00752.01",
  catalog_resolution: { requested_identifier: "K00752.01", identifier_type: "koi_name", match_status: "matched_koi", note: "Matched KOI name K00752.01." },
  missing_features: [],
  ready_for_prediction: true,
  features: {
    koi_score: { value: 1.0, unit: "", source: "nasa_koi_catalog", status: "catalog", note: "n" },
    koi_period: { value: 8.0, unit: "days", source: "box_least_squares", status: "estimated", note: "n" },
  },
  prediction: {
    prediction: 1, weighted_probability: 0.91, random_forest_probability: 0.9,
    cnn_probability: 0.92, weights: { random_forest: 0.5, cnn: 0.5 }, model_version: "1.0",
  },
};

beforeEach(() => {
  window.sessionStorage.setItem(
    SESSION_KEY,
    JSON.stringify({ lightCurveResult: FAKE_READY_RESULT })
  );
});

describe("zero-manual-entry auto-skip", () => {
  test("visiting Manual Parameters with a fully-resolved result lands on Results without user input", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: /Manual Parameters/i }));

    expect(await screen.findByRole("heading", { name: /Transit Detection & ML Prediction/i })).toBeInTheDocument();
    expect(screen.getByText("Predicted class")).toBeInTheDocument();
  });
});
