"""INV-2：訊號-執行延遲 ≥ 1 個交易日（規格 §1.2、§3）。

本檔前半鎖時鐘算術，後半（Task 9 加入）鎖引擎行為。
"""

import pytest

from quantcore.backtest.clock import EventClock
from tests.fixtures.synthetic import make_dates


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
