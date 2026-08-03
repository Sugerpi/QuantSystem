"""engine 對 execute=False decision：落診斷但不執行、不換手（§1.7 log-only）。"""

from __future__ import annotations

import pandas as pd

from quantcore.backtest.clock import EventClock
from quantcore.backtest.engine import run_strategy
from quantcore.backtest.strategy import Decision, Diagnostics, Strategy
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


class _LogOnlyOnce(Strategy):
    """第一個決策日回 execute=False 的 log-only decision，其後不動作。"""

    strategy_id = "log_only_probe"

    def __init__(self, cfg):
        super().__init__(cfg)
        self._fired = False

    @property
    def warmup_days(self):
        return 2

    def decide(self, view, event):
        if self._fired:
            return None
        self._fired = True
        return Decision(
            target_weights={"SPY": 1.0, "CASH": 0.0},
            diagnostics=Diagnostics(eligible=["SPY"], selected=["SPY"], band_blocked=True),
            execute=False,
        )


def test_log_only_decision_records_row_but_no_turnover():
    dates = make_dates(12)
    snap = make_snapshot({"SPY": [100.0 + i for i in range(12)]}, dates)
    cfg = make_cfg(["SPY"], schedule={"selection_interval": 3, "exposure_check_interval": 3})
    clock = EventClock(dates, warmup=2, selection_interval=3, exposure_check_interval=3)
    nav, weights, decisions, _tr = run_strategy(snap, clock, _LogOnlyOnce(cfg), cfg)

    # 診斷有落盤（band_blocked=True 的那筆）
    assert len(decisions) == 1
    assert bool(decisions.iloc[0]["diagnostics"].band_blocked) is True
    assert pd.isna(decisions.iloc[0]["execution_date"])  # 未執行（None 或 NaT，視 frame 組成）
    # 全程無換手（execute=False 不 rebalance；權重恆為初始全現金）
    assert float(nav["turnover"].sum()) == 0.0


class _LogOnlyThenExecute(Strategy):
    """第一個決策日 execute=False（log-only），下一個決策日 execute=True。"""

    strategy_id = "log_then_exec_probe"

    def __init__(self, cfg):
        super().__init__(cfg)
        self._n = 0

    @property
    def warmup_days(self):
        return 2

    def decide(self, view, event):
        self._n += 1
        if self._n == 1:
            return Decision(
                target_weights={"SPY": 1.0, "CASH": 0.0},
                diagnostics=Diagnostics(eligible=["SPY"], selected=["SPY"], band_blocked=True),
                execute=False,
            )
        if self._n == 2:
            return Decision(
                target_weights={"SPY": 1.0, "CASH": 0.0},
                diagnostics=Diagnostics(eligible=["SPY"], selected=["SPY"]),
                execute=True,
            )
        return None


def test_log_only_does_not_block_subsequent_execute():
    dates = make_dates(12)
    snap = make_snapshot({"SPY": [100.0 + i for i in range(12)]}, dates)
    cfg = make_cfg(["SPY"], schedule={"selection_interval": 3, "exposure_check_interval": 3})
    clock = EventClock(dates, warmup=2, selection_interval=3, exposure_check_interval=3)
    # 不應拋 RuntimeError（log-only 未佔用 pending）
    nav, weights, decisions, _tr = run_strategy(snap, clock, _LogOnlyThenExecute(cfg), cfg)
    assert len(decisions) == 2
    # 第二筆（execute=True）確實執行 → 有換手；第一筆（log-only）未執行
    assert pd.isna(decisions.iloc[0]["execution_date"])
    assert decisions.iloc[1]["execution_date"] is not None
    assert float(nav["turnover"].sum()) > 0.0
