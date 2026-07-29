"""trade blotter 對帳：Σ|Δw| == nav.turnover、Σ cost == nav.cost（逐再平衡）。"""

import numpy as np

from quantcore.backtest.accounting import CASH
from quantcore.backtest.clock import EventClock
from quantcore.backtest.engine import run_strategy
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.config import load_config
from tests.fixtures.synthetic import make_dates, make_snapshot


class _FixedTarget(Strategy):
    strategy_id = "fixed"

    def __init__(self, cfg, target):
        super().__init__(cfg)
        self._target = target
        self._done = False

    @property
    def warmup_days(self) -> int:
        return 0

    def decide(self, view, event):
        if self._done or event is not DecisionEvent.SELECTION:
            return None
        self._done = True
        return Decision(
            target_weights=dict(self._target),
            diagnostics=Diagnostics(eligible=sorted(self._target), selected=sorted(self._target)),
        )


def _run(target):
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["A", "B"]
    cfg.universe.min_history_days = 1
    cfg.signal.top_k = 2
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    cfg.costs.per_side_bps = 10.0  # 確保 cost > 0
    dates = make_dates(20)
    rng = np.random.default_rng(7)
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
    return run_strategy(snap, clock, _FixedTarget(cfg, target), cfg)


def test_blotter_reconciles_turnover_and_cost():
    nav, weights, decisions, trades = _run({"A": 0.6, "B": 0.4, CASH: 0.0})
    x_day = decisions["execution_date"].iloc[0]
    tr = trades[trades["execution_date"] == x_day]
    nav_row = nav[nav["date"] == x_day].iloc[0]

    assert abs(tr["delta_weight"].abs().sum() - nav_row["turnover"]) < 1e-12
    assert abs(tr["cost"].sum() - nav_row["cost"]) < 1e-9


def test_blotter_fields_are_consistent():
    _, _, _, trades = _run({"A": 1.0, "B": 0.0, CASH: 0.0})
    row = trades[trades["ticker"] == "A"].iloc[0]
    assert row["side"] == "buy"  # 全現金 → 建 A 倉
    assert row["delta_weight"] > 0
    assert abs(row["shares"] * row["fill_price"] - row["notional"]) < 1e-6
