import pytest

from app import feature_aliases
from app.feature_aliases import (
    MODEL_FEATURE_ORDER,
    FeatureOrderNotConfiguredError,
    InvalidFeatureValueError,
    MissingFeatureError,
    RfFeatureContractError,
    assert_valid_rf_feature_vector,
    extract_feature_vector,
    resolve_canonical_fields,
)

# NOTE: this is an illustrative, explicitly-fake feature order used only to
# prove the alias/extraction mechanics work correctly end-to-end. It is NOT
# the real trained model's feature order -- see feature_aliases.py's
# module docstring for why that order is not recoverable from this repo.
ILLUSTRATIVE_ORDER = ["koi_period", "koi_duration", "koi_depth"]


class TestResolveCanonicalFields:
    def test_recognizes_canonical_names_directly(self):
        resolved = resolve_canonical_fields({"koi_period": 9.5, "koi_duration": 3.1})
        assert resolved == {"koi_period": 9.5, "koi_duration": 3.1}

    def test_recognizes_documented_aliases(self):
        resolved = resolve_canonical_fields({
            "orbital_period": 9.5,
            "transit_duration": 3.1,
            "flux_drop": 421.0,
        })
        assert resolved == {"koi_period": 9.5, "koi_duration": 3.1, "koi_depth": 421.0}

    def test_case_insensitive_and_space_hyphen_tolerant(self):
        resolved = resolve_canonical_fields({
            "Orbital-Period": 9.5,
            "TRANSIT DURATION": 3.1,
            "Flux_Drop": 421.0,
        })
        assert resolved == {"koi_period": 9.5, "koi_duration": 3.1, "koi_depth": 421.0}

    def test_err1_err2_aliases_are_recognized(self):
        resolved = resolve_canonical_fields({
            "period_err1": 0.001,
            "orbital_period_err2": -0.002,
        })
        assert resolved == {"koi_period_err1": 0.001, "koi_period_err2": -0.002}

    def test_target_and_id_columns_are_dropped_even_if_present(self):
        # koi_disposition/koi_pdisposition are the training target and
        # rowid/kepid are pure identifiers -- none are model features, per
        # the verified drop_cols logic. koi_score is NOT dropped by that
        # logic, so it must be kept (verified separately below).
        resolved = resolve_canonical_fields({
            "koi_period": 9.5,
            "koi_disposition": "CONFIRMED",
            "kepid": 12345678,
            "rowid": 1,
        })
        assert resolved == {"koi_period": 9.5}

    def test_koi_score_and_tce_plnt_num_are_kept_not_dropped(self):
        # These two were incorrectly excluded in an earlier version of this
        # module; the verified training code's drop_cols does NOT remove
        # them -- they are two of the real 17 features.
        resolved = resolve_canonical_fields({"koi_score": 0.99, "koi_tce_plnt_num": 1})
        assert resolved == {"koi_score": 0.99, "koi_tce_plnt_num": 1}

    def test_unrecognized_fields_are_ignored_not_rejected(self):
        resolved = resolve_canonical_fields({"koi_period": 9.5, "some_unrelated_field": "x"})
        assert resolved == {"koi_period": 9.5}


