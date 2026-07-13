"""yfinance adapter（primary，規格 §4.1/§4.5）。

拆為薄網路邊界（fetch_prices/fetch_metadata/fetch_dividends）與純正規化函數
（normalize_yfinance）。引擎其他層不得 import 本模組。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

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


def normalize_yfinance(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """單一 ticker 的 yfinance 原始 frame → tidy 長格式。"""
    if raw is None or raw.empty:
        return empty_prices()
    out = pd.DataFrame(
        {
            "date": _to_naive_normalized_index(raw.index),
            "ticker": ticker,
            "close": raw["Close"].to_numpy(dtype="float64"),
            "adj_close": raw["Adj Close"].to_numpy(dtype="float64"),
            "volume": raw["Volume"].to_numpy(dtype="float64"),
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
            )
            frames.append(normalize_yfinance(raw, t))
        return pd.concat(frames, ignore_index=True) if frames else empty_prices()

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
        import yfinance as yf

        div = yf.Ticker(ticker).dividends
        if div is None or len(div) == 0:
            return pd.DataFrame(
                {
                    "date": pd.Series(dtype="datetime64[ns]"),
                    "dividend": pd.Series(dtype="float64"),
                }
            )
        if div.index.tz is not None:
            start_ts = pd.Timestamp(start, tz=div.index.tz)
            end_ts = pd.Timestamp(end, tz=div.index.tz)
        else:
            start_ts = pd.Timestamp(start)
            end_ts = pd.Timestamp(end)
        div = div[(div.index >= start_ts) & (div.index <= end_ts)]
        return pd.DataFrame(
            {
                "date": _to_naive_normalized_index(div.index),
                "dividend": div.to_numpy(dtype="float64"),
            }
        ).reset_index(drop=True)
