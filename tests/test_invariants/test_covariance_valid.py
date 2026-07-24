"""INV-3：共變異數矩陣永遠對稱、PSD、對角線=個別變異數（規格 §3 INV-3）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantcore.models.covariance import build_covariance


def test_covariance_symmetric_psd_diag_on_valid_R():
    sigma = {"A": 0.2, "B": 0.3, "C": 0.25}
    tickers = ["A", "B", "C"]
    R = pd.DataFrame(
        [[1.0, 0.4, 0.2], [0.4, 1.0, 0.3], [0.2, 0.3, 1.0]], index=tickers, columns=tickers
    )
    Sigma = build_covariance(sigma, R)
    assert np.allclose(Sigma.to_numpy(), Sigma.to_numpy().T)  # 對稱
    assert np.linalg.eigvalsh(Sigma.to_numpy()).min() >= -1e-10  # PSD
    for t in tickers:
        assert Sigma.loc[t, t] == pytest.approx(sigma[t] ** 2)  # 對角線=個別變異數


def test_covariance_projection_has_teeth_on_non_psd_R():
    # 有牙齒守護：對刻意非 PSD 的 R，輸出仍須 PSD 且對角線精確=σ_i²。
    # 若拿掉 build_covariance 的 R PSD 投影/單位對角重正規化，此測試轉紅。
    sigma = {"A": 0.2, "B": 0.2, "C": 0.2}
    tickers = ["A", "B", "C"]
    R_bad = pd.DataFrame(
        [[1.0, 0.95, -0.95], [0.95, 1.0, 0.95], [-0.95, 0.95, 1.0]], index=tickers, columns=tickers
    )
    assert np.linalg.eigvalsh(R_bad.to_numpy()).min() < 0  # 輸入確實非 PSD
    Sigma = build_covariance(sigma, R_bad)
    assert np.linalg.eigvalsh(Sigma.to_numpy()).min() >= -1e-10  # 投影後 PSD
    for t in tickers:
        assert Sigma.loc[t, t] == pytest.approx(0.2**2)  # 對角線嚴守


def test_covariance_single_asset_is_variance():
    R = pd.DataFrame([[1.0]], index=["SPY"], columns=["SPY"])
    Sigma = build_covariance({"SPY": 0.15}, R)
    assert Sigma.shape == (1, 1)
    assert Sigma.loc["SPY", "SPY"] == pytest.approx(0.15**2)
