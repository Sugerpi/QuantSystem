"""波動目標曝險機制基底（規格 §1.6/§1.7）。full/voltarget_only 共用。

有狀態（forecaster + e_current + 上次選擇快取），引擎每 run 新建（比照 bh_spy，不破 INV-6）。
子類實作 _select_and_weight（選擇日：選標的、相對權重、refit σ̂）。
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, replace

import pandas as pd

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.config import QuantConfig
from quantcore.models.covariance import build_covariance, portfolio_vol, rolling_correlation
from quantcore.models.volatility.forecaster import VolForecaster
from quantcore.portfolio.exposure import target_exposure


@dataclass(frozen=True)
class RiskyState:
    eligible: list[str]
    selected: list[str]
    momentum_scores: dict[str, float] | None
    w_risky: dict[str, float]  # Σ=1 over selected
    sigma_hat: dict[str, float]
    absmom: dict[str, bool]
    garch_params: dict[str, dict[str, float] | None]
    fell_back: dict[str, bool]


def ticker_returns(view: PointInTimeView, ticker: str) -> pd.Series:
    """該檔 ≤t 的日報酬（自 adj_close）。"""
    return view.history(ticker)["adj_close"].astype("float64").pct_change().dropna()


def forecast_selected(
    forecaster: VolForecaster, view: PointInTimeView, selected: list[str]
) -> tuple[dict[str, float], dict[str, dict[str, float] | None], dict[str, bool]]:
    """對每檔 refit σ̂，並收集 GARCH 參數與 fallback 旗標（診斷用）。
    回 (sigma_hat, garch_params, fell_back)。
    """
    sigma_hat: dict[str, float] = {}
    garch_params: dict[str, dict[str, float] | None] = {}
    fell_back: dict[str, bool] = {}
    for t in selected:
        sigma_hat[t] = forecaster.refit(t, ticker_returns(view, t))
        garch_params[t] = forecaster.last_params(t)
        fell_back[t] = forecaster.last_fell_back(t)
    return sigma_hat, garch_params, fell_back


def _selected_returns_window(
    view: PointInTimeView, selected: list[str], window: int
) -> pd.DataFrame:
    """date×ticker 報酬窗（選定資產尾端 window 根），供 rolling_correlation。"""
    wide = view.prices.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    return wide[selected].pct_change().tail(window)


class VolTargetStrategy(Strategy):
    def __init__(self, cfg: QuantConfig) -> None:
        super().__init__(cfg)
        self._forecaster = VolForecaster(
            cfg.risk.vol_model,
            cfg.risk.ewma_lambda,
            cfg.risk.forecast_horizon,
            cfg.risk.garch_window,
        )
        self._e_current: float | None = None
        self._cache: RiskyState | None = None

    @abstractmethod
    def _select_and_weight(self, view: PointInTimeView) -> RiskyState | None:
        """選擇日：回 RiskyState（內部 refit σ̂）；無合格資產回 None。"""

    def _refilter(self, view: PointInTimeView, cached: RiskyState) -> RiskyState:
        """曝險檢查日：以 filter 更新 σ̂，其餘沿用快取。"""
        sigma_hat = {
            t: self._forecaster.filter(t, ticker_returns(view, t)) for t in cached.selected
        }
        return replace(cached, sigma_hat=sigma_hat)

    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        cfg = self._cfg
        if event is DecisionEvent.SELECTION:
            state = self._select_and_weight(view)
            if state is None:
                return None
            self._cache = state
            e_current = None
        else:  # EXPOSURE_CHECK
            if self._cache is None:
                return None
            assert self._e_current is not None  # _cache 已設 ⟹ 選擇日已賦值 _e_current
            state = self._refilter(view, self._cache)
            e_current = self._e_current

        window = _selected_returns_window(view, state.selected, cfg.risk.corr_window)
        R = rolling_correlation(window)
        cov = build_covariance(state.sigma_hat, R)
        sigma_p = portfolio_vol(state.w_risky, cov)
        exp = target_exposure(
            sigma_p,
            cfg.risk.vol_target_annual,
            cfg.risk.exposure_min,
            cfg.risk.exposure_band,
            e_current,
        )

        weights = {
            t: exp.exposure_applied * state.w_risky[t]
            for t in state.selected
            if state.absmom.get(t, False)
        }
        cash = 1.0 - sum(weights.values())

        diag = Diagnostics(
            eligible=state.eligible,
            selected=state.selected,
            momentum_scores=state.momentum_scores,
            absmom=state.absmom,
            sigma_hat=state.sigma_hat,
            w_risky=state.w_risky,
            sigma_p=sigma_p,
            exposure_raw=exp.exposure_raw,
            exposure_applied=exp.exposure_applied,
            band_blocked=exp.band_blocked,
            vol_fell_back=state.fell_back,
            garch_params=state.garch_params,
        )
        if not exp.band_blocked:
            self._e_current = exp.exposure_applied
        return Decision(
            target_weights={**weights, CASH: cash},
            diagnostics=diag,
            execute=not exp.band_blocked,
        )
