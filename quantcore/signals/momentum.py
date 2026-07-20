"""動量訊號（規格 §1.3、§1.4）。純函數，收 DataFrame，不 import backtest。

依賴方向（CLAUDE.md）：signals 為上游，只認 pandas。呼叫端（策略）持有 view，
把 view.prices / view.rates 傳入——比照 portfolio/selection.py 的設計。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_DAYS_PER_YEAR = 252


def cross_sectional_momentum(prices: pd.DataFrame, lookback: int, skip: int) -> dict[str, float]:
    """12-1 橫斷面動量：M_i = adj_close[t-skip] / adj_close[t-lookback] - 1。

    prices 為 point-in-time 切片（≤ t），須含 'ticker'/'date'/'adj_close'。
    bar 數 < lookback+1 者不產生分數（算不出 t-lookback）。
    """
    out: dict[str, float] = {}
    for ticker, g in prices.groupby("ticker", sort=True):
        s = g.sort_values("date")["adj_close"].to_numpy()
        if len(s) < lookback + 1:
            continue
        out[ticker] = float(s[-1 - skip] / s[-1 - lookback] - 1.0)
    return out


def absolute_momentum(prices: pd.DataFrame, rates: pd.DataFrame, lookback: int) -> dict[str, bool]:
    """時間序列動量（§1.4）：過去 lookback 日總報酬是否勝過同期 T-bill 累積。

    DTB3 為 FRED 聯邦營業日索引，與 NYSE 交易日曆不同步。此處比照 engine._daily_rates
    的慣例，把 DTB3 reindex 到價格的交易日軸並 ffill/bfill，使 tbill 窗與資產報酬窗落在
    同一組交易日；否則兩者只共用端點、不共用起點與中間日集。

    前置條件：所有資產末根對齊交易日末日 t（由上游 eligibility 保證，故 tbill 窗只算一次）。
    交易日不足 lookback、或窗內在 reindex+ffill+bfill 後仍為 NaN（DTB3 全空）時明確拋錯，
    而非靜默把全部部位轉現金。
    """
    trading_days = pd.DatetimeIndex(sorted(prices["date"].unique()))
    daily_rate = (
        rates.set_index("date")["DTB3"].reindex(trading_days).ffill().bfill()
        / 100.0
        / _DAYS_PER_YEAR
    ).to_numpy()
    window = daily_rate[-lookback:]
    if len(window) < lookback:
        raise ValueError(f"交易日不足 {lookback} 日，無法對齊絕對動量窗（僅 {len(window)} 日）")
    if not np.isfinite(window).all():
        raise ValueError("DTB3 窗內含 NaN（reindex+ffill/bfill 後仍缺），無法計算絕對動量 hurdle")
    tbill_cum = float(np.prod(1.0 + window) - 1.0)

    out: dict[str, bool] = {}
    for ticker, g in prices.groupby("ticker", sort=True):
        s = g.sort_values("date")["adj_close"].to_numpy()
        if len(s) < lookback + 1:
            continue
        tr = float(s[-1] / s[-1 - lookback] - 1.0)
        out[ticker] = bool(tr - tbill_cum > 0.0)
    return out
