"""VolTargetStrategy 基底：選擇/曝險檢查流程、權重守恆、band log-only。"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategies.vol_target_base import (
    RiskyState,
    VolTargetStrategy,
    ticker_returns,
)
from quantcore.backtest.strategy import DecisionEvent
from quantcore.portfolio.weighting import inverse_vol
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


class _FixedRisky(VolTargetStrategy):
    """測試用：固定選 A、B，σ̂ 由 forecaster（ewma）決定；absmom 可注入。"""

    strategy_id = "fixed_risky_probe"

    def __init__(self, cfg, absmom):
        super().__init__(cfg)
        self._absmom = absmom

    @property
    def warmup_days(self):
        return 2

    def _select_and_weight(self, view):
        selected = ["A", "B"]
        sigma_hat = {t: self._forecaster.refit(t, ticker_returns(view, t)) for t in selected}
        return RiskyState(
            eligible=selected,
            selected=selected,
            momentum_scores=None,
            w_risky=inverse_vol(sigma_hat),
            sigma_hat=sigma_hat,
            absmom={t: self._absmom.get(t, True) for t in selected},
            garch_params={t: self._forecaster.last_params(t) for t in selected},
            fell_back={t: self._forecaster.last_fell_back(t) for t in selected},
        )


def _snap(n=60):
    dates = make_dates(n)
    rng = np.random.default_rng(0)
    a = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    b = 100 * np.cumprod(1 + rng.normal(0, 0.02, n))
    return make_snapshot({"A": list(a), "B": list(b)}, dates), dates


def _cfg():
    return make_cfg(
        ["A", "B"],
        risk={"vol_model": "ewma", "corr_window": 30, "garch_window": 100},
        signal={"top_k": 2},
    )


def test_selection_produces_valid_weights_summing_to_one():
    snap, dates = _snap()
    strat = _FixedRisky(_cfg(), absmom={"A": True, "B": True})
    dec = strat.decide(make_view(snap, dates[50]), DecisionEvent.SELECTION)
    assert dec is not None and dec.execute is True
    assert sum(dec.target_weights.values()) == pytest.approx(1.0)
    E = dec.diagnostics.exposure_applied
    assert 0.0 < E <= 1.0
    assert dec.target_weights[CASH] == pytest.approx(1.0 - E)


def test_absmom_fail_routes_to_cash():
    snap, dates = _snap()
    strat = _FixedRisky(_cfg(), absmom={"A": True, "B": False})
    dec = strat.decide(make_view(snap, dates[50]), DecisionEvent.SELECTION)
    assert dec.target_weights.get("B", 0.0) == 0.0
    assert sum(dec.target_weights.values()) == pytest.approx(1.0)


def test_exposure_check_before_selection_returns_none():
    snap, dates = _snap()
    strat = _FixedRisky(_cfg(), absmom={"A": True, "B": True})
    assert strat.decide(make_view(snap, dates[50]), DecisionEvent.EXPOSURE_CHECK) is None


def test_band_block_yields_log_only_decision():
    snap, dates = _snap()
    strat = _FixedRisky(_cfg(), absmom={"A": True, "B": True})
    strat.decide(make_view(snap, dates[50]), DecisionEvent.SELECTION)
    e0 = strat._e_current
    dec = strat.decide(make_view(snap, dates[55]), DecisionEvent.EXPOSURE_CHECK)
    if dec.diagnostics.band_blocked:
        assert dec.execute is False
        assert strat._e_current == e0


def test_forecast_selected_returns_sigma_params_fellback_triple():
    from quantcore.backtest.strategies.vol_target_base import forecast_selected
    from quantcore.models.volatility.forecaster import VolForecaster

    snap, dates = _snap()
    view = make_view(snap, dates[50])
    f = VolForecaster("ewma", ewma_lambda=0.94, horizon=21, garch_window=100)
    sigma_hat, garch_params, fell_back = forecast_selected(f, view, ["A", "B"])
    assert set(sigma_hat) == {"A", "B"} and all(v > 0 for v in sigma_hat.values())
    assert garch_params == {"A": None, "B": None}  # ewma → 無 GARCH 參數
    assert fell_back == {"A": False, "B": False}
