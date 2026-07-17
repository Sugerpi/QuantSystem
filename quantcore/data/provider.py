"""DataProvider 介面與 tidy schema（規格 §4.1）。

引擎任何模組不得 import 具體 adapter；只認識本 Protocol 與快照格式。
tidy 格式：columns = [date, ticker, close, adj_close, volume]。
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd

PRICE_COLUMNS = ["date", "ticker", "close", "adj_close", "volume"]


def empty_prices() -> pd.DataFrame:
    """回傳符合 tidy schema 的空 DataFrame。"""
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "ticker": pd.Series(dtype="object"),
            "close": pd.Series(dtype="float64"),
            "adj_close": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="float64"),
        }
    )


@runtime_checkable
class DataProvider(Protocol):
    def fetch_prices(self, tickers: list[str], start: date, end: date) -> pd.DataFrame:
        """tidy 格式：columns = [date, ticker, close, adj_close, volume]。"""
        ...

    def fetch_metadata(self, tickers: list[str]) -> dict:
        """每檔：inception_date、name（可含 asset_class）。"""
        ...

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.Series:
        """總經/利率序列（FRED 用），index 為日期。"""
        ...
