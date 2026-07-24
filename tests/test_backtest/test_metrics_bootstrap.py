"""Stationary block bootstrap 索引：形狀、界限、決定性、塊結構。"""

from __future__ import annotations

import numpy as np

from quantcore.backtest.metrics import (
    bootstrap_metric_ci,
    metric_calmar,
    metric_sharpe,
    paired_metric_diff_ci,
    stationary_bootstrap_indices,
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
