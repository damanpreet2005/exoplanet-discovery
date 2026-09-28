"""
Tests for app/stellar_catalog_service.py. The live NASA Exoplanet Archive is
NEVER called here -- every test monkeypatches
`app.stellar_catalog_service.query_cumulative_table` (the one seam this
module uses to reach app/nasa_exoplanet_archive_client.py) with canned rows
or a simulated failure, so the suite is fast, deterministic, and has no
dependency on live NASA availability.

Fixture data below mirrors real NASA Exoplanet Archive `cumulative` table
rows (same identifiers/values used when this project still shipped a local
snapshot of the table), used as realistic ground truth rather than
fabricated expectations:
  kepid 10797460 has two KOIs: K00752.01 (Kepler-227 b) and K00752.02 (Kepler-227 c)
  kepid 10811496 has exactly one KOI: K00753.01 (no confirmed planet name), FALSE POSITIVE, koi_score=0.0
  K01046.01 is a real record with most fields blank except ra/dec/koi_kepmag
"""
import pytest

from app import stellar_catalog_service as scs
from app.nasa_exoplanet_archive_client import (
    NasaApiHttpError,
    NasaApiMalformedResponseError,
    NasaApiTimeoutError,
    NasaApiUnavailableError,
)

K00752_01 = {
    "kepid": 10797460, "kepoi_name": "K00752.01", "kepler_name": "Kepler-227 b",
    "koi_score": 1.0, "koi_tce_plnt_num": 1,
    "koi_steff": 5455.0, "koi_slogg": 4.467, "koi_srad": 0.9270,
    "ra": 291.934230, "dec": 48.141651, "koi_kepmag": 15.347,
}
K00752_02 = {
    "kepid": 10797460, "kepoi_name": "K00752.02", "kepler_name": "Kepler-227 c",
    "koi_score": 0.969, "koi_tce_plnt_num": 2,
    "koi_steff": 5455.0, "koi_slogg": 4.467, "koi_srad": 0.9270,
    "ra": 291.934230, "dec": 48.141651, "koi_kepmag": 15.347,
}
K00753_01 = {
    "kepid": 10811496, "kepoi_name": "K00753.01", "kepler_name": None,
    "koi_score": 0.0, "koi_tce_plnt_num": 1,
    "koi_steff": 5853.0, "koi_slogg": 4.544, "koi_srad": 0.868,
    "ra": 297.004820, "dec": 48.134129, "koi_kepmag": 15.436,
}
K01046_01_MOSTLY_BLANK = {
    "kepid": 6209637, "kepoi_name": "K01046.01", "kepler_name": None,
    "koi_score": None, "koi_tce_plnt_num": None,
    "koi_steff": None, "koi_slogg": None, "koi_srad": None,
    "ra": 293.287990, "dec": 41.560455, "koi_kepmag": 13.220,
}


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    """Every test gets an empty NASA-lookup cache so one test's mocked rows
    can't leak into another via the module-level cache singleton."""
    monkeypatch.setattr(scs, "_cache", None)


def mock_query(monkeypatch, rows_by_clause: dict[str, list[dict]]):
    """Replaces the network call with a lookup table keyed by the exact
    ADQL WHERE clause the code under test is expected to build."""
    calls = []

    def fake_query_cumulative_table(where_clause: str) -> list[dict]:
        calls.append(where_clause)
        for clause, rows in rows_by_clause.items():
            if where_clause == clause:
                return rows
        return []

    monkeypatch.setattr(scs, "query_cumulative_table", fake_query_cumulative_table)
    return calls


def mock_query_raises(monkeypatch, exc: Exception):
    def fake_query_cumulative_table(where_clause: str) -> list[dict]:
        raise exc
    monkeypatch.setattr(scs, "query_cumulative_table", fake_query_cumulative_table)


class TestNotProvided:
    def test_none_identifier(self):
        res = scs.resolve_object_id(None)
        assert res.match_status == "not_provided"
        assert all(v is None for v in res.fields.values())

    def test_blank_identifier(self):
        res = scs.resolve_object_id("   ")
        assert res.match_status == "not_provided"


class TestNotFound:
    def test_unknown_kepid(self, monkeypatch):
        mock_query(monkeypatch, {"kepid = 999999999": []})
        res = scs.resolve_object_id("999999999")
        assert res.match_status == "not_found"
        assert all(v is None for v in res.fields.values())

    def test_unknown_kepler_name(self, monkeypatch):
        mock_query(monkeypatch, {"kepler_name like 'Kepler-999999%'": []})
        res = scs.resolve_object_id("Kepler-999999 z")
        assert res.match_status == "not_found"

    def test_garbage_identifier(self, monkeypatch):
        mock_query(monkeypatch, {})
        res = scs.resolve_object_id("not a real target !!")
        assert res.match_status == "not_found"