class TestExtractFeatureVector:
    def test_extracts_values_in_the_given_order_using_aliases(self):
        raw = {"orbital_period": 9.5, "transit_duration": 3.1, "depth": 421.0}
        values = extract_feature_vector(raw, ILLUSTRATIVE_ORDER)
        assert values == [9.5, 3.1, 421.0]

    def test_missing_required_feature_raises_with_alias_list_in_message(self):
        raw = {"transit_duration": 3.1, "depth": 421.0}  # koi_period missing
        with pytest.raises(MissingFeatureError) as exc_info:
            extract_feature_vector(raw, ILLUSTRATIVE_ORDER)
        message = str(exc_info.value)
        assert "koi_period" in message
        assert "orbital_period" in message
        assert "planet_period" in message

    def test_never_fills_missing_value_with_a_default(self):
        raw = {"koi_period": 9.5}
        with pytest.raises(MissingFeatureError):
            extract_feature_vector(raw, ILLUSTRATIVE_ORDER)

    def test_non_numeric_value_raises(self):
        raw = {"koi_period": "not_a_number", "koi_duration": 3.1, "koi_depth": 421.0}
        with pytest.raises(InvalidFeatureValueError):
            extract_feature_vector(raw, ILLUSTRATIVE_ORDER)

    def test_non_finite_value_raises(self):
        raw = {"koi_period": float("nan"), "koi_duration": 3.1, "koi_depth": 421.0}
        with pytest.raises(InvalidFeatureValueError):
            extract_feature_vector(raw, ILLUSTRATIVE_ORDER)

    def test_raises_configuration_error_if_ever_unconfigured_again(self, monkeypatch):
        # Safety-net test: if MODEL_FEATURE_ORDER were ever unset again (e.g.
        # a future refactor), this must fail loudly rather than guess.
        monkeypatch.setattr(feature_aliases, "MODEL_FEATURE_ORDER", None)
        with pytest.raises(FeatureOrderNotConfiguredError):
            extract_feature_vector({"koi_period": 9.5})

    def test_default_order_is_the_verified_17_real_model_features(self):
        assert len(MODEL_FEATURE_ORDER) == 17
        assert MODEL_FEATURE_ORDER == [
            "koi_score", "koi_period", "koi_time0bk", "koi_impact", "koi_duration",
            "koi_depth", "koi_prad", "koi_teq", "koi_insol", "koi_model_snr",
            "koi_tce_plnt_num", "koi_steff", "koi_slogg", "koi_srad", "ra", "dec",
            "koi_kepmag",
        ]

    def test_real_named_input_extracts_in_the_default_verified_order(self):
        raw = {
            "score": 1.0, "orbital_period": 9.488, "transit_epoch": 170.5,
            "impact": 0.146, "transit_duration": 2.9575, "depth": 615.8,
            "planet_radius": 2.26, "temperature": 793.0, "insolation": 93.59,
            "snr": 35.8, "tce_planet_number": 1, "teff": 5455.0, "logg": 4.467,
            "stellar_radius": 0.927, "right_ascension": 291.93, "declination": 48.14,
            "kepmag": 15.347,
        }
        values = extract_feature_vector(raw)  # no explicit order -> uses the real default
        assert len(values) == 17
        assert values[0] == 1.0  # koi_score
        assert values[1] == 9.488  # koi_period
        assert values[-1] == 15.347  # koi_kepmag


class TestAssertValidRfFeatureVector:
    """STEP 9: an explicit assertion so an accidental future reordering,
    renaming, or missing/non-finite value is caught before it ever reaches
    the trained model, rather than silently producing a wrong prediction."""

    def _valid_values(self):
        return [float(i) for i in range(1, 18)]  # 17 finite values

    def test_correct_order_and_values_pass(self):
        assert_valid_rf_feature_vector(list(MODEL_FEATURE_ORDER), self._valid_values())

    def test_reordered_names_raise(self):
        reordered = list(MODEL_FEATURE_ORDER)
        reordered[0], reordered[1] = reordered[1], reordered[0]
        with pytest.raises(RfFeatureContractError):
            assert_valid_rf_feature_vector(reordered, self._valid_values())

    def test_renamed_feature_raises(self):
        renamed = list(MODEL_FEATURE_ORDER)
        renamed[-1] = "koi_kepmag_v2"
        with pytest.raises(RfFeatureContractError):
            assert_valid_rf_feature_vector(renamed, self._valid_values())

    def test_wrong_length_raises(self):
        with pytest.raises(RfFeatureContractError):
            assert_valid_rf_feature_vector(list(MODEL_FEATURE_ORDER), self._valid_values()[:16])

    def test_none_value_raises(self):
        values = self._valid_values()
        values[3] = None
        with pytest.raises(RfFeatureContractError):
            assert_valid_rf_feature_vector(list(MODEL_FEATURE_ORDER), values)

    def test_non_finite_value_raises(self):
        values = self._valid_values()
        values[3] = float("nan")
        with pytest.raises(RfFeatureContractError):
            assert_valid_rf_feature_vector(list(MODEL_FEATURE_ORDER), values)

    def test_matches_model_artifact_feature_names_when_present(self):
        class FakeModel:
            feature_names_in_ = list(MODEL_FEATURE_ORDER)

        assert_valid_rf_feature_vector(list(MODEL_FEATURE_ORDER), self._valid_values(), random_forest=FakeModel())

    def test_mismatched_model_artifact_feature_names_raise(self):
        class FakeModel:
            feature_names_in_ = ["some", "other", "order"]

        with pytest.raises(RfFeatureContractError):
            assert_valid_rf_feature_vector(list(MODEL_FEATURE_ORDER), self._valid_values(), random_forest=FakeModel())

    def test_no_artifact_metadata_is_not_an_error(self):
        # Reflects today's real artifact: feature_names_in_ is None on both
        # the stored RandomForestClassifier and RobustScaler.
        class FakeModel:
            feature_names_in_ = None

        assert_valid_rf_feature_vector(list(MODEL_FEATURE_ORDER), self._valid_values(), random_forest=FakeModel())
