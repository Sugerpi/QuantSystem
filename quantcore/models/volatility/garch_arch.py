"""GARCH(1,1)-t 透過 arch 套件（規格 §5.2，Phase 4 正式路徑）。

v1 固定 GARCH(1,1)-t，不做 AIC 選規格。多步用 arch 的 analytic forecast
（GARCH(1,1) 閉式解析遞迴，決定性，符合 INV-6）。失敗拋 GarchDegenerateError。
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from quantcore.models.volatility.base import _SCALE, GarchDegenerateError, VolatilityModel


def _build_arch_model(scaled_array: np.ndarray, o: int = 0):
    """建 GARCH(1,1)-t（×100 尺度）。o>0 啟用 GJR 非對稱項。_estimate 與濾波
    共用，使模型規格單一來源——規格若變（dist/p/o/q）兩條路徑不會靜默分歧。"""
    from arch import arch_model

    return arch_model(scaled_array, mean="Constant", vol="GARCH", p=1, o=o, q=1, dist="t")


class GarchArch(VolatilityModel):
    enforce_stationarity = True
    _min_obs = 100  # GARCH-t MLE 需足夠樣本
    _o = 0  # arch 非對稱階數；GjrGarchArch 覆寫為 1

    def _estimate(self, scaled_returns: pd.Series) -> None:
        am = _build_arch_model(scaled_returns.to_numpy(), o=self._o)
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
        if self._o >= 1:
            self._params["gamma"] = float(pr["gamma[1]"])
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
        """完整 arch 參數向量，供 fix() 濾波。標準 GARCH 為
        [mu, omega, alpha[1], beta[1], nu]；GJR（_o≥1）為
        [mu, omega, alpha[1], gamma[1], beta[1], nu]。"""
        return np.asarray(self._arch_params, dtype="float64")

    @property
    def standardized_residuals(self) -> pd.Series:
        # r_t/σ_t（尺度不變：×100 分子分母相消），與 Ewma 一致、符合 base 契約。
        # 用 arch 的條件波動而非 res.std_resid（後者在 mean="Constant" 下已去估計均值），
        # 確保 GARCH 與 EWMA fallback 資產的殘差定義一致（Phase 5 DCC 唯一輸入）。
        cond_vol = np.asarray(self._res.conditional_volatility, dtype="float64")
        return pd.Series(self._scaled.to_numpy() / cond_vol, index=self._index)


class GjrGarchArch(GarchArch):
    """GJR-GARCH(1,1)-t：加非對稱槓桿項 γ（arch o=1）。其餘估計/預測/殘差
    慣例全繼承 GarchArch（×100 尺度、Student-t、analytic 多步）。"""

    _o = 1


def garch_filter_forecast(
    fixed_params: np.ndarray, returns: pd.Series, horizon: int, o: int = 0
) -> np.ndarray:
    """以固定 arch 參數對 returns 濾波（不跑 MLE），回每步變異數（已 ÷100² 還原）。

    fixed_params 為完整 arch 向量（GarchArch.arch_params）。§5.2 的便宜濾波路徑。
    """
    if horizon < 1:
        raise ValueError(f"horizon 必須 ≥ 1，收到 {horizon}")
    r = returns.astype("float64").dropna()
    am = _build_arch_model(r.to_numpy() * _SCALE, o=o)
    res = am.fix(np.asarray(fixed_params, dtype="float64"))
    fc = res.forecast(horizon=horizon, method="analytic", reindex=False)
    out = np.asarray(fc.variance.to_numpy()[-1], dtype="float64") / (_SCALE**2)
    if not np.all(np.isfinite(out)):
        raise GarchDegenerateError("濾波多步預測含非有限值（固定參數退化）")
    return out


def garch_filter_residuals(fixed_params: np.ndarray, returns: pd.Series, o: int = 0) -> pd.Series:
    """以固定 arch 參數濾波，回標準化殘差 r_t/σ_t（帶 DatetimeIndex，供 DCC）。

    與 GarchArch.standardized_residuals 同定義（scaled_return / 條件波動），
    但用固定參數（不跑 MLE）——曝險檢查日的便宜路徑。
    """
    r = returns.astype("float64").dropna()
    am = _build_arch_model(r.to_numpy() * _SCALE, o=o)
    res = am.fix(np.asarray(fixed_params, dtype="float64"))
    cond_vol = np.asarray(res.conditional_volatility, dtype="float64")
    return pd.Series(r.to_numpy() * _SCALE / cond_vol, index=r.index)
