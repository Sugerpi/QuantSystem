"""sixty_forty —— 60% SPY / 40% IEF（規格 §6.3）。

存在理由：傳統配置基準。每個選擇日重平衡回 60/40。
"""

from __future__ import annotations

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy


class SixtyForty(Strategy):
    strategy_id = "sixty_forty"

    @property
    def warmup_days(self) -> int:
        return 0

    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        if event is not DecisionEvent.SELECTION:
            return None
        return Decision(
            target_weights={"SPY": 0.6, "IEF": 0.4, CASH: 0.0},
            diagnostics=Diagnostics(eligible=["IEF", "SPY"], selected=["IEF", "SPY"]),
        )
