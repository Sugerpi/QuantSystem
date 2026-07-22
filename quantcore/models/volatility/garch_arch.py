"""GARCH(1,1)-t 透過 arch 套件（規格 §5.2，Phase 4 正式路徑）。

v1 固定 GARCH(1,1)-t，不做 AIC 選規格。多步用 arch 的 analytic forecast
（GARCH(1,1) 閉式解析遞迴，決定性，符合 INV-6）。失敗拋 GarchDegenerateError。
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from quantcore.models.volatility.base import GarchDegenerateError, VolatilityModel


class GarchArch(VolatilityModel):
    enforce_stationarity = True
    _min_obs = 100  # GARCH-t MLE 需足夠樣本

    def _estimate(self, scaled_returns: pd.Series) -> None:
        from arch import arch_model

        am = arch_model(
            scaled_returns.to_numpy(),
            mean="Constant",
            vol="GARCH",
            p=1,
            q=1,
            dist="t",
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = am.fit(disp="off", show_warning=False)
        if int(getattr(res, "convergence_flag", 0)) != 0:
            raise GarchDegenerateError(f"GARCH 優化未收斂（flag={res.convergence_flag}）")
        pr = res.params
        self._params = {
            "omega": float(pr["omega"]),
            "alpha": float(pr["alpha[1]"]),
            "beta": float(pr["beta[1]"]),
            "nu": float(pr["nu"]),
        }
        if not all(np.isfinite(v) for v in self._params.values()):
            raise GarchDegenerateError("GARCH 參數含非有限值")
        self._res = res

    def _forecast_scaled(self, horizon: int) -> np.ndarray:
        fc = self._res.forecast(horizon=horizon, method="analytic", reindex=False)
        return np.asarray(fc.variance.to_numpy()[-1], dtype="float64")

    @property
    def params(self) -> dict[str, float]:
        return dict(self._params)

    @property
    def standardized_residuals(self) -> pd.Series:
        return pd.Series(np.asarray(self._res.std_resid, dtype="float64"))
