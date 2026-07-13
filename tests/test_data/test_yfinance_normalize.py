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
