"""RiskMetrics EWMA 相關（λ=0.94，規格 §5.3）。DCC 必須在消融中打敗此基線。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantcore.models.correlation.base import normalize_to_correlation


def ewma_correlation(std_resid: pd.DataFrame, lam: float) -> pd.DataFrame:
    """收 date×ticker 標準化殘差，回 EWMA 相關矩陣（label-aligned，依 ticker 排序）。

    S_0 = 樣本共變異數；S_t = (1−λ)·ε_{t−1}ε_{t−1}' + λ·S_{t−1}；R = normalize(S_last)。
    無待估參數（λ 固定）。
    """
    if not 0 < lam < 1:
        raise ValueError(f"EWMA λ 必須落在 (0,1)，收到 {lam}")
    cols = sorted(std_resid.columns)
    E = std_resid[cols].dropna().to_numpy(dtype="float64")
    if len(E) < 2:
        raise ValueError("ewma_correlation 需至少 2 筆觀測")
    S = np.atleast_2d(np.cov(E, rowvar=False))
    for t in range(1, len(E)):
        e = E[t - 1][:, None]
        S = (1 - lam) * (e @ e.T) + lam * S
    R = normalize_to_correlation(S)
    return pd.DataFrame(R, index=cols, columns=cols)
