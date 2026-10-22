import io

import numpy as np
import pytest

from app import stellar_catalog_service as scs

TRUE_PERIOD = 5.0
TRUE_DURATION_DAYS = 0.12
TRUE_DEPTH = 0.01

# Catalogue lookups in this file are served by the real local KOI catalogue
# (ml_service/data/koi_catalog.csv) -- e.g. K00752.01 is Kepler-227 b on
# KIC 10797460; KIC 999999999 does not exist in it.


def make_catalog_unavailable(monkeypatch):
    from app.koi_catalog import KoiCatalogUnavailableError

    def raise_unavailable():
        raise KoiCatalogUnavailableError("KOI catalogue could not be opened")
    monkeypatch.setattr(scs, "get_koi_catalog", raise_unavailable)


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


def test_missing_object_id_returns_422_for_a_light_curve_upload(client):
    """Object ID is required for the light-curve path: the RF's 17 trained
    features genuinely include catalog-only fields a light curve alone
    cannot supply, so submitting without one must be a clear validation
    error, not a silently-degraded/partial analysis."""
    files = {"file": ("kepler_001.csv", make_light_curve_csv(), "text/csv")}
    resp = client.post("/predict/csv", files=files)
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "CSV_VALIDATION_ERROR"
    assert "Object ID" in body["error"]["message"]


def test_blank_object_id_returns_422(client):
    files = {"file": ("kepler_001.csv", make_light_curve_csv(), "text/csv")}
    resp = client.post("/predict/csv", files=files, data={"object_id": "   "})
    assert resp.status_code == 422
    assert "Object ID" in resp.json()["error"]["message"]


def test_overly_long_object_id_returns_422(client):
    files = {"file": ("kepler_001.csv", make_light_curve_csv(), "text/csv")}
    resp = client.post("/predict/csv", files=files, data={"object_id": "K" * 100})
    assert resp.status_code == 422


