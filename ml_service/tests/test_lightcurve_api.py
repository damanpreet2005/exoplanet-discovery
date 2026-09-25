import io

import numpy as np
import pytest

TRUE_PERIOD = 5.0
TRUE_DURATION_DAYS = 0.12
TRUE_DEPTH = 0.01


def make_light_curve_csv(seed=0, n_points=3000, baseline_days=40.0):
    rng = np.random.default_rng(seed)
    time = np.linspace(0, baseline_days, n_points)
    flux = np.ones_like(time)
    phase = np.mod(time, TRUE_PERIOD)
    in_transit = (phase < TRUE_DURATION_DAYS / 2) | (phase > TRUE_PERIOD - TRUE_DURATION_DAYS / 2)
    flux[in_transit] -= TRUE_DEPTH
    flux += rng.normal(0, 0.0008, size=time.shape)
    lines = ["time,flux"] + [f"{t},{f}" for t, f in zip(time, flux)]
    return io.BytesIO(("\n".join(lines) + "\n").encode("utf-8"))


def test_valid_lightcurve_csv_alone_returns_analysis_not_a_prediction(client):
    """No stellar params, no extra fields -- just the CSV. This is stage-1
    analysis only: it must NOT contain a prediction (see
    LightCurveAnalysisResponse's docstring for why the real model, whose 17
    features are KOI catalog values, is never called from a light curve
    alone)."""
    files = {"file": ("kepler_001.csv", make_light_curve_csv(), "text/csv")}
    resp = client.post("/predict/csv", files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["dataset_type"] == "light_curve"
    assert body["filename"] == "kepler_001.csv"
    assert "prediction" not in body
    assert "weighted_probability" not in body
    assert "cache_hit" not in body
    assert body["diagnostics"]["bls_period_days"] == pytest.approx(TRUE_PERIOD, rel=0.15)
    assert len(body["extracted_features"]) == 17
    assert body["characterisation"]["status"] == "computed"
    assert "estimated_planet_radius_rearth" not in body["characterisation"]
    assert body["physics_validation"]["status"] == "not_implemented"
    assert any("best-effort" in w.lower() for w in body["warnings"])

    # Suggested parameters: only the 5 fields a transit search can inform,
    # and koi_period should be close to the real injected period.
    suggested = body["suggested_parameters"]
    assert set(suggested.keys()) == {
        "koi_period", "koi_time0bk", "koi_duration", "koi_depth", "koi_model_snr",
    }
    assert suggested["koi_period"] == pytest.approx(TRUE_PERIOD, rel=0.15)


def test_missing_time_flux_columns_returns_422(client):
    files = {"file": ("bad.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")}
    resp = client.post("/predict/csv", files=files)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "CSV_VALIDATION_ERROR"


def test_too_few_points_returns_422(client):
    raw = b"time,flux\n" + b"\n".join(f"{i},1.0".encode() for i in range(5))
    files = {"file": ("short.csv", io.BytesIO(raw), "text/csv")}
    resp = client.post("/predict/csv", files=files)
    assert resp.status_code == 422


def test_empty_csv_returns_422(client):
    files = {"file": ("empty.csv", io.BytesIO(b""), "text/csv")}
    resp = client.post("/predict/csv", files=files)
    assert resp.status_code == 422


def test_no_file_returns_422(client):
    resp = client.post("/predict/csv")
    assert resp.status_code == 422


def test_repeated_upload_gives_deterministic_analysis(client):
    # No prediction is run at this stage, so there is nothing to cache --
    # confirm the same light curve just deterministically re-analyzes the
    # same way rather than exposing a stale/irrelevant cache_hit flag.
    csv_bytes = make_light_curve_csv(seed=42).getvalue()
    files1 = {"file": ("dup.csv", io.BytesIO(csv_bytes), "text/csv")}
    files2 = {"file": ("dup.csv", io.BytesIO(csv_bytes), "text/csv")}
    resp1 = client.post("/predict/csv", files=files1)
    resp2 = client.post("/predict/csv", files=files2)
    assert "cache_hit" not in resp1.json()
    assert resp1.json()["diagnostics"]["bls_period_days"] == resp2.json()["diagnostics"]["bls_period_days"]
