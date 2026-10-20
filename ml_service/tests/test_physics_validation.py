"""
Unit tests for app/physics_validation.py -- the Stage 2 physics-validation
module. Tested entirely independent of the web layer (no TestClient / FastAPI
needed here; see test_physics_api.py for the HTTP-level tests).
"""
from app.physics_validation import (
    NOT_EVALUATED,
    PASS,
    REVIEW_REQUIRED,
    run_physics_validation,
)

# A self-consistent Earth-like system used as the "everything agrees" case:
#   Rstar = 1 Rsun, Rp = 1 Rearth -> k = 0.0091577 -> depth = 1e6*k^2 ~= 83.9 ppm
#   Mstar = 1 Msun (slogg=4.438 cgs, srad=1 -> M~1), P = 365.25 d -> a ~= 1 AU
#   a/Rstar = 1 AU / 1 Rsun ~= 215.1
#   b = 0 -> T14 = (P/pi) * arcsin((1+k)/215.1) ~= 13.0 hours
EARTH_LIKE = {
    "koi_period": 365.25,
    "koi_impact": 0.0,
    "koi_duration": 13.0,
    "koi_depth": 83.9,
    "koi_prad": 1.0,
    "koi_srad": 1.0,
    "koi_steff": 5772.0,
    "koi_slogg": 4.438,
}


def _get(report, test_id):
    return next(t for t in report.tests if t.test_id == test_id)


class TestPlanetSizeValidation:
    def test_consistent_depth_passes_values(self):
        report = run_physics_validation(EARTH_LIKE)
        test = _get(report, "planet_size")
        assert test.status == PASS
        assert test.observed["transit_depth"].value == 83.9
        assert test.expected["transit_depth"].value == pytest_approx(83.9, rel=0.05)

    def test_grossly_inconsistent_depth_requires_review(self):
        features = dict(EARTH_LIKE, koi_depth=5000.0)  # way deeper than a 1-Rearth planet implies
        report = run_physics_validation(features)
        test = _get(report, "planet_size")
        assert test.status == REVIEW_REQUIRED
        assert test.discrepancy.relative > 0.3

    def test_missing_depth_is_not_evaluated(self):
        features = dict(EARTH_LIKE, koi_depth=None)
        report = run_physics_validation(features)
        test = _get(report, "planet_size")
        assert test.status == NOT_EVALUATED
        assert "koi_depth" in test.missing_data

    def test_missing_stellar_radius_is_not_evaluated(self):
        features = dict(EARTH_LIKE, koi_srad=None)
        report = run_physics_validation(features)
        test = _get(report, "planet_size")
        assert test.status == NOT_EVALUATED
        assert "koi_srad" in test.missing_data

    def test_non_positive_depth_is_not_evaluated_not_fabricated(self):
        features = dict(EARTH_LIKE, koi_depth=-10.0)
        report = run_physics_validation(features)
        test = _get(report, "planet_size")
        assert test.status == NOT_EVALUATED
        assert test.expected == {}

    def test_non_finite_radius_is_not_evaluated(self):
        features = dict(EARTH_LIKE, koi_prad=float("nan"))
        report = run_physics_validation(features)
        test = _get(report, "planet_size")
        assert test.status == NOT_EVALUATED


class TestTransitDurationValidation:
    def test_consistent_duration_passes(self):
        report = run_physics_validation(EARTH_LIKE)
        test = _get(report, "transit_duration")
        assert test.status == PASS
        assert test.observed["transit_duration"].value == 13.0

    def test_grossly_inconsistent_duration_requires_review(self):
        features = dict(EARTH_LIKE, koi_duration=1.0)  # far too short for this orbit
        report = run_physics_validation(features)
        test = _get(report, "transit_duration")
        assert test.status == REVIEW_REQUIRED

    def test_missing_slogg_is_not_evaluated(self):
        features = dict(EARTH_LIKE, koi_slogg=None)
        report = run_physics_validation(features)
        test = _get(report, "transit_duration")
        assert test.status == NOT_EVALUATED
        assert "koi_slogg" in test.missing_data

    def test_impossible_impact_parameter_is_review_required_not_fabricated(self):
        # b > 1 + k: planet "misses" the star entirely for this radius ratio.
        features = dict(EARTH_LIKE, koi_impact=5.0)
        report = run_physics_validation(features)
        test = _get(report, "transit_duration")
        assert test.status == REVIEW_REQUIRED
        assert test.expected == {}

    def test_negative_impact_parameter_is_not_evaluated(self):
        features = dict(EARTH_LIKE, koi_impact=-0.5)
        report = run_physics_validation(features)
        test = _get(report, "transit_duration")
        assert test.status == NOT_EVALUATED

    def test_zero_period_is_not_evaluated(self):
        features = dict(EARTH_LIKE, koi_period=0.0)
        report = run_physics_validation(features)
        test = _get(report, "transit_duration")
        assert test.status == NOT_EVALUATED


