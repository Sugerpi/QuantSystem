"""FRED adapter（DTB3 現金利率，規格 §4.4）。

keyless：使用 pandas-datareader 的 FRED 端點（fredgraph.csv），無需 API key。
"""

from __future__ import annotations

from datetime import date

import pandas as pd


def normalize_fred(raw: pd.Series) -> pd.Series:
    """FRED 原始序列 → tz-naive、依日期排序、保留原名。"""
    s = raw.copy()
    s.index = pd.to_datetime(s.index)
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    s.index = s.index.normalize()
    return s.sort_index()


class FredAdapter:
    """DTB3 provider。keyless 網路邊界。"""

    def fetch_prices(self, tickers, start, end):
        raise NotImplementedError("FRED 只供利率序列，用 fetch_series。")

    def fetch_metadata(self, tickers):
        raise NotImplementedError

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.Series:
        from pandas_datareader import data as pdr

        raw = pdr.DataReader(series_id, "fred", start, end)[series_id]
        return normalize_fred(raw.rename(series_id))
