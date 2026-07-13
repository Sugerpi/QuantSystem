"""Tiingo 正規化：REST JSON payload → tidy 長格式。"""

from quantcore.data.provider import PRICE_COLUMNS
from quantcore.data.providers.tiingo_adapter import normalize_tiingo


def _payload():
    return [
        {"date": "2020-01-02T00:00:00.000Z", "close": 101.0, "adjClose": 100.2, "volume": 1000000},
        {"date": "2020-01-03T00:00:00.000Z", "close": 102.5, "adjClose": 101.7, "volume": 1200000},
    ]


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
