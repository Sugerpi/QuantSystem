"""波動目標曝險機制基底（規格 §1.6/§1.7）。full/voltarget_only/full_erc 共用。

有狀態（forecaster + e_current + 上次選擇快取），引擎每 run 新建（比照 bh_spy，不破 INV-6）。
子類兩種接法：
- inverse-vol 類（full/voltarget_only）：實作 `_select_and_weight`（選擇日算好 w_risky），走 base 的
  `decide()`（`_select_and_weight → _build_cov → _exposure_decision`）。
- cov-first 類（full_erc，ERC 權重需完整 Σ）：覆寫 `decide()`（`_build_cov` 後才算 w_risky），直接
  複用共用 helper `_build_cov`/`_exposure_decision`；`_select_and_weight` 不適用（raise）。
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, replace

import pandas as pd

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.config import QuantConfig
from quantcore.models.correlation.forecaster import CorrelationForecaster
from quantcore.models.covariance import build_covariance, portfolio_vol
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
    """該檔 ≤t 的日報酬（自 adj_close，date 為 index）。

    index 設為 date（而非 view.history 的位置索引）：VolForecaster 快取的標準化殘差
    沿用此 index，_collect_std_residuals 才能以日期比對決策當日的新鮮度（見該方法）。
    """
    h = view.history(ticker).set_index("date")
    return h["adj_close"].astype("float64").pct_change().dropna()


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


class VolTargetStrategy(Strategy):
    def __init__(self, cfg: QuantConfig) -> None:
        super().__init__(cfg)
        self._forecaster = VolForecaster(
            cfg.risk.vol_model,
            cfg.risk.ewma_lambda,
            cfg.risk.forecast_horizon,
            cfg.risk.garch_window,
        )
        self._corr = CorrelationForecaster(
            cfg.risk.corr_model,
            cfg.risk.ewma_lambda,
            cfg.risk.dcc_refit_interval,
            tuple(cfg.risk.dcc_fixed_ab),
            cfg.schedule.selection_interval,
            cfg.risk.dcc_qbar_shrink,
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

    def _collect_std_residuals(self, view: PointInTimeView, selected: list[str]) -> pd.DataFrame:
        """組 selected 各檔標準化殘差為 date×ticker 矩陣（按日交集）。

        殘差由 VolForecaster 在本次 refit/filter 已快取。逐檔斷言殘差新鮮
        （最後一列＝決策當日 view.t），防「漏對某檔 refit/filter →
        吃到前次 selection 的 stale 殘差」（INV-3 驗不到輸入新鮮度）。
        誠實失敗：hard raise（靜默排除某檔會使 σ̂_p 低估、曝險過高）。錯誤訊息點名各 offender
        的殘差末日，便於分辨「數週 stale（程式缺失）」與「差 1-2 天（資料缺口）」。
        """
        series = {t: self._forecaster.last_standardized_residuals(t) for t in selected}
        stale = {
            t: (s.index[-1] if not s.empty else None)
            for t, s in series.items()
            if s.empty or s.index[-1] != view.t
        }
        if stale:
            raise ValueError(
                f"標準化殘差非新鮮（決策日 {view.t}）：各 offender 末日 {stale}"
                "——可能有 selected 檔未於本次 refit/filter，或該檔今日缺 bar"
            )
        mat = pd.concat(series, axis=1)
        mat.columns = list(series.keys())
        mat = mat.dropna()
        if mat.empty:
            raise ValueError("標準化殘差矩陣為空（selected 各檔無共同日期）")
        return mat

    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        if event is DecisionEvent.SELECTION:
            state = self._select_and_weight(view)
            if state is None:
                return None
            e_current = None
        else:  # EXPOSURE_CHECK
            if self._cache is None:
                return None
            assert self._e_current is not None  # _cache 已設 ⟹ 選擇日已賦值 _e_current
            state = self._refilter(view, self._cache)
            e_current = self._e_current
        cov, R = self._build_cov(view, state.selected, state.sigma_hat, event)
        if event is DecisionEvent.SELECTION:
            self._cache = state  # M-1：相關步驟成功後才寫快取（例外時不留半套狀態）
        return self._exposure_decision(state, cov, R, e_current)

    def _build_cov(
        self,
        view: PointInTimeView,
        selected: list[str],
        sigma_hat: dict[str, float],
        event: DecisionEvent,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """殘差 → corr.refit(選擇日)/filter(曝險檢查日) → build_covariance。回 (Σ, R)。"""
        std_resid = self._collect_std_residuals(view, selected)
        R = (
            self._corr.refit(std_resid)
            if event is DecisionEvent.SELECTION
            else self._corr.filter(std_resid)
        )
        return build_covariance(sigma_hat, R), R

    def _exposure_decision(
        self, state: RiskyState, cov: pd.DataFrame, R: pd.DataFrame, e_current: float | None
    ) -> Decision:
        """σ̂_p → target_exposure → 最終權重 + 現金 + Diagnostics + log-only Decision。"""
        cfg = self._cfg
        sigma_p = portfolio_vol(state.w_risky, cov)
        exp = target_exposure(
            sigma_p,
            cfg.risk.vol_target_annual,
            cfg.risk.exposure_min,
            cfg.risk.exposure_band,
            e_current,
            cfg.risk.exposure_band_mode,
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
            corr_matrix=R,
            corr_fell_back=self._corr.last_fell_back(),
        )
        if not exp.band_blocked:
            self._e_current = exp.exposure_applied
        return Decision(
            target_weights={**weights, CASH: cash},
            diagnostics=diag,
            execute=not exp.band_blocked,
        )

    def standardized_residuals(self) -> dict[str, pd.Series]:
        """各檔最後一次 refit/filter 的標準化殘差（runner 於 run 結束落盤 residuals.parquet）。"""
        return self._forecaster.all_standardized_residuals()
