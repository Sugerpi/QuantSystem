"""INV-2：訊號-執行延遲 ≥ 1 個交易日（規格 §1.2、§3）。

本檔前半鎖時鐘算術，後半（Task 9 加入）鎖引擎行為。
"""

import numpy as np
import pytest

from quantcore.backtest.accounting import CASH
from quantcore.backtest.clock import EventClock
from quantcore.backtest.engine import run_strategy
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.config import load_config
from tests.fixtures.synthetic import make_dates, make_snapshot


def _clock(n=40, warmup=5, sel=7, exp=3) -> EventClock:
    return EventClock(
        trading_days=make_dates(n),
        warmup=warmup,
        selection_interval=sel,
        exposure_check_interval=exp,
    )


def test_active_days_start_after_warmup():
    c = _clock()
    assert c.active_days[0] == c.trading_days[5]
    assert len(c.active_days) == 35


def test_first_active_day_is_both_selection_and_exposure_day():
    """錨點：warmup 結束後第一個交易日為第 0 天（設計文件 §2.3.1）。"""
    c = _clock()
    t0 = c.active_days[0]
    assert c.is_selection_day(t0)
    assert c.is_exposure_check_day(t0)


def test_selection_days_are_every_interval_from_anchor():
    c = _clock(sel=7)
    sel = [t for t in c.active_days if c.is_selection_day(t)]
    assert sel == list(c.active_days[::7])


def test_execution_day_is_strictly_next_trading_day():
    c = _clock()
    for t in c.active_days[:-1]:
        ex = c.execution_day(t)
        assert ex > t
        i = c.trading_days.get_loc(t)
        assert ex == c.trading_days[i + 1]


def test_execution_day_none_past_end_of_data():
    c = _clock()
    assert c.execution_day(c.trading_days[-1]) is None


def test_rejects_interval_below_two():
    """間隔 1 會讓前次決策尚未執行就被覆蓋，語意不明確，直接拒絕。"""
    with pytest.raises(ValueError, match="間隔"):
        EventClock(
            trading_days=make_dates(10),
            warmup=0,
            selection_interval=1,
            exposure_check_interval=3,
        )


def test_rejects_warmup_beyond_data():
    with pytest.raises(ValueError, match="warmup"):
        EventClock(
            trading_days=make_dates(10),
            warmup=10,
            selection_interval=7,
            exposure_check_interval=3,
        )


# ---------------------------------------------------------------- 引擎行為（Task 9）


class _FixedTarget(Strategy):
    """在第一個選擇日給定 target，其後不動作。target 由測試注入。"""

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


def _engine_cfg():
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["A", "B"]
    cfg.universe.min_history_days = 1
    cfg.signal.top_k = 2
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    return cfg


def _engine_snapshot(n=20):
    dates = make_dates(n)
    rng = np.random.default_rng(7)
    a = list(100.0 * np.cumprod(1 + rng.normal(0.001, 0.01, n)))
    b = list(50.0 * np.cumprod(1 + rng.normal(0.001, 0.01, n)))
    return make_snapshot({"A": a, "B": b}, dates), dates


def _run(target, warmup=2):
    cfg = _engine_cfg()
    snap, dates = _engine_snapshot()
    clock = EventClock(
        trading_days=dates,
        warmup=warmup,
        selection_interval=cfg.schedule.selection_interval,
        exposure_check_interval=cfg.schedule.exposure_check_interval,
    )
    nav, weights, decisions, _tr = run_strategy(snap, clock, _FixedTarget(cfg, target), cfg)
    return nav, weights, decisions, clock


def test_target_change_does_not_affect_decision_or_execution_day_nav():
    """INV-2 的行為證明（§1.2「新權重自 close(t+1) 生效，賺 (t+1 → t+2]」）。

    把 target 換成完全不同的值，決策日與執行日當天的 NAV 必須逐位元相同——
    決策日當天新權重尚未存在，執行日當天的報酬仍由舊（漂移後）權重賺得，
    成本雖於執行日扣除，但兩個 target 的換手率在此設定下相同（皆由全現金建倉，
    換手 = 1.0），故 NAV 亦同。差異只能出現在執行日之後。
    """
    nav1, _, dec1, clock = _run({"A": 1.0, "B": 0.0, CASH: 0.0})
    nav2, _, _, _ = _run({"A": 0.0, "B": 1.0, CASH: 0.0})

    d_day = dec1["decision_date"].iloc[0]
    x_day = dec1["execution_date"].iloc[0]

    n1 = nav1.set_index("date")["nav"]
    n2 = nav2.set_index("date")["nav"]
    assert n1.loc[d_day] == n2.loc[d_day]
    assert n1.loc[x_day] == n2.loc[x_day]
    after = n1.index[n1.index > x_day]
    assert not np.allclose(n1.loc[after].to_numpy(), n2.loc[after].to_numpy())


def test_weights_change_only_on_execution_day():
    nav, weights, dec, clock = _run({"A": 1.0, "B": 0.0, CASH: 0.0})
    x_day = dec["execution_date"].iloc[0]
    w = weights.pivot(index="date", columns="ticker", values="weight").fillna(0.0)

    before = w.index[w.index < x_day]
    assert (w.loc[before, CASH] == 1.0).all()
    assert w.loc[x_day, "A"] == 1.0


def test_decision_recorded_with_next_trading_day_as_execution():
    _, _, dec, clock = _run({"A": 1.0, "B": 0.0, CASH: 0.0})
    d_day = dec["decision_date"].iloc[0]
    assert dec["execution_date"].iloc[0] == clock.execution_day(d_day)
