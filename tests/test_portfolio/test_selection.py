"""point-in-time 合格性（規格 §1.1、§2.1）。"""

import numpy as np

from quantcore.backtest.ptview import make_view
from quantcore.portfolio.selection import eligible_assets
from tests.fixtures.synthetic import make_dates, make_snapshot

MENU = ["SPY", "QQQ", "LATE"]


def _snap(n=30):
    dates = make_dates(n)
    snap = make_snapshot(
        {
            "SPY": list(100.0 + np.arange(n)),
            "QQQ": list(200.0 + np.arange(n)),
            "LATE": list(50.0 + np.arange(10)),  # 只有最後 10 天有資料
        },
        dates,
    )
    return snap, dates


def test_asset_with_insufficient_history_is_not_eligible():
    snap, dates = _snap()
    v = make_view(snap, dates[-1])
    assert eligible_assets(v, MENU, min_history_days=20) == ["QQQ", "SPY"]


def test_late_asset_becomes_eligible_once_history_suffices():
    snap, dates = _snap()
    v = make_view(snap, dates[-1])
    assert eligible_assets(v, MENU, min_history_days=10) == ["LATE", "QQQ", "SPY"]


def test_result_is_sorted_for_determinism():
    snap, dates = _snap()
    v = make_view(snap, dates[-1])
    out = eligible_assets(v, ["QQQ", "SPY"], min_history_days=5)
    assert out == sorted(out)


def test_ticker_absent_from_snapshot_is_not_eligible():
    snap, dates = _snap()
    v = make_view(snap, dates[-1])
    assert eligible_assets(v, ["SPY", "NOPE"], min_history_days=5) == ["SPY"]
