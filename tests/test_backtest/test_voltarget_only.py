"""voltarget_only：SPY + 波動目標（單資產 σ̂_p=σ̂_SPY）。"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategies.voltarget_only import VoltargetOnly
from quantcore.backtest.strategy import DecisionEvent
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def _snap(n=60):
    dates = make_dates(n)
    rng = np.random.default_rng(1)
    spy = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    return make_snapshot({"SPY": list(spy)}, dates), dates


def _cfg():
    return make_cfg(["SPY"], risk={"vol_model": "ewma", "corr_window": 30, "garch_window": 100})


def test_voltarget_only_holds_spy_with_exposure():
    snap, dates = _snap()
    strat = VoltargetOnly(_cfg())
    dec = strat.decide(make_view(snap, dates[50]), DecisionEvent.SELECTION)
    E = dec.diagnostics.exposure_applied
    assert dec.target_weights["SPY"] == pytest.approx(E)
    assert dec.target_weights[CASH] == pytest.approx(1.0 - E)
    # 單資產：σ̂_p == σ̂_SPY
    assert dec.diagnostics.sigma_p == pytest.approx(dec.diagnostics.sigma_hat["SPY"])


def test_voltarget_only_strategy_id():
    assert VoltargetOnly.strategy_id == "voltarget_only"


def test_voltarget_only_warmup_is_min_history():
    cfg = _cfg()
    assert VoltargetOnly(cfg).warmup_days == cfg.universe.min_history_days