class TestKicResolution:
    def test_bare_kepid_ambiguous_star(self, monkeypatch):
        mock_query(monkeypatch, {"kepid = 10797460": [K00752_01, K00752_02]})
        res = scs.resolve_object_id("10797460")
        assert res.match_status == "matched_star"
        assert res.n_candidate_rows == 2
        assert res.field_available["koi_steff"] is True
        assert res.fields["koi_steff"] == pytest.approx(5455.0)
        # Per-KOI fields must NOT be resolved from an ambiguous star-only match.
        assert res.field_available["koi_score"] is False
        assert res.field_available["koi_tce_plnt_num"] is False

    def test_kic_prefix(self, monkeypatch):
        mock_query(monkeypatch, {"kepid = 10797460": [K00752_01, K00752_02]})
        res = scs.resolve_object_id("KIC 10797460")
        assert res.match_status == "matched_star"
        assert res.matched_kepid == 10797460

    def test_single_koi_star_resolves_fully(self, monkeypatch):
        mock_query(monkeypatch, {"kepid = 10811496": [K00753_01]})
        res = scs.resolve_object_id("10811496")
        assert res.match_status == "matched_koi"
        assert res.field_available["koi_score"] is True
        assert res.fields["koi_score"] == pytest.approx(0.0)

    def test_query_uses_exact_kepid_no_raw_string_interpolation(self, monkeypatch):
        calls = mock_query(monkeypatch, {"kepid = 10797460": [K00752_01]})
        scs.resolve_object_id("KIC 10797460")
        assert calls == ["kepid = 10797460"]


class TestKoiNameResolution:
    def test_canonical_koi_name(self, monkeypatch):
        mock_query(monkeypatch, {"kepoi_name = 'K00752.01'": [K00752_01]})
        res = scs.resolve_object_id("K00752.01")
        assert res.match_status == "matched_koi"
        assert res.matched_kepid == 10797460
        assert res.fields["koi_score"] == pytest.approx(1.0)
        assert res.fields["koi_tce_plnt_num"] == pytest.approx(1.0)
        assert res.fields["koi_steff"] == pytest.approx(5455.0)
        assert res.fields["ra"] == pytest.approx(291.934230, rel=1e-4)

    def test_second_planet_same_star_different_score(self, monkeypatch):
        mock_query(monkeypatch, {"kepoi_name = 'K00752.02'": [K00752_02]})
        res = scs.resolve_object_id("K00752.02")
        assert res.match_status == "matched_koi"
        assert res.fields["koi_tce_plnt_num"] == pytest.approx(2.0)
        assert res.fields["koi_steff"] == pytest.approx(5455.0)

    def test_loose_koi_dash_form(self, monkeypatch):
        mock_query(monkeypatch, {"kepoi_name = 'K00752.01'": [K00752_01]})
        res = scs.resolve_object_id("KOI-752.01")
        assert res.match_status == "matched_koi"
        assert res.matched_kepoi_name == "K00752.01"

    def test_koi_number_without_planet_suffix_is_ambiguous(self, monkeypatch):
        mock_query(monkeypatch, {"kepoi_name like 'K00752.%'": [K00752_01, K00752_02]})
        res = scs.resolve_object_id("KOI-752")
        assert res.match_status == "matched_star"
        assert res.n_candidate_rows == 2


class TestKeplerNameResolution:
    def test_exact_kepler_name(self, monkeypatch):
        mock_query(monkeypatch, {"kepler_name like 'Kepler-227%'": [K00752_01, K00752_02]})
        res = scs.resolve_object_id("Kepler-227 b")
        assert res.match_status == "matched_koi"
        assert res.matched_kepoi_name == "K00752.01"

    def test_kepler_name_case_and_spacing_insensitive(self, monkeypatch):
        mock_query(monkeypatch, {"kepler_name like 'Kepler-227%'": [K00752_01, K00752_02]})
        res = scs.resolve_object_id("kepler-227b")
        assert res.match_status == "matched_koi"
        assert res.matched_kepoi_name == "K00752.01"

    def test_prefix_query_still_requires_exact_client_side_match(self, monkeypatch):
        # A LIKE prefix can over-match (e.g. 'Kepler-2270' would also start
        # with 'Kepler-227'); the exact normalized comparison must reject it.
        decoy = {**K00752_01, "kepoi_name": "K09999.01", "kepler_name": "Kepler-2270 x"}
        mock_query(monkeypatch, {"kepler_name like 'Kepler-227%'": [decoy]})
        res = scs.resolve_object_id("Kepler-227 b")
        assert res.match_status == "not_found"


