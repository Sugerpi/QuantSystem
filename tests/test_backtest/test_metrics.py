"""績效統計（規格 §6.4）。Phase 2 不含 block bootstrap（§9）。"""

import numpy as np
import pandas as pd
import pytest

from quantcore.backtest.metrics import (
    annualized_return,
    annualized_turnover,
    calmar,
    compute_metrics,
    max_drawdown,
    sharpe,
)


def test_annualized_return_doubles_over_one_year():
    nav = pd.Series(np.linspace(1.0, 2.0, 253))
    assert annualized_return(nav) == pytest.approx(1.0, rel=1e-9)


def test_max_drawdown_of_peak_then_trough():
    nav = pd.Series([1.0, 2.0, 1.0, 1.5])
    assert max_drawdown(nav) == pytest.approx(-0.5)


def test_max_drawdown_is_zero_for_monotonic_nav():
    assert max_drawdown(pd.Series([1.0, 1.1, 1.2])) == pytest.approx(0.0)


def test_sharpe_is_zero_when_return_equals_riskfree():
    ret = pd.Series([0.0001] * 100)
    rf = pd.Series([0.0001] * 100)
    assert sharpe(ret, rf) == pytest.approx(0.0, abs=1e-12)


def test_sharpe_is_nan_when_excess_has_no_variance_but_nonzero_mean():
    """常數超額報酬 → 標準差 0 → Sharpe 無定義。回 nan 而非 inf 或崩潰。"""
    ret = pd.Series([0.001] * 100)
    rf = pd.Series([0.0] * 100)
    assert np.isnan(sharpe(ret, rf))


def test_calmar_is_cagr_over_abs_maxdd():
    nav = pd.Series([1.0, 2.0, 1.0, 1.5])
    assert calmar(nav) == pytest.approx(annualized_return(nav) / 0.5)


def test_annualized_turnover_scales_to_252_days():
    assert annualized_turnover(total_turnover=2.0, n_days=126) == pytest.approx(4.0)


def test_compute_metrics_returns_all_keys():
    n = 300
    nav = pd.Series(np.cumprod(1 + np.full(n, 0.0004)), index=pd.RangeIndex(n))
    rf = pd.Series(np.full(n, 0.0001))
    m = compute_metrics(nav=nav, rate_daily=rf, total_turnover=1.0, total_cost=0.0005)
    assert set(m) == {
        "annualized_return",
        "sharpe",
        "sortino",
        "max_drawdown",
        "calmar",
        "annualized_turnover",
        "cost_drag_bps_per_year",
        "n_days",
        "average_exposure",
        "annualized_vol",
    }
    assert m["n_days"] == n


def test_annualized_vol_matches_std_times_sqrt252():
    from quantcore.backtest.metrics import annualized_vol

    n = 300
    rng = np.random.default_rng(0)
    r = rng.normal(0, 0.01, n)
    nav = pd.Series(np.cumprod(1 + r), index=pd.RangeIndex(n))
    daily = nav.pct_change().dropna().to_numpy()
    assert annualized_vol(nav) == pytest.approx(np.std(daily, ddof=1) * np.sqrt(252))
