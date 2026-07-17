"""Twelve Data adapter（arbiter，規格 §4.5 第三源，取代失效的 Stooq）。

免費層 time_series 端點僅拆分調整、不含息，故 adj_close 設為 NaN，
只可比對價格報酬（與既有 Stooq arbiter 同一類）。key 由 secrets.get_secret 讀取。
"""

from __future__ import annotations

import re
import time
from datetime import date

import numpy as np
import pandas as pd

from quantcore.data.provider import PRICE_COLUMNS, empty_prices
from quantcore.data.secrets import get_secret

_BASE = "https://api.twelvedata.com/time_series"

# 網路邊界工程常數（非策略/config 參數，見 CLAUDE.md 硬性規則）。
_OUTPUTSIZE = 5000  # 免費層單次請求最大回傳筆數
_REQUEST_DELAY_SECONDS = 8.0  # 免費層 8 req/min，請求間節流
_RATE_WAIT_SECONDS = 61.0  # 遇分鐘級速率限制時等待
_MAX_ATTEMPTS = 4  # 單一 ticker 的總嘗試次數（含第一次）


def _redact_apikey(text: str) -> str:
    """遮蔽任何 apikey=… 查詢參數，避免 API key 出現在錯誤訊息/log。"""
    return re.sub(r"apikey=[^&\s]+", "apikey=***", text)


def normalize_twelvedata(values: list[dict], ticker: str) -> pd.DataFrame:
    """Twelve Data time_series JSON 的 values（list[dict]）→ tidy；adj_close = NaN（不含息）。"""
    if not values:
        return empty_prices()
    df = pd.DataFrame(values)
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["datetime"]).dt.normalize(),
            "ticker": ticker,
            "close": df["close"].astype("float64"),
            "adj_close": np.nan,
            "volume": df["volume"].astype("float64"),
        }
    )
    return out[PRICE_COLUMNS].reset_index(drop=True)


class TwelveDataAdapter:
    """arbiter provider（§4.5 第三源）。best-effort：單一 ticker 失敗不中止整體抓取。"""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or get_secret("TWELVEDATA_API_KEY")

    def _fetch_one(self, ticker: str, start: date, end: date) -> list:
        """單一 ticker 的請求，含分鐘級速率限制退避重試。

        回傳 Twelve Data time_series JSON 的 values（list[dict]，可能為空）。
        """
        import requests

        for attempt_index in range(_MAX_ATTEMPTS):
            time.sleep(_REQUEST_DELAY_SECONDS)  # 免費層 8 req/min，請求前先節流
            try:
                resp = requests.get(
                    _BASE,
                    params={
                        "symbol": ticker,
                        "interval": "1day",
                        "start_date": str(start),
                        "end_date": str(end),
                        "outputsize": _OUTPUTSIZE,
                        "order": "asc",
                        "apikey": self._api_key,
                    },
                    timeout=60,
                )
            except requests.RequestException as exc:
                raise RuntimeError(
                    f"TwelveData 請求失敗（{ticker}）：{_redact_apikey(str(exc))}"
                ) from None
            payload = resp.json()
            if payload.get("status") == "error":
                code = payload.get("code")
                if code == 429:
                    if attempt_index == _MAX_ATTEMPTS - 1:
                        raise RuntimeError(
                            f"TwelveData 速率限制（{ticker}）：重試 {_MAX_ATTEMPTS} 次仍失敗，"
                            "免費額度為每分鐘上限，請稍後再試。"
                        )
                    time.sleep(_RATE_WAIT_SECONDS)
                    continue
                raise RuntimeError(f"TwelveData 錯誤（{ticker}，code={code}）")
            return payload.get("values", [])
        # 理論上不可達：迴圈要嘛在最後一次 429 時 raise，要嘛提早 return。
        raise RuntimeError(f"TwelveData 速率限制（{ticker}）：重試 {_MAX_ATTEMPTS} 次仍失敗。")

    def fetch_prices(self, tickers: list[str], start: date, end: date) -> pd.DataFrame:
        """best-effort：單一 ticker 失敗只跳過（貢獻空值），不中止整體 arbiter 抓取。"""
        frames = []
        for t in tickers:
            try:
                values = self._fetch_one(t, start, end)
            except RuntimeError as exc:
                print(f"[TwelveDataAdapter] 跳過 {t}：{_redact_apikey(str(exc))}")
                continue
            frames.append(normalize_twelvedata(values, t))
        return pd.concat(frames, ignore_index=True) if frames else empty_prices()

    def fetch_metadata(self, tickers: list[str]) -> dict:
        return {t: {"inception_date": None, "name": t} for t in tickers}

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.Series:
        raise NotImplementedError
