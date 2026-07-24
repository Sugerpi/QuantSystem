"""refit/filter 波動預報器（規格 §5.2）。

昂貴的 GARCH 估計（選擇日 refit）與便宜的固定參數濾波（曝險檢查日 filter）分離。
內部一律切尾端 garch_window 根，成本 O(cap) 不隨回測時間膨脹。
有狀態：策略每 run 持有一實例（比照 bh_spy，引擎每 run 新建，不破 INV-6）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantcore.models.volatility import annualized_forecast_vol, fit_volatility
from quantcore.models.volatility.base import annualize_variance_path
from quantcore.models.volatility.garch_arch import GarchArch, garch_filter_forecast


@dataclass(frozen=True)
class _CacheEntry:
    kind: str  # 'garch' | 'ewma'
    arch_params: np.ndarray | None
    fell_back: bool


class VolForecaster:
    def __init__(self, spec: str, ewma_lambda: float, horizon: int, garch_window: int) -> None:
        self._spec = spec
        self._ewma_lambda = ewma_lambda
        self._horizon = horizon
        self._window = garch_window
        self._cache: dict[str, _CacheEntry] = {}
        if spec not in ("garch_arch", "ewma"):
            raise ValueError(f"VolForecaster 不支援 vol_model={spec!r}（可用：garch_arch | ewma）")

    def _tail(self, returns: pd.Series) -> pd.Series:
        return returns.iloc[-self._window :]

    def refit(self, ticker: str, returns: pd.Series) -> float:
        """選擇日：完整估計（含 fallback），快取，回年化 σ̂。"""
        outcome = fit_volatility(self._spec, self._tail(returns), ewma_lambda=self._ewma_lambda)
        if isinstance(outcome.model, GarchArch):
            self._cache[ticker] = _CacheEntry("garch", outcome.model.arch_params, outcome.fell_back)
        else:
            self._cache[ticker] = _CacheEntry("ewma", None, outcome.fell_back)
        return annualized_forecast_vol(outcome.model, self._horizon)

    def filter(self, ticker: str, returns: pd.Series) -> float:
        """曝險檢查日：以快取參數濾波（GARCH 走 fix()，EWMA 重跑）。無快取則 refit。"""
        if ticker not in self._cache:
            return self.refit(ticker, returns)
        entry = self._cache[ticker]
        window = self._tail(returns)
        if entry.kind == "garch":
            # 快取參數來自成功的 fit（α+β<1、ω 有限），GARCH(1,1) 解析多步變異數因此
            # 恆有限——garch_filter_forecast 的非有限守護在此不可達。
            return annualize_variance_path(
                garch_filter_forecast(entry.arch_params, window, self._horizon)
            )
        outcome = fit_volatility("ewma", window, ewma_lambda=self._ewma_lambda)
        return annualized_forecast_vol(outcome.model, self._horizon)

    def last_fell_back(self, ticker: str) -> bool:
        """該 ticker 上次 refit 是否退回 EWMA（供 4b-2 落盤 model_details）。
        前置條件：ticker 須已 refit 過（未 refit 會 KeyError——呼叫端在選擇日必先 refit）。"""
        return self._cache[ticker].fell_back

    def last_params(self, ticker: str) -> dict[str, float] | None:
        """GARCH ticker 回可讀 {omega,alpha,beta,nu}；EWMA/fallback 回 None（供診斷落盤）。"""
        entry = self._cache[ticker]
        if entry.kind != "garch" or entry.arch_params is None:
            return None
        p = entry.arch_params  # [mu, omega, alpha[1], beta[1], nu]
        return {
            "omega": float(p[1]),
            "alpha": float(p[2]),
            "beta": float(p[3]),
            "nu": float(p[4]),
        }
