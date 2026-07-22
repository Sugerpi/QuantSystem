"""QLIKE / MZ-R² 純損失函數。"""

from __future__ import annotations

import numpy as np

from quantcore.models.volatility.eval import mincer_zarnowitz_r2, qlike


def test_qlike_zero_for_perfect_forecast():
    v = np.array([1.0, 2.0, 3.0, 4.0])
    assert np.isclose(qlike(v, v), 0.0)


def test_qlike_positive_and_larger_for_worse_forecast():
    realized = np.array([1.0, 2.0, 3.0, 4.0])
    slightly_off = realized * 1.1
    way_off = realized * 2.0
    assert qlike(realized, slightly_off) > 0
    assert qlike(realized, way_off) > qlike(realized, slightly_off)


def test_mz_r2_is_one_when_realized_equals_forecast():
    f = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert np.isclose(mincer_zarnowitz_r2(f, f), 1.0)


def test_mz_r2_low_for_uncorrelated():
    rng = np.random.default_rng(0)
    realized = rng.uniform(1, 2, 200)
    forecast = rng.uniform(1, 2, 200)
    assert mincer_zarnowitz_r2(realized, forecast) < 0.2
