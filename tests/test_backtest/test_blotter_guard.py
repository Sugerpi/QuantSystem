"""blotter 對非有限/非正 fill_price 誠實拋錯（不靜默寫 NaN shares）。"""

import numpy as np
import pytest

from quantcore.backtest.accounting import CASH
from quantcore.backtest.clock import EventClock
from quantcore.backtest.engine import run_strategy
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.config import load_config
from tests.fixtures.synthetic import make_dates, make_snapshot


class _BuyA(Strategy):
    strategy_id = "buya"

    def __init__(self, cfg):
        super().__init__(cfg)
        self._done = False

    @property
    def warmup_days(self) -> int:
        return 0

    def decide(self, view, event):
        if self._done or event is not DecisionEvent.SELECTION:
            return None
        self._done = True
        return Decision(
            target_weights={"A": 1.0, "B": 0.0, CASH: 0.0},
            diagnostics=Diagnostics(eligible=["A", "B"], selected=["A", "B"]),
        )


def test_blotter_raises_on_nonfinite_fill_price():
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["A", "B"]
    cfg.universe.min_history_days = 1
    cfg.signal.top_k = 2
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    cfg.costs.per_side_bps = 5.0
    dates = make_dates(20)
    rng = np.random.default_rng(1)
    snap = make_snapshot(
        {
            "A": list(100.0 * np.cumprod(1 + rng.normal(0.001, 0.01, 20))),
            "B": list(50.0 * np.cumprod(1 + rng.normal(0.001, 0.01, 20))),
        },
        dates,
    )
    clock = EventClock(
        trading_days=dates,
        warmup=2,
        selection_interval=cfg.schedule.selection_interval,
        exposure_check_interval=cfg.schedule.exposure_check_interval,
    )
    # 找出第一次選擇日的執行日（下一交易日），把 A 在該日的 adj_close 設為 NaN
    strat = _BuyA(cfg)
    # 決策日 = active_days[0]（錨點），執行日 = 下一交易日
    decision_day = clock.active_days[0]
    exec_day = clock.execution_day(decision_day)
    prices = snap["prices"]
    mask = (prices["ticker"] == "A") & (prices["date"] == exec_day)
    assert mask.any(), "測試前提：A 在執行日有一列價格可污染"
    prices.loc[mask, "adj_close"] = np.nan

    with pytest.raises(ValueError, match="fill_price"):
        run_strategy(snap, clock, strat, cfg)
