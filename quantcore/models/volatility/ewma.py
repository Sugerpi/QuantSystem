"""RiskMetrics EWMA（λ=0.94，規格 §5.3）。

消融基線 + GARCH fallback（設計文件 §1.4），兩者共用此實作。
EWMA 是 IGARCH（α+β=1），enforce_stationarity=False 豁免 base 的平穩性檢查。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantcore.models.volatility.base import VolatilityModel


class Ewma(VolatilityModel):
    enforce_stationarity = False
    _min_obs = 2

    def __init__(self, lam: float):
        if not 0 < lam < 1:
            raise ValueError(f"EWMA λ 必須落在 (0,1)，收到 {lam}")
        self._lam = float(lam)

    def _estimate(self, scaled_returns: pd.Series) -> None:
        lam = self._lam
        r = scaled_returns.to_numpy()
        h = float(np.var(r, ddof=1))  # seed = 樣本變異數
        cond_var = np.empty(len(r), dtype="float64")
        for t in range(len(r)):
            cond_var[t] = h  # 預測 r_t 的條件變異數
            h = lam * h + (1 - lam) * r[t] ** 2
        self._cond_var = cond_var  # ×100 尺度，長度 = len(r)
        self._last_var = h  # 預測 r_{T+1} 的條件變異數
        self._scaled = scaled_returns

    def _forecast_scaled(self, horizon: int) -> np.ndarray:
        return np.full(horizon, self._last_var, dtype="float64")

    @property
    def params(self) -> dict[str, float]:
        return {"lambda": self._lam}

    @property
    def standardized_residuals(self) -> pd.Series:
        return self._scaled / np.sqrt(self._cond_var)
