"""voltarget_only —— 持有 SPY + GARCH 波動目標（規格 §6.3）。

存在理由：消融——只有倉位（曝險）層，無動量選擇、無 absmom。
單資產 → R=[[1]]、σ̂_p=σ̂_SPY，走 VolTargetStrategy 同一路徑不特判。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategies.vol_target_base import (
    RiskyState,
    VolTargetStrategy,
    forecast_selected,
)


class VoltargetOnly(VolTargetStrategy):
    strategy_id = "voltarget_only"

    @property
    def warmup_days(self) -> int:
        return self._cfg.universe.min_history_days

    def _select_and_weight(self, view: PointInTimeView) -> RiskyState | None:
        selected = ["SPY"]
        sigma_hat, garch_params, fell_back = forecast_selected(self._forecaster, view, selected)
        return RiskyState(
            eligible=selected,
            selected=selected,
            momentum_scores=None,
            w_risky={"SPY": 1.0},
            sigma_hat=sigma_hat,
            absmom={"SPY": True},
            garch_params=garch_params,
            fell_back=fell_back,
        )
