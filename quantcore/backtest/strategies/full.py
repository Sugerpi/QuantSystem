"""full —— 動量 + inverse-vol + 絕對動量 + 波動目標（主策略，規格 §1、§6.3）。

σ̂_p 用全 selected 的 w_risky（Σ=1）算 E；passing 檔 w_i=E×w_risky_i、
absmom failing 檔的 E×w_risky_i 轉現金（§1.6 Step 3）。σ̂ 由 GARCH（VolForecaster）。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategies.momentum_selection import momentum_select
from quantcore.backtest.strategies.vol_target_base import (
    RiskyState,
    VolTargetStrategy,
    forecast_selected,
)
from quantcore.portfolio.weighting import inverse_vol


class Full(VolTargetStrategy):
    strategy_id = "full"

    @property
    def warmup_days(self) -> int:
        return max(self._cfg.signal.momentum_lookback + 1, self._cfg.universe.min_history_days)

    def _select_and_weight(self, view: PointInTimeView) -> RiskyState | None:
        sel = momentum_select(view, self._cfg)
        if sel is None:
            return None
        sigma_hat, garch_params, fell_back = forecast_selected(self._forecaster, view, sel.selected)
        w_risky = inverse_vol(sigma_hat)
        return RiskyState(
            eligible=sel.eligible,
            selected=sel.selected,
            momentum_scores=sel.scores,
            w_risky=w_risky,
            sigma_hat=sigma_hat,
            absmom=sel.absmom,
            garch_params=garch_params,
            fell_back=fell_back,
        )
