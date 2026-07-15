"""Twelve Data 正規化：time_series JSON values → tidy；adj_close = NaN（僅價格）。"""

from quantcore.data.provider import PRICE_COLUMNS
from quantcore.data.providers.twelvedata_adapter import (
    _redact_apikey,
    normalize_twelvedata,
)


def _values():
    return [
        {
            "datetime": "2006-08-25",
            "open": "129.64",
            "high": "130.25",
            "low": "129.55",
            "close": "129.81",
            "volume": "41756000",
        },
        {
            "datetime": "2006-08-28",
            "open": "129.90",
            "high": "130.40",
            "low": "129.70",
            "close": "130.10",
            "volume": "38000000",
        },
    ]


def test_normalize_columns_and_types():
    tidy = normalize_twelvedata(_values(), "SPY")
    assert list(tidy.columns) == PRICE_COLUMNS
    assert len(tidy) == 2
    assert (tidy["ticker"] == "SPY").all()
    assert tidy["close"].iloc[0] == 129.81
    assert tidy["adj_close"].isna().all()  # TD time_series 為價格，無含息 → NaN
    assert tidy["date"].dtype.kind == "M"


def test_normalize_empty():
    tidy = normalize_twelvedata([], "SPY")
    assert list(tidy.columns) == PRICE_COLUMNS
    assert tidy.empty


def test_redact_apikey():
    msg = "error for url https://api.twelvedata.com/time_series?symbol=SPY&apikey=SECRET123&outputsize=5000"
    red = _redact_apikey(msg)
    assert "SECRET123" not in red
    assert "apikey=***" in red
