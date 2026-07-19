"""橫斷面與絕對動量（規格 §1.3、§1.4）。"""

import numpy as np

from quantcore.signals.momentum import cross_sectional_momentum
from tests.fixtures.synthetic import make_dates, make_snapshot


def test_momentum_uses_skip_and_lookback_offsets():
    # lookback=4, skip=1：M = s[t-1]/s[t-4] - 1
    dates = make_dates(6)
    snap = make_snapshot({"A": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]}, dates)
    out = cross_sectional_momentum(snap["prices"], lookback=4, skip=1)
    # s[-2]=14, s[-5]=11 → 14/11 - 1
    assert out["A"] == np.float64(14.0 / 11.0 - 1.0)


def test_asset_with_too_few_bars_is_omitted():
    dates = make_dates(6)
    snap = make_snapshot(
        {"A": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0], "SHORT": [1.0, 2.0, 3.0]}, dates
    )
    out = cross_sectional_momentum(snap["prices"], lookback=4, skip=1)
    assert "A" in out
    assert "SHORT" not in out  # 只有 3 根 bar < lookback+1=5


def test_multiple_tickers_scored_independently():
    dates = make_dates(6)
    snap = make_snapshot({"UP": [10, 10, 10, 10, 10, 20], "DOWN": [20, 20, 20, 20, 20, 10]}, dates)
    out = cross_sectional_momentum(snap["prices"], lookback=4, skip=1)
    # skip=1 → 用 s[-2]（尚未反映最後一天跳動），兩檔 s[-2]/s[-5] 皆為 1.0 → 0.0
    assert out["UP"] == 0.0
    assert out["DOWN"] == 0.0
