import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, test, beforeEach } from "vitest";
import App from "../src/App";

const SESSION_KEY = "exoplanet_prediction_session_v1";
const INVALID_OBJECT_ID = "86789987";

// A light-curve result for an Object ID that doesn't resolve to any NASA
// Exoplanet Archive catalog entry -- the exact shape ml_service's
// stellar_catalog_service returns for an unknown KIC number.
const FAKE_NOT_FOUND_RESULT = {
  dataset_type: "light_curve",
  filename: "unknown_object.csv",
  diagnostics: {
    n_points_used: 4000, n_points_dropped: 0, baseline_days: 60,
    bls_period_days: 6.0, bls_duration_hours: 3.1, bls_depth_ppm: 700,
    bls_transit_snr: 10.0, num_transits_observed: 8,
  },
  extracted_features: {},
  suggested_parameters: { koi_period: 6.0, koi_time0bk: 3.0, koi_duration: 3.1, koi_depth: 700, koi_model_snr: 10.0 },
  characterisation: {
    status: "computed", bls_period_days: 6.0, bls_duration_hours: 3.1, bls_depth_ppm: 700,
    bls_transit_snr: 10.0, num_transits_observed: 8, odd_even_depth_ratio: 1.0,
    secondary_eclipse_depth_ppm: 1.0, note: "note",
  },
  physics_validation: { status: "not_implemented", message: "later" },
  warnings: [],
  object_id: INVALID_OBJECT_ID,
  catalog_resolution: {
    requested_identifier: INVALID_OBJECT_ID,
    identifier_type: "kic",
    match_status: "not_found",
    note: `No catalog entry found for KIC ${INVALID_OBJECT_ID}.`,
  },
  missing_features: [],
  ready_for_prediction: false,
};

beforeEach(() => {
  window.sessionStorage.setItem(
    SESSION_KEY,
    JSON.stringify({ lightCurveResult: FAKE_NOT_FOUND_RESULT })
  );
});

describe("invalid Object ID -> 'Wrong Input? Try Again'", () => {
  test("an unresolved Object ID shows the catalog error and the retry button underneath it", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: /Manual Parameters/i }));

    expect(await screen.findByRole("heading", { name: "Object Information" })).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`Stellar information unavailable for Object ID ${INVALID_OBJECT_ID}`))).toBeInTheDocument();
    expect(screen.getByText(`No catalog entry found for KIC ${INVALID_OBJECT_ID}.`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Wrong Input\? Try Again/i })).toBeInTheDocument();
  });

  test("clicking the retry button returns to Upload & Analysis with a clean Object ID field and no stale error", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: /Manual Parameters/i }));
    const retryButton = await screen.findByRole("button", { name: /Wrong Input\? Try Again/i });

    fireEvent.click(retryButton);

    expect(await screen.findByRole("heading", { name: /^Upload Light Curve$/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Object ID/i)).toHaveValue("");
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();

    // The stale not-found session must actually be gone, not just hidden --
    // navigating back to Manual Parameters should bounce to Step 1 again.
    fireEvent.click(screen.getByRole("link", { name: /Manual Parameters/i }));
    expect(await screen.findByRole("heading", { name: /^Upload Light Curve$/i })).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(`Stellar information unavailable for Object ID ${INVALID_OBJECT_ID}`))).not.toBeInTheDocument();
  });
});
