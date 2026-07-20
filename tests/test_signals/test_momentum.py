"""橫斷面與絕對動量（規格 §1.3、§1.4）。"""

import numpy as np

from quantcore.signals.momentum import absolute_momentum, cross_sectional_momentum
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
    snap = make_snapshot(
        {"UP": [10.0, 10.0, 10.0, 10.0, 20.0, 25.0], "DOWN": [20.0, 20.0, 20.0, 20.0, 10.0, 5.0]},
        dates,
    )
    out = cross_sectional_momentum(snap["prices"], lookback=4, skip=1)
    # skip=1 → 用 s[-2]（第 5 天），不受最後一天影響
    assert out["UP"] == 20.0 / 10.0 - 1.0  # +1.0
    assert out["DOWN"] == 10.0 / 20.0 - 1.0  # -0.5


def test_absmom_pass_when_return_beats_tbill():
    # dtb3=2.52% → 日利率 0.0001；lookback=4 → tbill_cum≈(1.0001)^4-1≈0.0004
    dates = make_dates(5)
    snap = make_snapshot(
        {"UP": [10.0, 10.0, 10.0, 10.0, 11.0], "DOWN": [10.0, 10.0, 10.0, 10.0, 9.0]},
        dates,
        dtb3_percent=2.52,
    )
    out = absolute_momentum(snap["prices"], snap["rates"], lookback=4)
    assert out["UP"] is True  # TR=+0.10 > tbill
    assert out["DOWN"] is False  # TR=-0.10 < tbill


def test_absmom_omits_short_history():
    dates = make_dates(5)
    snap = make_snapshot({"SHORT": [1.0, 2.0, 3.0]}, dates)
    out = absolute_momentum(snap["prices"], snap["rates"], lookback=4)
    assert "SHORT" not in out


def test_absmom_uses_tbill_hurdle_not_just_positive_return():
    # lookback=4, dtb3=2.52% → tbill_cum ≈ (1.0001)^4 - 1 ≈ 0.00040006
    # ABOVE: TR=+0.0006 > hurdle → True；BELOW: TR=+0.0002（正報酬但輸給 T-bill）→ False
    dates = make_dates(5)
    snap = make_snapshot(
        {
            "ABOVE": [10000.0, 10000.0, 10000.0, 10000.0, 10006.0],
            "BELOW": [10000.0, 10000.0, 10000.0, 10000.0, 10002.0],
        },
        dates,
        dtb3_percent=2.52,
    )
    out = absolute_momentum(snap["prices"], snap["rates"], lookback=4)
    assert out["ABOVE"] is True
    assert out["BELOW"] is False  # 正報酬但低於 T-bill hurdle → 轉現金
