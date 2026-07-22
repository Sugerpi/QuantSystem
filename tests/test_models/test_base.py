"""base.VolatilityModel 的縮放模板與慣例檢查（INV-4 的單一實作點）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantcore.models.volatility.base import GarchDegenerateError, VolatilityModel


class _DummyModel(VolatilityModel):
    """最小具體子類：在 ×100 尺度把條件變異數固定為輸入報酬變異數，供測 base。"""

    enforce_stationarity = False
    _min_obs = 2

    def __init__(self, fake_alpha_beta: tuple[float, float] | None = None):
        self._fake_ab = fake_alpha_beta

    def _estimate(self, scaled_returns: pd.Series) -> None:
        self._scaled_var = float(scaled_returns.var(ddof=1))
        self._scaled = scaled_returns

    def _forecast_scaled(self, horizon: int) -> np.ndarray:
        return np.full(horizon, self._scaled_var, dtype="float64")

    @property
    def params(self) -> dict[str, float]:
        if self._fake_ab is None:
            return {}
        return {"alpha": self._fake_ab[0], "beta": self._fake_ab[1]}

    @property
    def standardized_residuals(self) -> pd.Series:
        return self._scaled / np.sqrt(self._scaled_var)


def _returns(n: int = 300) -> pd.Series:
    rng = np.random.default_rng(0)
    return pd.Series(rng.normal(0, 0.01, n))


def test_forecast_is_backscaled_to_return_variance():
    r = _returns()
    m = _DummyModel().fit(r)
    # base 在 ×100 尺度估計 var，forecast 應除以 100**2 還原回報酬變異數尺度
    expected = (r * 100).var(ddof=1) / (100**2)
    out = m.forecast(5)
    assert out.shape == (5,)
    assert np.allclose(out, expected)
    # 還原後應與原始報酬變異數同數量級
    assert np.isclose(out[0], r.var(ddof=1), rtol=0.05)


def test_forecast_before_fit_raises():
    with pytest.raises(RuntimeError):
        _DummyModel().forecast(1)


def test_horizon_must_be_positive():
    m = _DummyModel().fit(_returns())
    with pytest.raises(ValueError):
        m.forecast(0)


def test_stationarity_enforced_only_when_flag_set():
    r = _returns()
    # 旗標關閉（EWMA 情境）：α+β=1 不該擋
    _DummyModel(fake_alpha_beta=(0.2, 0.8)).fit(r)

    class _Enforced(_DummyModel):
        enforce_stationarity = True

    with pytest.raises(GarchDegenerateError):
        _Enforced(fake_alpha_beta=(0.2, 0.85)).fit(r)  # α+β=1.05 ≥ 1
    # α+β<1 正常
    _Enforced(fake_alpha_beta=(0.1, 0.85)).fit(r)


def test_forecast_non_finite_raises_garch_degenerate():
    class _NonFiniteModel(_DummyModel):
        def _forecast_scaled(self, horizon: int) -> np.ndarray:
            return np.full(horizon, np.inf, dtype="float64")

    m = _NonFiniteModel().fit(_returns())
    with pytest.raises(GarchDegenerateError):
        m.forecast(3)


def test_fit_insufficient_observations_raises_value_error():
    with pytest.raises(ValueError):
        _DummyModel().fit(pd.Series([0.01]))
