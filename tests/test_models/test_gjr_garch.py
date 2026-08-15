"""GJR-GARCH(1,1)-t：非對稱項 γ 估計、濾波 parity、向量長度。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantcore.models.volatility.garch_arch import (
    GarchArch,
    GjrGarchArch,
    garch_filter_forecast,
    garch_filter_residuals,
)
from tests.fixtures.synthetic import make_garch_t_returns


def test_gjr_fit_produces_gamma_and_is_stationary():
    r = make_garch_t_returns(4000, omega=1e-6, alpha=0.06, beta=0.88, nu=7, seed=7)
    m = GjrGarchArch().fit(r)
    p = m.params
    assert "gamma" in p  # GJR 多出非對稱項
    assert all(np.isfinite(v) for v in p.values())
    # GJR 平穩條件：α + β + 0.5γ < 1
    assert p["alpha"] + p["beta"] + 0.5 * p["gamma"] < 1.0
    assert p["nu"] > 3.0  # Student-t


def test_gjr_arch_params_full_vector_length_six():
    r = make_garch_t_returns(1000, omega=1e-6, alpha=0.06, beta=0.88, nu=8, seed=1)
    m = GjrGarchArch().fit(r)
    # 完整 arch 向量 [mu, omega, alpha[1], gamma[1], beta[1], nu]
    assert m.arch_params.shape == (6,)


def test_gjr_filter_forecast_matches_fit_forecast():
    r = make_garch_t_returns(1500, omega=1e-6, alpha=0.06, beta=0.88, nu=8, seed=13)
    m = GjrGarchArch().fit(r)
    filtered = garch_filter_forecast(m.arch_params, r, 21, o=1)
    assert filtered.shape == (21,)
    assert np.allclose(filtered, m.forecast(21))


def test_gjr_filter_residuals_matches_fit_scale():
    rng = np.random.default_rng(3)
    idx = pd.date_range("2018-01-01", periods=400, freq="B")
    r = pd.Series(rng.standard_normal(400) * 0.01, index=idx)
    m = GjrGarchArch().fit(r)
    resid = garch_filter_residuals(m.arch_params, r, o=1)
    assert np.allclose(resid.to_numpy(), m.standardized_residuals.to_numpy(), atol=1e-8)


def test_standard_garch_unchanged_length_five():
    # 回歸保護：標準 GARCH 路徑（o=0）向量仍 5、無 gamma。
    r = make_garch_t_returns(1000, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=1)
    m = GarchArch().fit(r)
    assert m.arch_params.shape == (5,)
    assert "gamma" not in m.params
