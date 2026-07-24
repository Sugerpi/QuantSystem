"""Stationary block bootstrap 索引：形狀、界限、決定性、塊結構。"""

from __future__ import annotations

import numpy as np

from quantcore.backtest.metrics import stationary_bootstrap_indices


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
