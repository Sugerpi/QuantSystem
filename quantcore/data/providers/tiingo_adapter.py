"""Tiingo adapter（validation，規格 §4.5）。

免費 API key，adjClose 含息，供跨源總報酬比對。key 由 secrets.get_secret 讀取。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from quantcore.data.provider import PRICE_COLUMNS, empty_prices
from quantcore.data.secrets import get_secret

_BASE = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"


def normalize_tiingo(payload: list[dict], ticker: str) -> pd.DataFrame:
    """Tiingo REST JSON（list[dict]）→ tidy 長格式。

    以 utc=True 解析日期，確保無論輸入是否帶時區資訊，
    都能穩定得到 tz-naive 的正規化日期（供 Task 10 跨源日期對齊）。
    """
    if not payload:
        return empty_prices()
    df = pd.DataFrame(payload)
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["date"], utc=True).dt.tz_localize(None).dt.normalize(),
            "ticker": ticker,
            "close": df["close"].to_numpy(dtype="float64"),
            "adj_close": df["adjClose"].to_numpy(dtype="float64"),
            "volume": df["volume"].to_numpy(dtype="float64"),
        }
    )
    return out[PRICE_COLUMNS].reset_index(drop=True)


class TiingoAdapter:
    """validation provider。網路邊界；離線測試以 normalize_tiingo 為準。"""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or get_secret("TIINGO_API_KEY")

    def fetch_prices(self, tickers: list[str], start: date, end: date) -> pd.DataFrame:
        import requests

        frames = []
        for t in tickers:
            resp = requests.get(
                _BASE.format(ticker=t),
                params={
                    "startDate": str(start),
                    "endDate": str(end),
                    "format": "json",
                    "token": self._api_key,
                },
                timeout=30,
            )
            resp.raise_for_status()
            frames.append(normalize_tiingo(resp.json(), t))
        return pd.concat(frames, ignore_index=True) if frames else empty_prices()

    def fetch_metadata(self, tickers: list[str]) -> dict:
        return {t: {"inception_date": None, "name": t} for t in tickers}

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.Series:
        raise NotImplementedError("Tiingo 不供本專案利率序列。")
