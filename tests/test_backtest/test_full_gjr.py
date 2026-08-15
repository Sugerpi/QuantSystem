"""full_gjr：繼承 full，波動引擎換 GJR-GARCH（§6.3 擴充）。"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategies import STRATEGIES
from quantcore.backtest.strategies.full import Full
from quantcore.backtest.strategies.full_gjr import FullGjr
from quantcore.backtest.strategy import DecisionEvent
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def _snap(n=320):
    dates = make_dates(n)
    rng = np.random.default_rng(1)
    prices = {}
    for i, tk in enumerate(["A", "B", "C", "D"]):
        prices[tk] = list(100 * np.cumprod(1 + rng.normal(0.0003 * (i + 1), 0.01, n)))
    return make_snapshot(prices, dates), dates


def _cfg(vol_model="garch_arch"):
    return make_cfg(
        ["A", "B", "C", "D"],
        risk={"vol_model": vol_model, "garch_window": 200},
        signal={"top_k": 2, "momentum_lookback": 120, "momentum_skip": 5},
        universe={"min_history_days": 130},
    )


def test_full_gjr_registered():
    assert STRATEGIES["full_gjr"] is FullGjr


def test_full_gjr_forecaster_uses_gjr_regardless_of_config():
    # 內部強制 GJR：即使 config.vol_model=garch_arch，forecaster spec 仍為 gjr_garch。
    strat = FullGjr(_cfg(vol_model="garch_arch"))
    assert strat._forecaster._spec == "gjr_garch"


def test_full_gjr_runs_and_weights_sum_to_one():
    snap, dates = _snap()
    dec = FullGjr(_cfg()).decide(make_view(snap, dates[300]), DecisionEvent.SELECTION)
    assert dec is not None
    assert sum(dec.target_weights.values()) == pytest.approx(1.0)
    assert dec.diagnostics.sigma_p > 0
    assert len(dec.diagnostics.selected) == 2


def test_full_gjr_selection_layer_matches_full():
    # full_gjr 與 full 只差 vol 引擎——選股（selected）相同；σ̂ 因引擎不同可異。
    snap, dates = _snap()
    view = make_view(snap, dates[300])
    df = Full(_cfg()).decide(view, DecisionEvent.SELECTION)
    dg = FullGjr(_cfg()).decide(view, DecisionEvent.SELECTION)
    assert df.diagnostics.selected == dg.diagnostics.selected
