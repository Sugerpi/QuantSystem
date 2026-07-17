"""Tiingo adapter（validation，規格 §4.5）。

免費 API key，adjClose 含息，供跨源總報酬比對。key 由 secrets.get_secret 讀取。
"""

from __future__ import annotations

import re
import time
from datetime import date

import pandas as pd

from quantcore.data.provider import PRICE_COLUMNS, empty_prices
from quantcore.data.secrets import get_secret

_BASE = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"

# 網路邊界工程常數（非策略/config 參數，見 CLAUDE.md 硬性規則）。
_MAX_ATTEMPTS = 5  # 429 重試總嘗試次數（含第一次）
_BACKOFF_BASE_SECONDS = (
    2.0  # 指數退避基數：等待秒數 = base ** attempt_index，attempt_index 從 0 起（1,2,4,8…）
)


def _redact_token(text: str) -> str:
    """遮蔽任何 token=… 查詢參數，避免 API key 出現在錯誤訊息/log。"""
    return re.sub(r"token=[^&\s]+", "token=***", text)


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

    def _fetch_one(self, ticker: str, start: date, end: date) -> list:
        """單一 ticker 的請求，含 429 速率限制退避重試。

        回傳 Tiingo REST JSON 原始 payload（list[dict]）。
        """
        import requests

        for attempt_index in range(_MAX_ATTEMPTS):
            resp = requests.get(
                _BASE.format(ticker=ticker),
                params={
                    "startDate": str(start),
                    "endDate": str(end),
                    "format": "json",
                    "token": self._api_key,
                },
                timeout=30,
            )
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after is not None else None
                except ValueError:
                    wait = None
                if wait is None:
                    wait = _BACKOFF_BASE_SECONDS**attempt_index
                if attempt_index == _MAX_ATTEMPTS - 1:
                    raise RuntimeError(
                        f"Tiingo 速率限制（429）：{ticker} 重試 {_MAX_ATTEMPTS} 次仍失敗，"
                        "免費額度為每小時上限，請稍後再試。"
                    )
                time.sleep(wait)
                continue
            try:
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise RuntimeError(
                    f"Tiingo 請求失敗（{ticker}）：{_redact_token(str(exc))}"
                ) from None
            return resp.json()
        # 理論上不可達：迴圈要嘛在最後一次 429 時 raise，要嘛提早 return。
        raise RuntimeError(f"Tiingo 速率限制（429）：{ticker} 重試 {_MAX_ATTEMPTS} 次仍失敗。")

    def fetch_prices(self, tickers: list[str], start: date, end: date) -> pd.DataFrame:
        frames = [normalize_tiingo(self._fetch_one(t, start, end), t) for t in tickers]
        return pd.concat(frames, ignore_index=True) if frames else empty_prices()

    def fetch_metadata(self, tickers: list[str]) -> dict:
        return {t: {"inception_date": None, "name": t} for t in tickers}

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.Series:
        raise NotImplementedError("Tiingo 不供本專案利率序列。")
