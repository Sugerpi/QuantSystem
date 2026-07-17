"""ew_menu —— 選單等權重、月再平衡（規格 §6.3）。

存在理由：分散但無訊號。
"""

from __future__ import annotations

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.portfolio.selection import eligible_assets


class EqualWeightMenu(Strategy):
    strategy_id = "ew_menu"

    @property
    def warmup_days(self) -> int:
        return self._cfg.universe.min_history_days

    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        if event is not DecisionEvent.SELECTION:
            return None
        elig = eligible_assets(view, self._cfg.universe.menu, self._cfg.universe.min_history_days)
        if not elig:
            return None
        w = 1.0 / len(elig)
        target = {t: w for t in elig}
        target[CASH] = 0.0
        return Decision(
            target_weights=target,
            diagnostics=Diagnostics(eligible=elig, selected=elig),
        )
