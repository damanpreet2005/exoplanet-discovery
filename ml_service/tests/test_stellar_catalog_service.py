"""
Tests for app/stellar_catalog_service.py and app/koi_catalog.py.

Lookups run against the real local KOI catalogue shipped at
ml_service/data/koi_catalog.csv (the same file the Docker image serves
from /srv/data), so expectations below are real catalogue records, not
fabricated values:
  kepid 10797460 has two KOIs: K00752.01 (Kepler-227 b) and K00752.02 (Kepler-227 c)
  kepid 10811496 has exactly one KOI: K00753.01 (no confirmed planet name), FALSE POSITIVE, koi_score=0.0
  K01046.01 is a real record with koi_steff/koi_slogg/koi_srad/koi_score blank but ra/dec/koi_kepmag present
  K00113.01 is a real record with stellar fields present but koi_score blank

Edge cases the real file doesn't contain (missing file, wrong schema,
conflicting duplicate rows) use small fixture CSVs written to tmp_path and
injected through the `get_koi_catalog` seam.
"""
import pytest

from app import koi_catalog
from app import stellar_catalog_service as scs
from app.config import get_settings

HEADER = (
    "rowid,kepid,kepoi_name,kepler_name,koi_disposition,koi_score,koi_tce_plnt_num,"
    "koi_steff,koi_slogg,koi_srad,ra,dec,koi_kepmag"
)


def use_fixture_catalog(monkeypatch, tmp_path, *rows: str, header: str = HEADER):
    path = tmp_path / "koi_catalog.csv"
    path.write_text("\n".join((header,) + rows) + "\n", encoding="utf-8")
    catalog = koi_catalog.load_koi_catalog(path)
    monkeypatch.setattr(scs, "get_koi_catalog", lambda: catalog)
    return catalog


def use_unavailable_catalog(monkeypatch, path):
    monkeypatch.setattr(scs, "get_koi_catalog", lambda: koi_catalog.load_koi_catalog(path))


class TestNotProvided:
    def test_none_identifier(self):
        res = scs.resolve_object_id(None)
        assert res.match_status == "not_provided"
        assert all(v is None for v in res.fields.values())

    def test_blank_identifier(self):
        res = scs.resolve_object_id("   ")
        assert res.match_status == "not_provided"


class TestNotFound:
    def test_unknown_kepid(self):
        res = scs.resolve_object_id("999999999")
        assert res.match_status == "not_found"
        assert all(v is None for v in res.fields.values())

    def test_unknown_koi_name(self):
        res = scs.resolve_object_id("K99999.01")
        assert res.match_status == "not_found"
        assert "K99999.01" in res.note

    def test_unknown_kepler_name(self):
        res = scs.resolve_object_id("Kepler-999999 z")
        assert res.match_status == "not_found"

    def test_garbage_identifier(self):
        res = scs.resolve_object_id("not a real target !!")
        assert res.match_status == "not_found"
        assert res.identifier_type == "unrecognized"


class TestKicResolution:
    def test_bare_kepid_ambiguous_star(self):
        res = scs.resolve_object_id("10797460")
        assert res.match_status == "matched_star"
        assert res.n_candidate_rows == 2
        assert res.field_available["koi_steff"] is True
        assert res.fields["koi_steff"] == pytest.approx(5455.0)
        assert res.fields["koi_srad"] == pytest.approx(0.927)
        # Per-KOI fields must NOT be resolved from an ambiguous star-only match.
        assert res.field_available["koi_score"] is False
        assert res.field_available["koi_tce_plnt_num"] is False

    def test_kic_prefix(self):
        res = scs.resolve_object_id("KIC 10797460")
        assert res.match_status == "matched_star"
        assert res.matched_kepid == 10797460

    def test_single_koi_star_resolves_fully(self):
        res = scs.resolve_object_id("10811496")
        assert res.match_status == "matched_koi"
        assert res.matched_kepoi_name == "K00753.01"
        assert res.field_available["koi_score"] is True
        assert res.fields["koi_score"] == pytest.approx(0.0)


