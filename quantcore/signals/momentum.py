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

    tbill 累積：DTB3（年化 %）→ 日利率（÷100 ÷252），取 ≤ t 的末 lookback 日複利。
    所有資產共用同一 t，故 tbill 窗只算一次。bar 不足者略過（與動量一致）。

    前置條件：rates 至少含 lookback 日；每檔資產末根對齊 rates 末日 t（由上游 eligibility 保證，
    故所有資產共用同一 tbill 窗）；DTB3 已 ffill 假日（資料層職責，§1.5）。窗內若有 NaN，
    tbill_cum 為 NaN、所有資產判為 fail——此情形應由資料層驗證擋下（§4.3）。
    """
    r = rates.sort_values("date")["DTB3"].to_numpy() / 100.0 / _DAYS_PER_YEAR
    daily = r[-lookback:]
    if len(daily) < lookback:
        raise ValueError(f"rates 不足 {lookback} 日，無法對齊絕對動量窗（僅 {len(daily)} 日）")
    tbill_cum = float(np.prod(1.0 + daily) - 1.0)

    out: dict[str, bool] = {}
    for ticker, g in prices.groupby("ticker", sort=True):
        s = g.sort_values("date")["adj_close"].to_numpy()
        if len(s) < lookback + 1:
            continue
        tr = float(s[-1] / s[-1 - lookback] - 1.0)
        out[ticker] = bool(tr - tbill_cum > 0.0)
    return out
