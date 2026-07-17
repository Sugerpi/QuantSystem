"""INV-1：無 Look-Ahead——決策日 t 只依賴 timestamp ≤ t 的資料（規格 §1.2、§3）。

兩層防護：
(a) property：view 內任何 timestamp ≤ t。
(b) 竄改未來資料，view 內容必須逐位元不變 —— 這條測結構而非自律：
    若有人讓 view 洩漏未來，(a) 可能仍過，(b) 必當場紅燈。
"""

import numpy as np
import pandas as pd
import pytest

from quantcore.backtest.ptview import make_view
from tests.fixtures.synthetic import make_dates, make_snapshot


def _snap(n=30):
    dates = make_dates(n)
    return make_snapshot(
        {
            "SPY": list(100.0 + np.arange(n) * 1.0),
            "QQQ": list(200.0 + np.arange(n) * 2.0),
        },
        dates,
    ), dates


def test_view_contains_no_future_timestamps():
    snap, dates = _snap()
    for t in dates:
        v = make_view(snap, t)
        assert (v.prices["date"] <= t).all()
        assert (v.rates["date"] <= t).all()


def test_view_includes_day_t_itself():
    """§1.2：day t 的 bar 在 close(t) 之後存在，決策於 close(t) 之後 → 含 t。"""
    snap, dates = _snap()
    t = dates[10]
    v = make_view(snap, t)
    assert v.prices["date"].max() == t


def test_corrupting_the_future_does_not_change_the_view():
    snap, dates = _snap()
    t = dates[10]
    baseline = make_view(snap, t)

    corrupted = {k: (val.copy() if hasattr(val, "copy") else val) for k, val in snap.items()}
    p = corrupted["prices"]
    future = p["date"] > t
    rng = np.random.default_rng(0)
    p.loc[future, "adj_close"] = rng.normal(1e6, 1e5, size=int(future.sum()))
    p.loc[future, "close"] = p.loc[future, "adj_close"]
    r = corrupted["rates"]
    r.loc[r["date"] > t, "DTB3"] = -999.0

    after = make_view(corrupted, t)
    pd.testing.assert_frame_equal(baseline.prices, after.prices)
    pd.testing.assert_frame_equal(baseline.rates, after.rates)


def test_view_is_frozen():
    snap, dates = _snap()
    v = make_view(snap, dates[5])
    with pytest.raises(AttributeError):  # dataclasses.FrozenInstanceError 的父類
        v.t = dates[6]


def test_bar_count_counts_only_up_to_t():
    snap, dates = _snap()
    v = make_view(snap, dates[9])
    assert v.bar_count("SPY") == 10
    assert v.bar_count("NOPE") == 0
