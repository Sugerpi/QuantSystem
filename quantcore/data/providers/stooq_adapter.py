"""Stooq adapter（arbiter，規格 §4.5；v1 預留，暫不併入交叉驗證）。

免金鑰；僅拆分調整、不含息，故 adj_close 設為 NaN，只可比對價格報酬。
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from quantcore.data.provider import PRICE_COLUMNS, empty_prices

_URL = "https://stooq.com/q/d/l/?s={ticker}.us&d1={d1}&d2={d2}&i=d"


def normalize_stooq(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Stooq CSV frame → tidy；adj_close = NaN（不含息）。"""
    if raw is None or raw.empty:
        return empty_prices()
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["Date"]).dt.normalize(),
            "ticker": ticker,
            "close": raw["Close"].to_numpy(dtype="float64"),
            "adj_close": np.nan,
            "volume": raw["Volume"].to_numpy(dtype="float64"),
        }
    )
    return out[PRICE_COLUMNS].reset_index(drop=True)


class StooqAdapter:
    """arbiter provider（預留）。網路邊界。"""

    def fetch_prices(self, tickers: list[str], start: date, end: date) -> pd.DataFrame:
        import io

        import requests

        frames = []
        for t in tickers:
            url = _URL.format(
                ticker=t.lower(),
                d1=f"{start:%Y%m%d}",
                d2=f"{end:%Y%m%d}",
            )
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            frames.append(normalize_stooq(pd.read_csv(io.StringIO(resp.text)), t))
        return pd.concat(frames, ignore_index=True) if frames else empty_prices()

    def fetch_metadata(self, tickers: list[str]) -> dict:
        return {t: {"inception_date": None, "name": t} for t in tickers}

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.Series:
        raise NotImplementedError
