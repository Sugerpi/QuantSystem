"""full：動量 + inverse-vol + absmom + 波動目標（主策略，§6.3）。"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategies.full import Full
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
        risk={"vol_model": "ewma", "corr_window": 60, "garch_window": 100},
        signal={"top_k": 2, "momentum_lookback": 120, "momentum_skip": 5},
        universe={"min_history_days": 130},
    )


def test_full_selection_weights_sum_to_one_and_scaled_by_exposure():
    snap, dates = _snap()
    strat = Full(_cfg())
    dec = strat.decide(make_view(snap, dates[300]), DecisionEvent.SELECTION)
    assert dec is not None
    assert sum(dec.target_weights.values()) == pytest.approx(1.0)
    E = dec.diagnostics.exposure_applied
    risky_sum = sum(v for k, v in dec.target_weights.items() if k != CASH)
    assert risky_sum == pytest.approx(E, abs=1e-9)  # 全過：risky_sum == E×Σw_risky == E
    assert len(dec.diagnostics.selected) == 2
    assert dec.diagnostics.sigma_p > 0


def test_full_records_garch_diagnostics():
    snap, dates = _snap()
    dec = Full(_cfg()).decide(make_view(snap, dates[300]), DecisionEvent.SELECTION)
    assert set(dec.diagnostics.vol_fell_back) == set(dec.diagnostics.selected)
    assert set(dec.diagnostics.garch_params) == set(dec.diagnostics.selected)


def test_full_warmup_is_max_of_momentum_and_history():
    cfg = _cfg()
    assert Full(cfg).warmup_days == max(
        cfg.signal.momentum_lookback + 1, cfg.universe.min_history_days
    )
