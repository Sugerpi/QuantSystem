"""Stationary block bootstrap 索引：形狀、界限、決定性、塊結構。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantcore.backtest.accounting import CASH
from quantcore.backtest.metrics import (
    average_exposure,
    bootstrap_metric_ci,
    compute_metrics,
    metric_calmar,
    metric_sharpe,
    paired_metric_diff_ci,
    stationary_bootstrap_indices,
    subperiod_metrics,
)


def _rf(n):
    return np.full(n, 0.0001)


def test_metric_adapters_finite():
    rng = np.random.default_rng(0)
    r = rng.normal(0.0005, 0.01, 500)
    assert np.isfinite(metric_sharpe(r, _rf(500)))
    assert np.isfinite(metric_calmar(r, _rf(500)))


def test_ci_brackets_point_for_noisy_series():
    rng = np.random.default_rng(3)
    r = rng.normal(0.0005, 0.01, 500)
    idx = stationary_bootstrap_indices(500, 21, 500, np.random.default_rng(9))
    point, lo, hi = bootstrap_metric_ci(r, _rf(500), metric_sharpe, idx)
    assert lo <= point <= hi
    assert lo < hi


def test_paired_diff_identical_series_ci_contains_zero():
    rng = np.random.default_rng(5)
    r = rng.normal(0.0005, 0.01, 500)
    idx = stationary_bootstrap_indices(500, 21, 500, np.random.default_rng(11))
    res = paired_metric_diff_ci(r, r.copy(), _rf(500), metric_sharpe, idx)
    # 配對性守護：相同序列 → 逐次差異恆為 0（若誤用獨立抽樣，差異會有雜訊、CI 不退化）
    assert res["point"] == 0.0
    assert res["lo"] == 0.0 and res["hi"] == 0.0
    assert res["excludes_zero"] is False


def test_paired_diff_shifted_series_excludes_zero():
    rng = np.random.default_rng(6)
    ra = rng.normal(0.001, 0.01, 800)
    rb = ra - 0.0008
    idx = stationary_bootstrap_indices(800, 21, 800, np.random.default_rng(13))
    res = paired_metric_diff_ci(ra, rb, _rf(800), metric_sharpe, idx)
    assert res["point"] > 0
    assert res["excludes_zero"] is True


def test_bootstrap_ci_deterministic():
    rng = np.random.default_rng(2)
    r = rng.normal(0.0005, 0.01, 300)
    i1 = stationary_bootstrap_indices(300, 21, 300, np.random.default_rng(1))
    i2 = stationary_bootstrap_indices(300, 21, 300, np.random.default_rng(1))
    assert bootstrap_metric_ci(r, _rf(300), metric_sharpe, i1) == bootstrap_metric_ci(
        r, _rf(300), metric_sharpe, i2
    )


def test_ci_all_nonfinite_returns_nan_not_crash():
    r = np.full(100, 0.001)
    idx = stationary_bootstrap_indices(100, 21, 50, np.random.default_rng(1))
    point, lo, hi = bootstrap_metric_ci(r, _rf(100), lambda a, b: float("nan"), idx)
    assert np.isnan(lo) and np.isnan(hi)


def test_paired_diff_all_nonfinite_returns_nan_excludes_false():
    r = np.full(100, 0.001)
    idx = stationary_bootstrap_indices(100, 21, 50, np.random.default_rng(1))
    res = paired_metric_diff_ci(r, r, _rf(100), lambda a, b: float("nan"), idx)
    assert np.isnan(res["lo"]) and np.isnan(res["hi"])
    assert res["excludes_zero"] is False


def test_indices_shape_and_bounds():
    rng = np.random.default_rng(42)
    idx = stationary_bootstrap_indices(n=200, mean_block=21, n_reps=50, rng=rng)
    assert idx.shape == (50, 200)
    assert idx.min() >= 0 and idx.max() < 200


def test_indices_deterministic_given_seed():
    a = stationary_bootstrap_indices(200, 21, 50, np.random.default_rng(7))
    b = stationary_bootstrap_indices(200, 21, 50, np.random.default_rng(7))
    assert np.array_equal(a, b)


def test_block_structure_continuation_ratio():
    # 連續（idx[t] == idx[t-1]+1 mod n）的比例應約 1 − 1/mean_block
    rng = np.random.default_rng(1)
    n, mb = 5000, 21
    idx = stationary_bootstrap_indices(n, mb, 20, rng)
    cont = 0
    total = 0
    for r in range(idx.shape[0]):
        for t in range(1, n):
            total += 1
            if idx[r, t] == (idx[r, t - 1] + 1) % n:
                cont += 1
    ratio = cont / total
    assert abs(ratio - (1 - 1 / mb)) < 0.03


def test_average_exposure_hand_computation():
    # 兩天：day1 風險 0.6（cash 0.4），day2 風險 1.0（cash 0）→ 平均 0.8
    w = pd.DataFrame(
        [
            {"date": "d1", "ticker": "A", "weight": 0.6},
            {"date": "d1", "ticker": CASH, "weight": 0.4},
            {"date": "d2", "ticker": "A", "weight": 1.0},
            {"date": "d2", "ticker": CASH, "weight": 0.0},
        ]
    )
    assert average_exposure(w) == pytest.approx(0.8)


def test_compute_metrics_average_exposure_none_without_weights():
    nav = pd.Series([1.0, 1.01, 1.02])
    rate = pd.Series([0.0001, 0.0001, 0.0001])
    m = compute_metrics(nav, rate, total_turnover=0.0, total_cost=0.0)
    assert m["average_exposure"] is None


def test_compute_metrics_average_exposure_from_weights():
    nav = pd.Series([1.0, 1.01, 1.02])
    rate = pd.Series([0.0001, 0.0001, 0.0001])
    w = pd.DataFrame(
        [
            {"date": "d1", "ticker": "A", "weight": 0.5},
            {"date": "d1", "ticker": CASH, "weight": 0.5},
        ]
    )
    m = compute_metrics(nav, rate, 0.0, 0.0, weights=w)
    assert m["average_exposure"] == pytest.approx(0.5)


def test_subperiod_metrics_splits_by_year():
    dates = pd.to_datetime(["2008-06-01", "2009-06-01", "2015-06-01", "2021-06-01", "2022-06-01"])
    nav = pd.Series([1.0, 0.9, 1.2, 1.3, 1.4], index=dates)
    rate = pd.Series([0.0001] * 5, index=dates)
    out = subperiod_metrics(nav, rate, [(2005, 2009), (2010, 2019), (2020, 9999)])
    assert set(out) == {"2005-2009", "2010-2019", "2020-9999"}
    assert out["2005-2009"]["n_days"] == 2  # 2008,2009
    assert out["2010-2019"]["n_days"] == 1  # 2015
    assert out["2020-9999"]["n_days"] == 2  # 2021,2022
