"""動量訊號（規格 §1.3、§1.4）。純函數，收 DataFrame，不 import backtest。

依賴方向（CLAUDE.md）：signals 為上游，只認 pandas。呼叫端（策略）持有 view，
把 view.prices / view.rates 傳入——比照 portfolio/selection.py 的設計。
"""

from __future__ import annotations

import pandas as pd


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
