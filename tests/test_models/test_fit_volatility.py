"""fit_volatility 的 fallback 政策與多步年化聚合。"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.models.volatility import (
    FitOutcome,
    annualized_forecast_vol,
    fit_volatility,
)
from quantcore.models.volatility.ewma import Ewma
from quantcore.models.volatility.garch_arch import GarchArch
from tests.fixtures.synthetic import make_garch_t_returns


def _good_returns():
    return make_garch_t_returns(1500, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=5)


def test_annualized_forecast_vol_aggregates_and_annualizes():
    m = Ewma(0.94).fit(_good_returns())
    per_step = m.forecast(21)
    expected = float(np.sqrt(per_step.mean()) * np.sqrt(252))
    assert np.isclose(annualized_forecast_vol(m, 21), expected)


def test_garch_spec_uses_garch_when_healthy():
    out = fit_volatility("garch_arch", _good_returns(), ewma_lambda=0.94)
    assert isinstance(out, FitOutcome)
    assert isinstance(out.model, GarchArch)
    assert out.fell_back is False
    assert out.reason is None


def test_garch_spec_falls_back_to_ewma_on_degenerate(monkeypatch):
    from quantcore.models.volatility import base

    def _boom(self, scaled_returns):
        raise base.GarchDegenerateError("造出的退化")

    monkeypatch.setattr(GarchArch, "_estimate", _boom)
    out = fit_volatility("garch_arch", _good_returns(), ewma_lambda=0.94)
    assert isinstance(out.model, Ewma)
    assert out.fell_back is True
    assert "退化" in out.reason


def test_ewma_spec_no_fallback():
    out = fit_volatility("ewma", _good_returns(), ewma_lambda=0.94)
    assert isinstance(out.model, Ewma)
    assert out.fell_back is False


def test_unknown_spec_raises():
    with pytest.raises(ValueError):
        fit_volatility("nope", _good_returns(), ewma_lambda=0.94)
