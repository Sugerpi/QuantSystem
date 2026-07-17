"""yfinance adapter（primary，規格 §4.1/§4.5）。

拆為薄網路邊界（fetch_prices/fetch_metadata/fetch_dividends）與純正規化函數
（normalize_yfinance）。引擎其他層不得 import 本模組。
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from quantcore.data.adjust import adjusted_close
from quantcore.data.provider import PRICE_COLUMNS, empty_prices


def _to_naive_normalized_index(idx: pd.Index) -> pd.DatetimeIndex:
    """將 index 轉為 tz-naive、去除時間部分的 DatetimeIndex。

    僅在 tz-aware 時才 tz_localize(None)；tz-naive 直接 normalize，
    避免 pandas 對已是 tz-naive 的 index 呼叫 tz_localize(None) 時拋出
    TypeError: Already tz-naive。
    """
    dt_idx = pd.to_datetime(idx)
    if dt_idx.tz is not None:
        dt_idx = dt_idx.tz_localize(None)
    return dt_idx.normalize()


def _dividend_series(raw_div: pd.Series | None, start: date, end: date) -> pd.Series:
    """將 yfinance 原始股息 Series 正規化為 tz-naive、去時間部分（除息日→金額）。

    並裁切到 [start, end]。
    """
    if raw_div is None or len(raw_div) == 0:
        return pd.Series(dtype="float64")
    s = raw_div.copy()
    idx = pd.to_datetime(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    s = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]
    return s.astype(np.float64)


def normalize_yfinance(raw: pd.DataFrame, ticker: str, dividends: pd.Series) -> pd.DataFrame:
    """單一 ticker 的 yfinance 原始 frame → tidy 長格式。

    adj_close 由 close + 股息以 adjusted_close 自建（決定性）；splits 傳空，因
    yfinance 的 Close（auto_adjust=False）已拆分調整（傳 splits 會重複調整）。
    """
    if raw is None or raw.empty:
        return empty_prices()
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.copy()
        raw.columns = raw.columns.get_level_values(0)
    date_index = _to_naive_normalized_index(raw.index)
    close = pd.Series(raw["Close"].to_numpy(dtype=np.float64), index=date_index)
    adj = adjusted_close(close, dividends, pd.Series(dtype="float64"))
    out = pd.DataFrame(
        {
            "date": date_index,
            "ticker": ticker,
            "close": close.to_numpy(dtype=np.float64),
            "adj_close": adj.to_numpy(dtype=np.float64),
            "volume": raw["Volume"].to_numpy(dtype=np.float64),
        }
    )
    return out[PRICE_COLUMNS].reset_index(drop=True)


class YFinanceAdapter:
    """primary provider。網路邊界；離線測試以 normalize_yfinance 為準。"""

    def fetch_prices(self, tickers: list[str], start: date, end: date) -> pd.DataFrame:
        import yfinance as yf

        frames = []
        for t in tickers:
            raw = yf.download(
                t,
                start=start,
                end=end,
                auto_adjust=False,
                actions=False,
                progress=False,
                multi_level_index=False,
            )
            div = self._fetch_dividends_series(t, start, end)
            frames.append(normalize_yfinance(raw, t, div))
        return pd.concat(frames, ignore_index=True) if frames else empty_prices()

    def _fetch_dividends_series(self, ticker: str, start: date, end: date) -> pd.Series:
        """抓取單一 ticker 的原始股息並正規化（除息日 → 金額）。"""
        import yfinance as yf

        raw_div = yf.Ticker(ticker).dividends
        return _dividend_series(raw_div, start, end)

    def fetch_metadata(self, tickers: list[str]) -> dict:
        import yfinance as yf

        meta: dict = {}
        for t in tickers:
            info = yf.Ticker(t).history_metadata
            first = info.get("firstTradeDate") if isinstance(info, dict) else None
            inception = (
                pd.Timestamp(first, unit="s").strftime("%Y-%m-%d") if first is not None else None
            )
            meta[t] = {"inception_date": inception, "name": t}
        return meta

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.Series:
        raise NotImplementedError("yfinance 不供利率序列；DTB3 用 FredAdapter。")

    def fetch_dividends(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """§4.3-1 總報酬檢查用：columns = [date, dividend]。"""
        div = self._fetch_dividends_series(ticker, start, end)
        return pd.DataFrame(
            {
                "date": pd.DatetimeIndex(div.index),
                "dividend": div.to_numpy(dtype=np.float64),
            }
        ).reset_index(drop=True)
