"""波動預測品質評估（規格 §5.4）。

純函數：QLIKE（對預測偏誤穩健）與 Mincer-Zarnowitz 回歸 R²。
刻意置於 models 層而非 backtest/metrics.py，以維持依賴方向單向
（models 不得依賴 backtest；設計文件 §3.1）。
"""

from __future__ import annotations

import numpy as np


def qlike(realized_var: np.ndarray, forecast_var: np.ndarray) -> float:
    """QLIKE = mean( r/f − log(r/f) − 1 )。完美預測為 0，偏誤時為正。"""
    r = np.asarray(realized_var, dtype="float64")
    f = np.asarray(forecast_var, dtype="float64")
    if np.any(f <= 0) or np.any(r <= 0):
        raise ValueError("QLIKE 需 realized/forecast 變異數皆為正")
    ratio = r / f
    return float(np.mean(ratio - np.log(ratio) - 1.0))


def mincer_zarnowitz_r2(realized_var: np.ndarray, forecast_var: np.ndarray) -> float:
    """realized ~ a + b·forecast 的 OLS R²。"""
    r = np.asarray(realized_var, dtype="float64")
    f = np.asarray(forecast_var, dtype="float64")
    x = np.column_stack([np.ones_like(f), f])
    beta, *_ = np.linalg.lstsq(x, r, rcond=None)
    pred = x @ beta
    ss_res = float(np.sum((r - pred) ** 2))
    ss_tot = float(np.sum((r - r.mean()) ** 2))
    if ss_tot == 0:
        return 0.0
    return 1.0 - ss_res / ss_tot
