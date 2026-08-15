"""波動率模型基底（規格 §5.1、INV-4）。

縮放（×100 估計 / ÷100² 還原）與 GARCH 平穩性檢查（α+β+0.5γ<1，純 GARCH γ=0）全在此完成——
INV-4 只有這一個地方能被違反。子類只實作 ×100 尺度的估計與預測。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

_SCALE = 100.0
DAYS_PER_YEAR = 252
# GJR 非對稱項係數：對稱條件分布下負向報酬指標 I(ε<0) 的期望值，
# 用於平穩條件 α+β+κγ<1（κ=0.5）。純 GARCH γ=0 時退化為 α+β<1。
_GJR_NEG_INDICATOR_EXPECTATION = 0.5


class GarchDegenerateError(RuntimeError):
    """GARCH 估計退化：不收斂、非平穩（α+β+0.5γ≥1，純 GARCH γ=0）或參數落邊界致預測非有限。

    由 fit_volatility 捕捉並退回 EWMA（設計文件 §1.4）。
    """


class VolatilityModel(ABC):
    """波動率模型 ABC。

    fit 收「報酬」序列（非價格）；forecast 回「每步變異數」，已還原縮放。
    """

    #: GARCH 家族設 True 以啟用 α+β+0.5γ<1 檢查；EWMA（IGARCH，α+β=1）設 False。
    enforce_stationarity: bool = False
    #: fit 所需最小觀測數（子類覆寫）。
    _min_obs: int = 2

    _fitted: bool = False

    def fit(self, returns: pd.Series) -> VolatilityModel:
        r = returns.astype("float64").dropna()
        if len(r) < self._min_obs:
            raise ValueError(
                f"{type(self).__name__}.fit 需至少 {self._min_obs} 筆觀測，收到 {len(r)}"
            )
        self._estimate(r * _SCALE)
        if self.enforce_stationarity:
            self._check_stationarity()
        self._fitted = True
        return self

    def forecast(self, horizon: int) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("forecast 前須先 fit")
        if horizon < 1:
            raise ValueError(f"horizon 必須 ≥ 1，收到 {horizon}")
        scaled_var = np.asarray(self._forecast_scaled(horizon), dtype="float64")
        out = scaled_var / (_SCALE**2)
        if not np.all(np.isfinite(out)):
            raise GarchDegenerateError("多步預測含非有限值（參數退化）")
        return out

    def _check_stationarity(self) -> None:
        p = self.params
        # GJR 平穩條件 α+β+0.5γ<1（對稱分布下負向指標期望=0.5）；
        # 純 GARCH gamma 預設 0，退化為 α+β<1。
        persistence = (
            p.get("alpha", 0.0)
            + p.get("beta", 0.0)
            + _GJR_NEG_INDICATOR_EXPECTATION * p.get("gamma", 0.0)
        )
        if persistence >= 1.0:
            raise GarchDegenerateError(f"非平穩：α+β+0.5γ={persistence:.4f} ≥ 1（多步預測會發散）")

    @property
    @abstractmethod
    def params(self) -> dict[str, float]:
        """{'omega','alpha','beta','nu',...}（×100 尺度）；供落盤與慣例檢查。"""

    @property
    @abstractmethod
    def standardized_residuals(self) -> pd.Series:
        """標準化殘差 r_t/σ_t（尺度不變），供 Phase 5 DCC。"""

    @abstractmethod
    def _estimate(self, scaled_returns: pd.Series) -> None:
        """在 ×100 尺度估計並儲存內部狀態。失敗拋 GarchDegenerateError。"""

    @abstractmethod
    def _forecast_scaled(self, horizon: int) -> np.ndarray:
        """×100 尺度的每步變異數（長度 horizon）。"""


def annualize_variance_path(per_step_var: np.ndarray) -> float:
    """每步變異數 → 年化波動：sqrt(mean(Var))·sqrt(252)（規格 §1.6 Step 1 的聚合）。"""
    return float(np.sqrt(np.mean(per_step_var)) * np.sqrt(DAYS_PER_YEAR))
