"""Tiingo 正規化：REST JSON payload → tidy 長格式。"""

from datetime import date

import pytest
import requests

from quantcore.data.provider import PRICE_COLUMNS
from quantcore.data.providers.tiingo_adapter import (
    _MAX_ATTEMPTS,
    TiingoAdapter,
    normalize_tiingo,
)


def _payload():
    return [
        {"date": "2020-01-02T00:00:00.000Z", "close": 101.0, "adjClose": 100.2, "volume": 1000000},
        {"date": "2020-01-03T00:00:00.000Z", "close": 102.5, "adjClose": 101.7, "volume": 1200000},
    ]


class _FakeResponse:
    """假 requests.Response：僅供離線測試使用，不觸網。"""

    def __init__(
        self, status_code: int, headers: dict | None = None, json_payload=None, http_error=None
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_payload = json_payload
        self._http_error = http_error

    def raise_for_status(self):
        if self._http_error is not None:
            raise self._http_error
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._json_payload


def _one_row_payload():
    return [
        {"date": "2020-01-02T00:00:00.000Z", "close": 101.0, "adjClose": 100.2, "volume": 1000000}
    ]


def test_fetch_prices_retries_then_succeeds(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            return _FakeResponse(429, headers={})
        return _FakeResponse(200, json_payload=_one_row_payload())

    monkeypatch.setattr(requests, "get", fake_get)
    import time

    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)

    adapter = TiingoAdapter(api_key="dummy")
    tidy = adapter.fetch_prices(["SPY"], date(2020, 1, 1), date(2020, 1, 3))

    assert not tidy.empty
    assert list(tidy.columns) == PRICE_COLUMNS
    assert len(calls) == 2


def test_fetch_prices_raises_after_persistent_429(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(1)
        return _FakeResponse(429, headers={})

    monkeypatch.setattr(requests, "get", fake_get)
    import time

    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)

    adapter = TiingoAdapter(api_key="dummy")
    with pytest.raises(RuntimeError, match="速率限制"):
        adapter.fetch_prices(["SPY"], date(2020, 1, 1), date(2020, 1, 3))

    assert len(calls) == _MAX_ATTEMPTS


def test_fetch_prices_non_429_error_is_redacted(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(
            401,
            headers={},
            http_error=requests.HTTPError(
                "401 Client Error: Unauthorized for url: "
                "https://api.tiingo.com/tiingo/daily/SPY/prices?token=SECRET123&format=json"
            ),
        )

    monkeypatch.setattr(requests, "get", fake_get)

    adapter = TiingoAdapter(api_key="dummy")
    with pytest.raises(RuntimeError) as exc_info:
        adapter.fetch_prices(["SPY"], date(2020, 1, 1), date(2020, 1, 3))

    msg = str(exc_info.value)
    assert "token=***" in msg
    assert "SECRET123" not in msg


def test_normalize_columns_and_values():
    tidy = normalize_tiingo(_payload(), "SPY")
    assert list(tidy.columns) == PRICE_COLUMNS
    assert len(tidy) == 2
    assert tidy["adj_close"].iloc[1] == 101.7
    assert (tidy["ticker"] == "SPY").all()


def test_normalize_empty_payload():
    tidy = normalize_tiingo([], "SPY")
    assert list(tidy.columns) == PRICE_COLUMNS
    assert tidy.empty


def test_redact_token_removes_key():
    from quantcore.data.providers.tiingo_adapter import _redact_token

    msg = (
        "401 Client Error: Unauthorized for url: "
        "https://api.tiingo.com/tiingo/daily/SPY/prices"
        "?startDate=2020-01-01&token=SECRETKEY123&format=json"
    )
    red = _redact_token(msg)
    assert "SECRETKEY123" not in red
    assert "token=***" in red
