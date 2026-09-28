"""
Tests for app/nasa_exoplanet_archive_client.py -- the raw HTTP/ADQL layer.
The live NASA Exoplanet Archive is NEVER called: every test monkeypatches
httpx.get with a fake response.
"""
import httpx
import pytest

from app.nasa_exoplanet_archive_client import (
    NasaApiHttpError,
    NasaApiMalformedResponseError,
    NasaApiTimeoutError,
    NasaApiUnavailableError,
    query_cumulative_table,
)


class FakeResponse:
    def __init__(self, status_code, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text

    def json(self):
        if self._json_body is _RAISE:
            raise ValueError("not valid json")
        return self._json_body


_RAISE = object()


class TestSuccessfulQuery:
    def test_returns_rows_from_a_well_formed_response(self, monkeypatch):
        rows = [{"kepid": 10797460, "koi_steff": 5455.0}]
        monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(200, rows))
        result = query_cumulative_table("kepid = 10797460")
        assert result == rows

    def test_empty_result_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(200, []))
        result = query_cumulative_table("kepid = 999999999")
        assert result == []

    def test_sends_the_expected_query_params(self, monkeypatch):
        captured = {}

        def fake_get(url, params=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["timeout"] = timeout
            return FakeResponse(200, [])

        monkeypatch.setattr(httpx, "get", fake_get)
        query_cumulative_table("kepid = 42")
        assert captured["params"]["format"] == "json"
        assert "from cumulative where kepid = 42" in captured["params"]["query"]
        assert "koi_steff" in captured["params"]["query"]  # only the needed fields are selected
        assert captured["timeout"] is not None


class TestFailureHandling:
    def test_timeout_raises_typed_error(self, monkeypatch):
        def fake_get(*a, **k):
            raise httpx.TimeoutException("timed out")
        monkeypatch.setattr(httpx, "get", fake_get)
        with pytest.raises(NasaApiTimeoutError):
            query_cumulative_table("kepid = 1")

    def test_connection_failure_raises_unavailable_error(self, monkeypatch):
        def fake_get(*a, **k):
            raise httpx.ConnectError("connection refused")
        monkeypatch.setattr(httpx, "get", fake_get)
        with pytest.raises(NasaApiUnavailableError):
            query_cumulative_table("kepid = 1")

    def test_non_200_status_raises_http_error_without_json_parsing(self, monkeypatch):
        def fake_get(*a, **k):
            return FakeResponse(400, _RAISE, text="<VOTABLE>error</VOTABLE>")
        monkeypatch.setattr(httpx, "get", fake_get)
        with pytest.raises(NasaApiHttpError) as exc_info:
            query_cumulative_table("select * from bogus")
        assert exc_info.value.status_code == 400

    def test_malformed_json_raises_malformed_response_error(self, monkeypatch):
        monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(200, _RAISE))
        with pytest.raises(NasaApiMalformedResponseError):
            query_cumulative_table("kepid = 1")

    def test_non_list_json_raises_malformed_response_error(self, monkeypatch):
        monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(200, {"unexpected": "shape"}))
        with pytest.raises(NasaApiMalformedResponseError):
            query_cumulative_table("kepid = 1")
