"""EWMA(λ=0.94) 遞迴、flat 多步、標準化殘差、平穩性豁免。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantcore.models.volatility.ewma import Ewma


def _returns(n: int = 300) -> pd.Series:
    rng = np.random.default_rng(1)
    return pd.Series(rng.normal(0, 0.01, n))


def _reference_last_var(scaled: np.ndarray, lam: float) -> float:
    """獨立參考遞迴：回傳用於預測 r_{T+1} 的條件變異數（×100 尺度）。"""
    h = float(np.var(scaled, ddof=1))  # seed = 樣本變異數
    for t in range(1, len(scaled)):
        h = lam * h + (1 - lam) * scaled[t - 1] ** 2
    # 再納入最後一筆觀測，得預測 r_{T+1} 的條件變異數
    h = lam * h + (1 - lam) * scaled[-1] ** 2
    return h


def test_forecast_matches_reference_recursion():
    r = _returns()
    m = Ewma(0.94).fit(r)
    ref_scaled = _reference_last_var(r.to_numpy() * 100, 0.94)
    expected = ref_scaled / (100**2)  # 還原尺度
    out = m.forecast(1)
    assert np.isclose(out[0], expected, rtol=1e-9)


def test_multistep_is_flat():
    m = Ewma(0.94).fit(_returns())
    out = m.forecast(21)
    assert out.shape == (21,)
    assert np.allclose(out, out[0])  # EWMA 無均值回歸 → 常數多步


def test_lambda_exposed_in_params_no_alpha_beta():
    m = Ewma(0.94).fit(_returns())
    assert m.params["lambda"] == 0.94
    # 無 alpha/beta → base 的平穩性檢查不觸發（IGARCH 豁免）
    assert "alpha" not in m.params


def test_standardized_residuals_unit_scale():
    m = Ewma(0.94).fit(_returns(500))
    z = m.standardized_residuals
    # 標準化殘差樣本標準差應接近 1
    assert 0.7 < float(z.std()) < 1.4
