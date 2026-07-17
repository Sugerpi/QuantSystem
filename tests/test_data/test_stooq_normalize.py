"""Stooq 正規化：CSV（僅拆分調整，無含息 adj）→ tidy；adj_close = NaN。"""

import pandas as pd

from quantcore.data.provider import PRICE_COLUMNS
from quantcore.data.providers.stooq_adapter import normalize_stooq


def _csv_frame():
    return pd.DataFrame(
        {
            "Date": ["2020-01-02", "2020-01-03"],
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.5],
            "Volume": [1000000, 1200000],
        }
    )


def test_normalize_sets_adj_close_nan():
    tidy = normalize_stooq(_csv_frame(), "SPY")
    assert list(tidy.columns) == PRICE_COLUMNS
    assert tidy["adj_close"].isna().all()  # Stooq 不含息
    assert tidy["close"].iloc[0] == 101.0