class TestOrbitalPhysicsValidation:
    def test_self_consistent_orbit_passes(self):
        report = run_physics_validation(EARTH_LIKE)
        test = _get(report, "orbital_physics")
        assert test.status == PASS
        assert test.calculation.derived["semi_major_axis"].value == pytest_approx(1.0, rel=0.02)

    def test_orbit_smaller_than_star_requires_review(self):
        # An absurdly short period for a Sun-like star puts a inside the star.
        features = dict(EARTH_LIKE, koi_period=0.001)
        report = run_physics_validation(features)
        test = _get(report, "orbital_physics")
        assert test.status == REVIEW_REQUIRED

    def test_missing_stellar_mass_inputs_is_not_evaluated(self):
        features = dict(EARTH_LIKE, koi_slogg=None, koi_srad=None)
        report = run_physics_validation(features)
        test = _get(report, "orbital_physics")
        assert test.status == NOT_EVALUATED
        assert "koi_slogg" in test.missing_data
        assert "koi_srad" in test.missing_data

    def test_cross_check_runs_when_geometry_inputs_present(self):
        report = run_physics_validation(EARTH_LIKE)
        test = _get(report, "orbital_physics")
        assert any("Cross-check" in c for c in test.consistency_checks)


class TestOverallReport:
    def test_all_pass_gives_overall_pass(self):
        report = run_physics_validation(EARTH_LIKE)
        assert report.overall_status == PASS
        assert report.counts[PASS] == 3

    def test_summary_never_hides_a_mixed_result(self):
        features = dict(EARTH_LIKE, koi_depth=None, koi_duration=1.0)
        report = run_physics_validation(features)
        counts = report.counts
        assert counts[NOT_EVALUATED] == 1  # planet_size
        assert counts[REVIEW_REQUIRED] == 1  # transit_duration
        assert counts[PASS] == 1  # orbital_physics
        message = report.summary_message()
        assert "1 of 3" in message
        assert "1 require investigation" in message
        assert "1 could not be evaluated" in message
        assert report.overall_status == REVIEW_REQUIRED

    def test_all_missing_gives_overall_not_evaluated(self):
        report = run_physics_validation({})
        assert report.overall_status == NOT_EVALUATED
        assert report.counts[NOT_EVALUATED] == 3

    def test_issues_and_recommendations_reflect_only_real_findings(self):
        report = run_physics_validation({})
        issues, recommendations = report.issues_and_recommendations()
        assert len(issues) == 3
        assert len(recommendations) == 3

    def test_no_issues_message_when_everything_passes(self):
        report = run_physics_validation(EARTH_LIKE)
        issues, _ = report.issues_and_recommendations()
        assert issues == []

    def test_object_id_is_echoed_back(self):
        report = run_physics_validation(EARTH_LIKE, object_id="KIC 11904151")
        assert report.object_id == "KIC 11904151"

    def test_to_dict_is_json_serializable_shape(self):
        import json

        report = run_physics_validation(EARTH_LIKE, object_id="KIC 11904151")
        body = report.to_dict()
        json.dumps(body)  # raises if anything isn't a plain JSON type
        assert body["overall_status"] == PASS
        assert len(body["tests"]) == 3
        assert body["summary"]["tests_passed"] == 3


def pytest_approx(value, rel):
    import pytest

    return pytest.approx(value, rel=rel)
