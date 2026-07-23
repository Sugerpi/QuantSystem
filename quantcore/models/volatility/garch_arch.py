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
        if int(getattr(res, "convergence_flag", 1)) != 0:
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
        self._index = scaled_returns.index
        self._scaled = scaled_returns
        self._arch_params = np.asarray(res.params.to_numpy(), dtype="float64")

    def _forecast_scaled(self, horizon: int) -> np.ndarray:
        fc = self._res.forecast(horizon=horizon, method="analytic", reindex=False)
        return np.asarray(fc.variance.to_numpy()[-1], dtype="float64")

    @property
    def params(self) -> dict[str, float]:
        return dict(self._params)

    @property
    def arch_params(self) -> np.ndarray:
        """完整 arch 參數向量 [mu, omega, alpha[1], beta[1], nu]，供 fix() 濾波。"""
        return np.asarray(self._arch_params, dtype="float64")

    @property
    def standardized_residuals(self) -> pd.Series:
        # r_t/σ_t（尺度不變：×100 分子分母相消），與 Ewma 一致、符合 base 契約。
        # 用 arch 的條件波動而非 res.std_resid（後者在 mean="Constant" 下已去估計均值），
        # 確保 GARCH 與 EWMA fallback 資產的殘差定義一致（Phase 5 DCC 唯一輸入）。
        cond_vol = np.asarray(self._res.conditional_volatility, dtype="float64")
        return pd.Series(self._scaled.to_numpy() / cond_vol, index=self._index)


_SCALE = 100.0  # ×100 估計 / ÷100² 還原，慣例同 base（INV-4）；一致性由 test 鎖住


def garch_filter_forecast(fixed_params: np.ndarray, returns: pd.Series, horizon: int) -> np.ndarray:
    """以固定 arch 參數對 returns 濾波（不跑 MLE），回每步變異數（已 ÷100² 還原）。

    fixed_params 為完整 arch 向量（GarchArch.arch_params）。§5.2 的便宜濾波路徑。
    """
    from arch import arch_model

    r = returns.astype("float64").dropna()
    am = arch_model(r.to_numpy() * _SCALE, mean="Constant", vol="GARCH", p=1, q=1, dist="t")
    res = am.fix(np.asarray(fixed_params, dtype="float64"))
    fc = res.forecast(horizon=horizon, method="analytic", reindex=False)
    return np.asarray(fc.variance.to_numpy()[-1], dtype="float64") / (_SCALE**2)
