"""INV-3：共變異數矩陣永遠對稱、PSD、對角線=個別變異數（規格 §3 INV-3）。"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.models.covariance import build_covariance


def test_covariance_symmetric_psd_diag_on_valid_R():
    sigma = {"A": 0.2, "B": 0.3, "C": 0.25}
    R = np.array([[1.0, 0.4, 0.2], [0.4, 1.0, 0.3], [0.2, 0.3, 1.0]])
    tickers = ["A", "B", "C"]
    Sigma = build_covariance(sigma, R, tickers)
    assert np.allclose(Sigma, Sigma.T)  # 對稱
    assert np.linalg.eigvalsh(Sigma).min() >= -1e-10  # PSD
    for i, t in enumerate(tickers):
        assert Sigma[i, i] == pytest.approx(sigma[t] ** 2)  # 對角線=個別變異數


def test_covariance_projection_has_teeth_on_non_psd_R():
    # 有牙齒守護：對刻意非 PSD 的 R，輸出仍須 PSD 且對角線精確=σ_i²。
    # 若拿掉 build_covariance 的 R PSD 投影/單位對角重正規化，此測試轉紅。
    sigma = {"A": 0.2, "B": 0.2, "C": 0.2}
    R_bad = np.array([[1.0, 0.95, -0.95], [0.95, 1.0, 0.95], [-0.95, 0.95, 1.0]])
    assert np.linalg.eigvalsh(R_bad).min() < 0  # 輸入確實非 PSD
    Sigma = build_covariance(sigma, R_bad, ["A", "B", "C"])
    assert np.linalg.eigvalsh(Sigma).min() >= -1e-10  # 投影後 PSD
    for i in range(3):
        assert Sigma[i, i] == pytest.approx(0.2**2)  # 對角線嚴守


def test_covariance_single_asset_is_variance():
    Sigma = build_covariance({"SPY": 0.15}, np.array([[1.0]]), ["SPY"])
    assert Sigma.shape == (1, 1)
    assert Sigma[0, 0] == pytest.approx(0.15**2)
