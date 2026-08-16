"""穩健性顯著性檢定純函式（規格 §3；設計 2026-08-16）。

無檔案 IO；隨機性由呼叫端以 cfg.seed 建 Generator 傳入（INV-6）。
所有 Sharpe 一律以每期（非年化）值進入公式（Bailey & López de Prado 慣例）。
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm

# Euler-Mascheroni 常數（expected max Sharpe 用）
_EULER = 0.5772156649015329


def psr(sr: float, n: int, skew: float, kurt: float, sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio。sr 為每期值，kurt 為非超額峰態（常態=3）。

    PSR = Φ( (sr − sr_benchmark)·√(n−1) / √(1 − skew·sr + ((kurt−1)/4)·sr²) )。
    n<2 或分母非正 → nan。
    """
    if n < 2:
        return float("nan")
    var = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr**2
    if not np.isfinite(var) or var <= 0.0:
        return float("nan")
    z = (sr - sr_benchmark) * np.sqrt(n - 1) / np.sqrt(var)
    return float(norm.cdf(z))


def expected_max_sharpe(sr_variance: float, n_trials: int) -> float:
    """N 次獨立試驗下的期望最大 Sharpe（Bailey & López de Prado 2014）。

    √V·[ (1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e)) ]。V≤0 或 N<2 → nan。
    """
    if n_trials < 2 or sr_variance <= 0.0:
        return float("nan")
    q1 = norm.ppf(1.0 - 1.0 / n_trials)
    q2 = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    return float(np.sqrt(sr_variance) * ((1.0 - _EULER) * q1 + _EULER * q2))


def deflated_sharpe_ratio(
    sr: float, n: int, skew: float, kurt: float, sr_variance: float, n_trials: int
) -> float:
    """Deflated Sharpe Ratio：以 expected_max_sharpe 為 benchmark 的 PSR。

    sr_variance = N 個試驗 Sharpe 的橫斷面變異；n_trials = 消融格數。
    benchmark 無法計算（nan）時回 nan。
    """
    sr_star = expected_max_sharpe(sr_variance, n_trials)
    if not np.isfinite(sr_star):
        return float("nan")
    return psr(sr, n, skew, kurt, sr_benchmark=sr_star)
