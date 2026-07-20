"""point-in-time 合格性（規格 §1.1、§2.1）。"""

import numpy as np

from quantcore.backtest.ptview import make_view
from quantcore.portfolio.selection import eligible_assets, select_top_k
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
    assert eligible_assets(v.prices, MENU, min_history_days=20) == ["QQQ", "SPY"]


def test_late_asset_becomes_eligible_once_history_suffices():
    snap, dates = _snap()
    v = make_view(snap, dates[-1])
    assert eligible_assets(v.prices, MENU, min_history_days=10) == ["LATE", "QQQ", "SPY"]


def test_result_is_sorted_for_determinism():
    snap, dates = _snap()
    v = make_view(snap, dates[-1])
    out = eligible_assets(v.prices, ["QQQ", "SPY"], min_history_days=5)
    assert out == sorted(out)


def test_ticker_absent_from_snapshot_is_not_eligible():
    snap, dates = _snap()
    v = make_view(snap, dates[-1])
    assert eligible_assets(v.prices, ["SPY", "NOPE"], min_history_days=5) == ["SPY"]


def test_select_top_k_by_score_desc():
    scores = {"A": 0.1, "B": 0.5, "C": 0.3}
    assert select_top_k(scores, k=2) == ["B", "C"]


def test_select_top_k_tie_broken_by_ticker_alpha():
    # 刻意把同分的 C 排在 A 前面插入：唯有「以 ticker 升序」平手規則才會得到 [A, C]。
    # 若拿掉 tie-break（sort 為 stable），會保留插入序回傳 [C, A] → 測試失敗，
    # 故此測試真的守得住 INV-6。
    scores = {"C": 0.3, "A": 0.3, "D": 0.2, "B": 0.1}
    assert select_top_k(scores, k=2) == ["A", "C"]


def test_select_top_k_caps_at_available():
    scores = {"A": 0.3, "B": 0.1}
    assert select_top_k(scores, k=5) == ["A", "B"]
