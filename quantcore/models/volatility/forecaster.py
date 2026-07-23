"""refit/filter 波動預報器（規格 §5.2）。

昂貴的 GARCH 估計（選擇日 refit）與便宜的固定參數濾波（曝險檢查日 filter）分離。
內部一律切尾端 garch_window 根，成本 O(cap) 不隨回測時間膨脹。
有狀態：策略每 run 持有一實例（比照 bh_spy，引擎每 run 新建，不破 INV-6）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantcore.models.volatility import annualized_forecast_vol, fit_volatility
from quantcore.models.volatility.base import annualize_variance_path
from quantcore.models.volatility.garch_arch import GarchArch, garch_filter_forecast


class VolForecaster:
    def __init__(self, spec: str, ewma_lambda: float, horizon: int, garch_window: int) -> None:
        self._spec = spec
        self._ewma_lambda = ewma_lambda
        self._horizon = horizon
        self._window = garch_window
        # ticker -> (kind: 'garch'|'ewma', arch_params 或 None, fell_back)
        self._cache: dict[str, tuple[str, np.ndarray | None, bool]] = {}

    def _tail(self, returns: pd.Series) -> pd.Series:
        return returns.iloc[-self._window :]

    def refit(self, ticker: str, returns: pd.Series) -> float:
        """選擇日：完整估計（含 fallback），快取，回年化 σ̂。"""
        outcome = fit_volatility(self._spec, self._tail(returns), ewma_lambda=self._ewma_lambda)
        if isinstance(outcome.model, GarchArch):
            self._cache[ticker] = ("garch", outcome.model.arch_params, outcome.fell_back)
        else:
            self._cache[ticker] = ("ewma", None, outcome.fell_back)
        return annualized_forecast_vol(outcome.model, self._horizon)

    def filter(self, ticker: str, returns: pd.Series) -> float:
        """曝險檢查日：以快取參數濾波（GARCH 走 fix()，EWMA 重跑）。無快取則 refit。"""
        if ticker not in self._cache:
            return self.refit(ticker, returns)
        kind, params, _ = self._cache[ticker]
        window = self._tail(returns)
        if kind == "garch":
            return annualize_variance_path(garch_filter_forecast(params, window, self._horizon))
        outcome = fit_volatility("ewma", window, ewma_lambda=self._ewma_lambda)
        return annualized_forecast_vol(outcome.model, self._horizon)

    def last_fell_back(self, ticker: str) -> bool:
        """該 ticker 上次 refit 是否退回 EWMA（供 4b-2 落盤 model_details）。"""
        return self._cache[ticker][2]
