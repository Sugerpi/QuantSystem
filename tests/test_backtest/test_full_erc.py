"""full_erc：與 full 同層（動量+absmom+波動目標），權重改用 ERC（§1.6/§5.3）。"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategies.full import Full
from quantcore.backtest.strategies.full_erc import FullErc
from quantcore.backtest.strategy import DecisionEvent
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def _snap(n=320):
    dates = make_dates(n)
    rng = np.random.default_rng(1)
    prices = {}
    for i, tk in enumerate(["A", "B", "C", "D"]):
        drift = 0.0003 * (i + 1)
        prices[tk] = list(100 * np.cumprod(1 + rng.normal(drift, 0.01, n)))
    return make_snapshot(prices, dates), dates


def _cfg():
    return make_cfg(
        ["A", "B", "C", "D"],
        risk={"vol_model": "ewma", "garch_window": 100},
        signal={"top_k": 2, "momentum_lookback": 120, "momentum_skip": 5},
        universe={"min_history_days": 130},
    )


def test_full_erc_selection_decides():
    snap, dates = _snap()
    cfg = _cfg()
    view = make_view(snap, dates[300])
    dec = FullErc(cfg).decide(view, DecisionEvent.SELECTION)
    assert dec is not None
    assert abs(sum(dec.target_weights.values()) - 1.0) < 1e-9  # INV-5
    assert dec.diagnostics.sigma_p is not None and dec.diagnostics.sigma_p > 0


def test_full_and_full_erc_share_selection_but_differ_in_weights():
    snap, dates = _snap()
    cfg = _cfg()
    view = make_view(snap, dates[300])
    df = Full(cfg).decide(view, DecisionEvent.SELECTION)
    de = FullErc(cfg).decide(view, DecisionEvent.SELECTION)
    assert df is not None and de is not None
    assert df.diagnostics.selected == de.diagnostics.selected
    assert df.diagnostics.sigma_hat == pytest.approx(de.diagnostics.sigma_hat)
    assert df.diagnostics.w_risky != de.diagnostics.w_risky  # 權重方案不同


def test_full_erc_registered():
    from quantcore.backtest.strategies import STRATEGIES

    assert STRATEGIES["full_erc"] is FullErc