class TestTicIsNeverConfusedWithKic:
    def test_tic_prefixed_identifier_is_rejected_without_any_query(self, monkeypatch):
        calls = mock_query(monkeypatch, {})
        res = scs.resolve_object_id("TIC 10797460")
        assert res.identifier_type == "tic"
        assert res.match_status == "unsupported_identifier_type"
        assert all(v is None for v in res.fields.values())
        assert "TESS" in res.note or "TIC" in res.note
        assert calls == []  # never even queried

    def test_tic_without_space(self, monkeypatch):
        mock_query(monkeypatch, {})
        res = scs.resolve_object_id("TIC10797460")
        assert res.identifier_type == "tic"
        assert res.match_status == "unsupported_identifier_type"

    def test_bare_kic_number_is_still_resolved_as_kic(self, monkeypatch):
        mock_query(monkeypatch, {"kepid = 10797460": [K00752_01, K00752_02]})
        res = scs.resolve_object_id("10797460")
        assert res.identifier_type == "kic"
        assert res.match_status in ("matched_koi", "matched_star")


class TestObjectIdValidation:
    def test_overly_long_object_id_raises(self):
        with pytest.raises(scs.InvalidObjectIdError):
            scs.resolve_object_id("K" * 100)


class TestCatalogMissingParameter:
    """STEP 9: a real, matched catalog record can still have a specific
    field blank -- this must surface as that one field being unavailable,
    never a silent 0/default, while every other resolvable field on the
    same record still comes through."""

    def test_matched_row_with_a_blank_stellar_field(self, monkeypatch):
        mock_query(monkeypatch, {"kepoi_name = 'K01046.01'": [K01046_01_MOSTLY_BLANK]})
        res = scs.resolve_object_id("K01046.01")
        assert res.match_status == "matched_koi"
        assert res.field_available["koi_steff"] is False
        assert res.fields["koi_steff"] is None
        assert res.field_available["koi_slogg"] is False
        assert res.field_available["koi_srad"] is False
        assert res.field_available["koi_score"] is False
        assert res.field_available["ra"] is True
        assert res.fields["ra"] == pytest.approx(293.287990, rel=1e-5)
        assert res.field_available["koi_kepmag"] is True

    def test_false_positive_has_zero_score_available_not_missing(self, monkeypatch):
        # koi_score == 0.0 is a real, present value -- must not be treated as
        # "unavailable" just because it's falsy.
        mock_query(monkeypatch, {"kepoi_name = 'K00753.01'": [K00753_01]})
        res = scs.resolve_object_id("K00753.01")
        assert res.field_available["koi_score"] is True
        assert res.fields["koi_score"] == pytest.approx(0.0)


class TestNasaApiFailureHandling:
    """STEP 4/8: timeouts, HTTP errors, and malformed responses must never
    be silently swallowed or fabricate a value -- they surface as an
    explicit 'lookup_error' resolution distinct from a legitimate
    'not_found', with every field left unavailable."""

    def test_timeout(self, monkeypatch):
        mock_query_raises(monkeypatch, NasaApiTimeoutError("timed out"))
        res = scs.resolve_object_id("KIC 10797460")
        assert res.match_status == "lookup_error"
        assert all(v is None for v in res.fields.values())
        assert "not respond" in res.note.lower()

    def test_unreachable(self, monkeypatch):
        mock_query_raises(monkeypatch, NasaApiUnavailableError("dns failure"))
        res = scs.resolve_object_id("KIC 10797460")
        assert res.match_status == "lookup_error"
        assert "could not be reached" in res.note.lower()

    def test_http_error(self, monkeypatch):
        mock_query_raises(monkeypatch, NasaApiHttpError(500, "internal error"))
        res = scs.resolve_object_id("KIC 10797460")
        assert res.match_status == "lookup_error"
        assert "500" in res.note

    def test_malformed_response(self, monkeypatch):
        mock_query_raises(monkeypatch, NasaApiMalformedResponseError("not json"))
        res = scs.resolve_object_id("KIC 10797460")
        assert res.match_status == "lookup_error"
        assert "unexpected response" in res.note.lower()


class TestCaching:
    def test_repeated_lookup_for_the_same_object_hits_cache_not_network(self, monkeypatch):
        calls = mock_query(monkeypatch, {"kepid = 10797460": [K00752_01, K00752_02]})
        scs.resolve_object_id("10797460")
        scs.resolve_object_id("KIC 10797460")  # different spelling, same normalized query
        assert len(calls) == 1