class TestStringVersusNumericIdentifiers:
    @pytest.mark.parametrize("object_id", ["10811496", " KIC 10811496 ", "kic-10811496", 10811496, 10811496.0, "10811496.0"])
    def test_every_kic_spelling_resolves_to_the_same_star(self, object_id):
        res = scs.resolve_object_id(object_id)
        assert res.identifier_type == "kic"
        assert res.match_status == "matched_koi"
        assert res.matched_kepid == 10811496
        assert res.fields["koi_steff"] == pytest.approx(5853.0)

    def test_fractional_number_is_not_a_kic_id(self):
        res = scs.resolve_object_id("10811496.5")
        assert res.match_status == "not_found"
        assert res.matched_kepid is None

    @pytest.mark.parametrize("object_id", [True, 10811496.5, float("nan"), ["10811496"]])
    def test_non_identifier_values_raise(self, object_id):
        with pytest.raises(scs.InvalidObjectIdError):
            scs.resolve_object_id(object_id)


class TestKoiNameResolution:
    def test_canonical_koi_name(self):
        res = scs.resolve_object_id("K00752.01")
        assert res.match_status == "matched_koi"
        assert res.matched_kepid == 10797460
        assert res.matched_kepler_name == "Kepler-227 b"
        assert res.fields["koi_score"] == pytest.approx(1.0)
        assert res.fields["koi_tce_plnt_num"] == pytest.approx(1.0)
        assert res.fields["koi_steff"] == pytest.approx(5455.0)
        assert res.fields["koi_slogg"] == pytest.approx(4.467)
        assert res.fields["ra"] == pytest.approx(291.934230, rel=1e-6)
        assert res.fields["dec"] == pytest.approx(48.141651, rel=1e-6)
        assert res.fields["koi_kepmag"] == pytest.approx(15.347)

    def test_second_planet_same_star_different_score(self):
        res = scs.resolve_object_id("K00752.02")
        assert res.match_status == "matched_koi"
        assert res.fields["koi_score"] == pytest.approx(0.969)
        assert res.fields["koi_tce_plnt_num"] == pytest.approx(2.0)
        assert res.fields["koi_steff"] == pytest.approx(5455.0)

    def test_lowercase_koi_name(self):
        res = scs.resolve_object_id("k00752.01")
        assert res.match_status == "matched_koi"
        assert res.matched_kepoi_name == "K00752.01"

    def test_loose_koi_dash_form(self):
        res = scs.resolve_object_id("KOI-752.01")
        assert res.match_status == "matched_koi"
        assert res.matched_kepoi_name == "K00752.01"

    def test_koi_number_without_planet_suffix_is_ambiguous(self):
        res = scs.resolve_object_id("KOI-752")
        assert res.match_status == "matched_star"
        assert res.n_candidate_rows == 2
        assert res.matched_kepid == 10797460


class TestKoiAndKicAreNeverInterchanged:
    def test_koi_number_is_not_looked_up_as_a_kic_number(self):
        # KOI 752 is on KIC 10797460; "KIC 752" is a different (absent) star.
        assert scs.resolve_object_id("KOI 752").matched_kepid == 10797460
        res = scs.resolve_object_id("KIC 752")
        assert res.identifier_type == "kic"
        assert res.match_status == "not_found"

    def test_kic_number_is_not_looked_up_as_a_koi_number(self):
        res = scs.resolve_object_id("KOI 10797460")
        assert res.identifier_type == "koi_name"
        assert res.match_status == "not_found"


class TestKeplerNameResolution:
    def test_exact_kepler_name(self):
        res = scs.resolve_object_id("Kepler-227 b")
        assert res.match_status == "matched_koi"
        assert res.matched_kepoi_name == "K00752.01"

    def test_kepler_name_case_and_spacing_insensitive(self):
        res = scs.resolve_object_id("kepler-227b")
        assert res.match_status == "matched_koi"
        assert res.matched_kepoi_name == "K00752.01"

    def test_similar_prefix_does_not_match(self, monkeypatch, tmp_path):
        # 'Kepler-2270 x' starts with 'Kepler-227' but is a different name.
        use_fixture_catalog(monkeypatch, tmp_path, "1,1,K09999.01,Kepler-2270 x,CONFIRMED,1,1,5000,4.5,1,290,45,14")
        res = scs.resolve_object_id("Kepler-227 b")
        assert res.match_status == "not_found"


