"""full —— 動量 + inverse-vol + 絕對動量 + 波動目標（主策略，規格 §1、§6.3）。

σ̂_p 用全 selected 的 w_risky（Σ=1）算 E；passing 檔 w_i=E×w_risky_i、
absmom failing 檔的 E×w_risky_i 轉現金（§1.6 Step 3）。σ̂ 由 GARCH（VolForecaster）。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategies.vol_target_base import (
    RiskyState,
    VolTargetStrategy,
    forecast_selected,
)
from quantcore.portfolio.selection import eligible_assets, select_top_k
from quantcore.portfolio.weighting import inverse_vol
from quantcore.signals.momentum import absolute_momentum, cross_sectional_momentum


class Full(VolTargetStrategy):
    strategy_id = "full"

    @property
    def warmup_days(self) -> int:
        return max(self._cfg.signal.momentum_lookback + 1, self._cfg.universe.min_history_days)

    def _select_and_weight(self, view: PointInTimeView) -> RiskyState | None:
        cfg = self._cfg
        # 選標的序列（eligible→動量→top_k→absmom）與 MomentumStrategy.decide 相同，須保持一致——
        # full/mom_ivol/mom_only 的消融須共用同一選擇邏輯才 apples-to-apples
        # （backlog：抽 momentum_select 共用，4c 前）。
        elig = eligible_assets(view.prices, cfg.universe.menu, cfg.universe.min_history_days)
        scores = cross_sectional_momentum(
            view.prices, cfg.signal.momentum_lookback, cfg.signal.momentum_skip
        )
        scores = {t: v for t, v in scores.items() if t in elig}
        if not scores:
            return None
        selected = select_top_k(scores, cfg.signal.top_k)

        sigma_hat, garch_params, fell_back = forecast_selected(self._forecaster, view, selected)
        w_risky = inverse_vol(sigma_hat)
        absmom_all = absolute_momentum(view.prices, view.rates, cfg.signal.momentum_lookback)
        absmom = {t: bool(absmom_all.get(t, False)) for t in selected}
        return RiskyState(
            eligible=elig,
            selected=selected,
            momentum_scores=scores,
            w_risky=w_risky,
            sigma_hat=sigma_hat,
            absmom=absmom,
            garch_params=garch_params,
            fell_back=fell_back,
        )
