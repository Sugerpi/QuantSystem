"""momentum_select 共用選擇：full/mom_only/mom_ivol 的唯一選標的實作。"""

from __future__ import annotations

import numpy as np

from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategies.momentum_selection import MomentumSelection, momentum_select
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def _snap(n=320):
    dates = make_dates(n)
    rng = np.random.default_rng(2)
    prices = {
        tk: list(100 * np.cumprod(1 + rng.normal(0.0003 * (i + 1), 0.01, n)))
        for i, tk in enumerate(["A", "B", "C", "D"])
    }
    return make_snapshot(prices, dates), dates


def _cfg():
    return make_cfg(
        ["A", "B", "C", "D"],
        signal={"top_k": 2, "momentum_lookback": 120, "momentum_skip": 5},
        universe={"min_history_days": 130},
    )


def test_momentum_select_returns_expected_shape():
    snap, dates = _snap()
    sel = momentum_select(make_view(snap, dates[300]), _cfg())
    assert isinstance(sel, MomentumSelection)
    assert set(sel.selected) <= set(sel.eligible)
    assert len(sel.selected) == 2
    assert set(sel.absmom) == set(sel.selected)
    assert set(sel.scores) <= {"A", "B", "C", "D"}


def test_momentum_select_none_when_no_eligible():
    dates = make_dates(50)
    snap = make_snapshot({"A": list(100 + np.arange(50.0))}, dates)
    cfg = make_cfg(
        ["A"], signal={"top_k": 1, "momentum_lookback": 40}, universe={"min_history_days": 200}
    )
    assert momentum_select(make_view(snap, dates[49]), cfg) is None
