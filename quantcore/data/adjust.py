"""決定性含息調整（back-adjust，規格 §4.5）。

yfinance 的原始 close / dividends / splits 在多次抓取間位元穩定，但其
`Adj Close` 每次抓取都會重新計算並帶有 ~1e-6 的抖動，破壞快照可重現性
（INV-6 / AC-4）。本模組改為從穩定輸入自行決定性計算調整後收盤價。

純函數：不做 I/O、不連網、不依賴全域狀態。
"""

from __future__ import annotations

import pandas as pd


def adjusted_close(
    close: pd.Series,
    dividends: pd.Series,
    splits: pd.Series,
) -> pd.Series:
    """由原始 close + 股息 + 拆分 決定性計算含息調整收盤（back-adjust）。

    - close: DatetimeIndex（依日期遞增）→ 原始收盤價。
    - dividends: DatetimeIndex（除息日）→ 每股股息金額。可為空。
    - splits: DatetimeIndex（拆分日）→ 拆分比率（如 2:1 為 2.0，1:4 反拆為 0.25）。可為空。
    回傳與 close 對齊、錨定最新日（adj[最後]==close[最後]）的調整後收盤 Series（float64）。
    """
    factor = pd.Series(1.0, index=close.index, dtype="float64")

    # 拆分：事件日之前的所有日期除以比率，使序列連續。
    for event_date, ratio in splits.items():
        pos = _snap_to_position(close.index, event_date)
        if pos is None:
            continue
        factor.iloc[:pos] *= 1.0 / ratio

    # 股息：c_prev 讀取「事件日前一個交易日」的原始（未調整）close。
    for event_date, amount in dividends.items():
        pos = _snap_to_position(close.index, event_date)
        if pos is None or pos == 0:
            # 事件日為首個 close 日期（無前一天）或超出範圍 → 跳過。
            continue
        c_prev = close.iloc[pos - 1]
        factor.iloc[:pos] *= 1.0 - amount / c_prev

    adj_close = (close * factor).astype("float64")
    return adj_close


def _snap_to_position(index: pd.DatetimeIndex, event_date) -> int | None:
    """將事件日期 snap 到 index 中第一個 >= event_date 的位置；找不到則回傳 None。"""
    event_ts = pd.Timestamp(event_date)
    pos = index.searchsorted(event_ts, side="left")
    if pos >= len(index):
        return None
    return int(pos)