def test_unresolvable_object_id_returns_analysis_not_a_prediction(client):
    """A syntactically valid but unmatched Object ID: the stellar/catalog-only
    fields (koi_steff, koi_score, ...) stay unavailable and the real model
    must NOT be run on a partially-guessed vector (see
    LightCurveAnalysisResponse's docstring) -- no fabricated stellar values."""
    files = {"file": ("kepler_001.csv", make_light_curve_csv(), "text/csv")}
    resp = client.post("/predict/csv", files=files, data={"object_id": "KIC 999999999"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["dataset_type"] == "light_curve"
    assert body["filename"] == "kepler_001.csv"
    assert body["object_id"] == "KIC 999999999"
    assert body["catalog_resolution"]["match_status"] == "not_found"
    assert body["catalog_resolution"]["identifier_type"] == "kic"
    assert body["ready_for_prediction"] is False
    assert body["prediction"] is None
    assert body["diagnostics"]["bls_period_days"] == pytest.approx(TRUE_PERIOD, rel=0.15)
    assert len(body["extracted_features"]) == 17
    assert body["characterisation"]["status"] == "computed"
    assert "estimated_planet_radius_rearth" not in body["characterisation"]
    assert body["physics_validation"]["status"] == "not_implemented"
    assert any("best-effort" in w.lower() for w in body["warnings"])

    # New: the full, attributed 17-feature report. Light-curve-derived
    # fields should be resolved; catalog-only fields should be explicitly
    # unavailable, never fabricated.
    features = body["features"]
    assert set(features.keys()) == {
        "koi_score", "koi_period", "koi_time0bk", "koi_impact", "koi_duration", "koi_depth",
        "koi_prad", "koi_teq", "koi_insol", "koi_model_snr", "koi_tce_plnt_num", "koi_steff",
        "koi_slogg", "koi_srad", "ra", "dec", "koi_kepmag",
    }
    assert features["koi_period"]["status"] == "estimated"
    assert features["koi_period"]["value"] == pytest.approx(TRUE_PERIOD, rel=0.15)
    assert features["koi_tce_plnt_num"]["status"] == "derived"
    assert features["koi_tce_plnt_num"]["value"] == 1.0
    for canonical in ("koi_score", "koi_steff", "koi_slogg", "koi_srad", "ra", "dec", "koi_kepmag"):
        assert features[canonical]["status"] == "unavailable"
        assert features[canonical]["value"] is None
    # koi_prad/koi_teq/koi_insol cascade to unavailable without koi_srad/koi_steff.
    for canonical in ("koi_prad", "koi_teq", "koi_insol"):
        assert features[canonical]["status"] == "unavailable"
    # koi_impact too: with no catalogue match there is neither a catalogue b
    # nor a stellar-density prior to constrain a fitted one.
    assert set(body["missing_features"]) == {
        "koi_score", "koi_impact", "koi_prad", "koi_teq", "koi_insol", "koi_steff", "koi_slogg", "koi_srad",
        "ra", "dec", "koi_kepmag",
    }

    # Suggested parameters: only the 5 fields a transit search can inform,
    # and koi_period should be close to the real injected period.
    suggested = body["suggested_parameters"]
    assert set(suggested.keys()) == {
        "koi_period", "koi_time0bk", "koi_duration", "koi_depth", "koi_model_snr",
    }
    assert suggested["koi_period"] == pytest.approx(TRUE_PERIOD, rel=0.15)


def make_trapezoid_light_curve_csv(seed=0, n_points=6000, baseline_days=80.0,
                                    period=8.0, duration_days=0.15, depth=0.001,
                                    ingress_frac=0.2, noise=0.0002):
    rng = np.random.default_rng(seed)
    time = np.linspace(0, baseline_days, n_points)
    flux = np.ones_like(time)
    half = duration_days / 2
    ingress = ingress_frac * duration_days
    phase = np.mod(time + period / 2, period) - period / 2
    abs_phase = np.abs(phase)
    flat = abs_phase < (half - ingress)
    ramp = (abs_phase >= (half - ingress)) & (abs_phase < half)
    flux[flat] -= depth
    ramp_idx = np.where(ramp)[0]
    for i in ramp_idx:
        frac = (half - abs_phase[i]) / ingress
        flux[i] -= depth * frac
    flux += rng.normal(0, noise, size=time.shape)
    lines = ["time,flux"] + [f"{t},{f}" for t, f in zip(time, flux)]
    return io.BytesIO(("\n".join(lines) + "\n").encode("utf-8"))


def test_csv_with_valid_object_id_runs_the_real_prediction_with_zero_manual_entry(client, monkeypatch):
    """The primary workflow: CSV upload + Object ID -> automatic 17-feature
    extraction -> the real trained Random Forest + CNN ensemble, with no
    manual parameter entry at all."""
    files = {"file": ("kepler_227b_like.csv", make_trapezoid_light_curve_csv(), "text/csv")}
    resp = client.post("/predict/csv", files=files, data={"object_id": "K00752.01"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["object_id"] == "K00752.01"
    assert body["catalog_resolution"]["identifier_type"] == "koi_name"
    assert body["catalog_resolution"]["match_status"] == "matched_koi"
    assert body["missing_features"] == []
    assert body["ready_for_prediction"] is True

    assert body["prediction"] is not None
    assert body["prediction"]["prediction"] in (0, 1)
    assert 0.0 <= body["prediction"]["weighted_probability"] <= 1.0

    features = body["features"]
    assert features["koi_steff"]["status"] == "catalog"
    assert features["koi_steff"]["value"] == pytest.approx(5455.0)
    assert features["koi_period"]["status"] == "estimated"
    assert features["koi_prad"]["status"] == "derived"
    # Matched KOI: the catalogue impact parameter, not a light-curve shape estimate.
    assert features["koi_impact"]["status"] == "catalog"
    assert features["koi_impact"]["value"] == pytest.approx(0.146)


def test_tic_object_id_is_rejected_not_silently_mismatched(client):
    """A TESS TIC identifier must never be searched against the (unrelated)
    Kepler KIC index -- this dataset/model is Kepler-only."""
    files = {"file": ("kepler_001.csv", make_light_curve_csv(), "text/csv")}
    resp = client.post("/predict/csv", files=files, data={"object_id": "TIC 141914082"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["catalog_resolution"]["identifier_type"] == "tic"
    assert body["catalog_resolution"]["match_status"] == "unsupported_identifier_type"
    assert body["ready_for_prediction"] is False
    assert body["prediction"] is None


def test_unavailable_catalogue_returns_analysis_with_lookup_error_not_a_crash(client, monkeypatch):
    make_catalog_unavailable(monkeypatch)

    files = {"file": ("kepler_001.csv", make_light_curve_csv(), "text/csv")}
    resp = client.post("/predict/csv", files=files, data={"object_id": "KIC 10797460"})
    assert resp.status_code == 200
    body = resp.json()
    # A catalogue that couldn't be read is never reported as "not found".
    assert body["catalog_resolution"]["match_status"] == "lookup_error"
    assert "not a missing object" in body["catalog_resolution"]["note"]
    assert body["ready_for_prediction"] is False
    assert body["prediction"] is None
    assert body["features"]["koi_steff"]["status"] == "unavailable"


def test_real_catalogue_record_with_blank_stellar_fields_reaches_the_api_response(client):
    # K01046.01 (KIC 6209637) is a real record whose koi_steff/koi_slogg/
    # koi_srad/koi_score are blank in the catalogue while ra/dec/koi_kepmag
    # are present.
    files = {"file": ("kepler_001.csv", make_light_curve_csv(), "text/csv")}
    resp = client.post("/predict/csv", files=files, data={"object_id": "K01046.01"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["catalog_resolution"]["match_status"] == "matched_koi"
    assert body["catalog_resolution"]["matched_kepid"] == 6209637
    assert body["features"]["koi_steff"]["status"] == "unavailable"
    assert body["features"]["koi_steff"]["value"] is None
    assert body["features"]["ra"]["status"] == "catalog"
    assert body["features"]["ra"]["value"] == pytest.approx(293.28799)
    assert body["features"]["koi_kepmag"]["value"] == pytest.approx(13.22)
    assert body["ready_for_prediction"] is False


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
    resp1 = client.post("/predict/csv", files=files1, data={"object_id": "KIC 999999999"})
    resp2 = client.post("/predict/csv", files=files2, data={"object_id": "KIC 999999999"})
    assert "cache_hit" not in resp1.json()
    assert resp1.json()["diagnostics"]["bls_period_days"] == resp2.json()["diagnostics"]["bls_period_days"]
