"""yfinance 正規化：單一 ticker 原始 frame → tidy 長格式。"""

import pandas as pd

from quantcore.data.provider import PRICE_COLUMNS
from quantcore.data.providers.yfinance_adapter import normalize_yfinance


def _raw_single_ticker():
    idx = pd.to_datetime(["2020-01-02", "2020-01-03"])
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.5],
            "Adj Close": [100.2, 101.7],
            "Volume": [1_000_000, 1_200_000],
        },
        index=idx,
    )


def test_normalize_shape_and_columns():
    tidy = normalize_yfinance(_raw_single_ticker(), "SPY")
    assert list(tidy.columns) == PRICE_COLUMNS
    assert len(tidy) == 2
    assert (tidy["ticker"] == "SPY").all()
    assert tidy["adj_close"].iloc[0] == 100.2
    assert tidy["date"].dtype.kind == "M"


def test_normalize_empty_returns_schema():
    tidy = normalize_yfinance(pd.DataFrame(), "SPY")
    assert list(tidy.columns) == PRICE_COLUMNS
    assert tidy.empty


def _raw_multiindex():
    idx = pd.to_datetime(["2020-01-02", "2020-01-03"])
    cols = pd.MultiIndex.from_tuples(
        [
            ("Open", "SPY"),
            ("High", "SPY"),
            ("Low", "SPY"),
            ("Close", "SPY"),
            ("Adj Close", "SPY"),
            ("Volume", "SPY"),
        ]
    )
    data = [
        [100.0, 102.0, 99.0, 101.0, 100.2, 1_000_000],
        [101.0, 103.0, 100.0, 102.5, 101.7, 1_200_000],
    ]
    return pd.DataFrame(data, index=idx, columns=cols)


def test_normalize_flattens_multiindex_columns():
    tidy = normalize_yfinance(_raw_multiindex(), "SPY")
    assert list(tidy.columns) == PRICE_COLUMNS
    assert len(tidy) == 2
    assert tidy["adj_close"].iloc[1] == 101.7


def test_normalize_handles_tz_aware_index():
    raw = _raw_single_ticker()
    raw.index = raw.index.tz_localize("US/Eastern")
    tidy = normalize_yfinance(raw, "SPY")
    assert tidy["date"].dt.tz is None
    assert tidy["date"].iloc[0] == pd.Timestamp("2020-01-02")