class TestTicIsNeverConfusedWithKic:
    def test_tic_prefixed_identifier_is_rejected_without_any_lookup(self, monkeypatch):
        def fail():
            raise AssertionError("catalogue must not be consulted for a TIC identifier")
        monkeypatch.setattr(scs, "get_koi_catalog", fail)
        res = scs.resolve_object_id("TIC 10797460")
        assert res.identifier_type == "tic"
        assert res.match_status == "unsupported_identifier_type"
        assert all(v is None for v in res.fields.values())
        assert "TESS" in res.note or "TIC" in res.note

    def test_tic_without_space(self):
        res = scs.resolve_object_id("TIC10797460")
        assert res.identifier_type == "tic"
        assert res.match_status == "unsupported_identifier_type"

    def test_bare_kic_number_is_still_resolved_as_kic(self):
        res = scs.resolve_object_id("10797460")
        assert res.identifier_type == "kic"
        assert res.match_status == "matched_star"


class TestObjectIdValidation:
    def test_overly_long_object_id_raises(self):
        with pytest.raises(scs.InvalidObjectIdError):
            scs.resolve_object_id("K" * 100)


class TestCatalogMissingParameter:
    """A real, matched catalog record can still have a specific field blank
    -- this must surface as that one field being unavailable, never a
    silent 0/default, while every other resolvable field on the same record
    still comes through."""

    def test_matched_row_with_blank_stellar_fields(self):
        res = scs.resolve_object_id("K01046.01")
        assert res.match_status == "matched_koi"
        assert res.matched_kepid == 6209637
        assert res.field_available["koi_steff"] is False
        assert res.fields["koi_steff"] is None
        assert res.field_available["koi_slogg"] is False
        assert res.field_available["koi_srad"] is False
        assert res.field_available["koi_score"] is False
        assert res.field_available["ra"] is True
        assert res.fields["ra"] == pytest.approx(293.287990, rel=1e-6)
        assert res.field_available["koi_kepmag"] is True
        assert res.fields["koi_kepmag"] == pytest.approx(13.22)

    def test_matched_row_with_only_score_blank_keeps_stellar_fields(self):
        res = scs.resolve_object_id("K00113.01")
        assert res.match_status == "matched_koi"
        assert res.field_available["koi_score"] is False
        assert res.fields["koi_steff"] == pytest.approx(5543.0)
        assert res.fields["koi_srad"] == pytest.approx(1.58)

    def test_false_positive_has_zero_score_available_not_missing(self):
        # koi_score == 0.0 is a real, present value -- must not be treated as
        # "unavailable" just because it's falsy.
        res = scs.resolve_object_id("K00753.01")
        assert res.field_available["koi_score"] is True
        assert res.fields["koi_score"] == pytest.approx(0.0)

    def test_non_finite_cells_become_unavailable(self, monkeypatch, tmp_path):
        use_fixture_catalog(monkeypatch, tmp_path, "1,123,K00001.01,,CANDIDATE,nan,1,inf,4.5,-inf,290.5,45.25,14")
        res = scs.resolve_object_id("K00001.01")
        assert res.match_status == "matched_koi"
        for name in ("koi_score", "koi_steff", "koi_srad"):
            assert res.fields[name] is None
            assert res.field_available[name] is False
        assert res.fields["koi_slogg"] == pytest.approx(4.5)
        assert res.fields["ra"] == pytest.approx(290.5)


