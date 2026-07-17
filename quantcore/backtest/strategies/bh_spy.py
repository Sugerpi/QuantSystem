"""bh_spy —— Buy & Hold SPY（規格 §6.3）。

存在理由：最誠實的基準，不折騰能拿到什麼。

有狀態（`_decided`）是刻意的：buy & hold 的語意就是「決策一次」。引擎每次 run
建立新實例，故不影響 INV-6 可重現性。
"""

from __future__ import annotations

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.config import QuantConfig


class BuyHoldSPY(Strategy):
    strategy_id = "bh_spy"

    def __init__(self, cfg: QuantConfig) -> None:
        super().__init__(cfg)
        self._decided = False

    @property
    def warmup_days(self) -> int:
        return 0

    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        if self._decided or event is not DecisionEvent.SELECTION:
            return None
        self._decided = True
        return Decision(
            target_weights={"SPY": 1.0, CASH: 0.0},
            diagnostics=Diagnostics(eligible=["SPY"], selected=["SPY"]),
        )