class TestDuplicateAndAmbiguousRows:
    def test_duplicate_koi_name_on_the_same_star_withholds_per_koi_fields(self, monkeypatch, tmp_path):
        use_fixture_catalog(
            monkeypatch, tmp_path,
            "1,123,K00001.01,,CANDIDATE,0.9,1,5000,4.5,1.0,290,45,14",
            "2,123,K00001.01,,CANDIDATE,0.4,1,5000,4.5,1.0,290,45,14",
        )
        res = scs.resolve_object_id("K00001.01")
        assert res.match_status == "matched_star"
        assert res.n_candidate_rows == 2
        assert res.fields["koi_steff"] == pytest.approx(5000.0)
        assert res.field_available["koi_score"] is False

    def test_duplicate_koi_name_on_different_stars_resolves_nothing(self, monkeypatch, tmp_path):
        use_fixture_catalog(
            monkeypatch, tmp_path,
            "1,123,K00001.01,,CANDIDATE,0.9,1,5000,4.5,1.0,290,45,14",
            "2,456,K00001.01,,CANDIDATE,0.4,1,6000,4.1,1.3,291,46,13",
        )
        res = scs.resolve_object_id("K00001.01")
        assert res.match_status == "lookup_error"
        assert res.n_candidate_rows == 2
        assert all(v is None for v in res.fields.values())
        assert "conflicting" in res.note


class TestCatalogUnavailable:
    """A catalogue that can't be read is a lookup failure, never a
    misleading 'not found'."""

    def test_missing_file(self, monkeypatch, tmp_path):
        use_unavailable_catalog(monkeypatch, tmp_path / "does_not_exist.csv")
        res = scs.resolve_object_id("K00752.01")
        assert res.match_status == "lookup_error"
        assert res.match_status != "not_found"
        assert all(v is None for v in res.fields.values())
        assert "not a missing object" in res.note

    def test_unreadable_file(self, monkeypatch, tmp_path):
        directory = tmp_path / "koi_catalog.csv"
        directory.mkdir()  # opening a directory as a file fails
        use_unavailable_catalog(monkeypatch, directory)
        assert scs.resolve_object_id("KIC 10797460").match_status == "lookup_error"

    def test_wrong_schema(self, monkeypatch, tmp_path):
        path = tmp_path / "koi_catalog.csv"
        path.write_text("id,name\n1,K00752.01\n", encoding="utf-8")
        with pytest.raises(koi_catalog.KoiCatalogUnavailableError, match="missing required column"):
            koi_catalog.load_koi_catalog(path)
        use_unavailable_catalog(monkeypatch, path)
        assert scs.resolve_object_id("K00752.01").match_status == "lookup_error"

    def test_header_only_file(self, tmp_path):
        path = tmp_path / "koi_catalog.csv"
        path.write_text(HEADER + "\n", encoding="utf-8")
        with pytest.raises(koi_catalog.KoiCatalogUnavailableError, match="no usable rows"):
            koi_catalog.load_koi_catalog(path)

    def test_failed_load_is_not_cached(self, monkeypatch, tmp_path):
        settings = get_settings()
        missing = tmp_path / "later.csv"
        monkeypatch.setattr(koi_catalog, "_catalog", None)
        monkeypatch.setattr(settings, "koi_catalog_path", str(missing))
        with pytest.raises(koi_catalog.KoiCatalogUnavailableError):
            koi_catalog.get_koi_catalog()
        missing.write_text(HEADER + "\n1,123,K00001.01,,CANDIDATE,0.9,1,5000,4.5,1.0,290,45,14\n", encoding="utf-8")
        assert koi_catalog.get_koi_catalog().n_rows == 1


class TestRealCatalogFile:
    def test_shipped_catalogue_loads_with_expected_schema(self):
        catalog = koi_catalog.load_koi_catalog(get_settings().koi_catalog_path)
        assert catalog.n_rows == 9564
        assert len(catalog.by_kepoi_name) == 9564  # kepoi_name is unique
        assert len(catalog.by_kepid[10797460]) == 2
        # Identifiers are stored as ints, never floats or strings.
        assert all(isinstance(k, int) for k in catalog.by_kepid)
