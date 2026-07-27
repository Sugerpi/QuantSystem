"""INV-3：共變異數矩陣永遠對稱、PSD、對角線=個別變異數（規格 §3 INV-3）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantcore.models.correlation.dcc import DccParams, dcc_recursion, q_bar
from quantcore.models.correlation.ewma_corr import ewma_correlation
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


def _resid(n=200, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame(rng.standard_normal((n, 3)), index=idx, columns=["A", "B", "C"])


def test_inv3_holds_with_dcc_R():
    # Phase 5a：R 來自 DCC 遞迴（而非舊版 rolling sample correlation）時，INV-3 仍成立。
    E = _resid()
    R = dcc_recursion(E, DccParams(0.05, 0.9, q_bar(E, 0.10)))
    sigma = {"A": 0.15, "B": 0.20, "C": 0.10}
    Sigma = build_covariance(sigma, R)
    Sigma_np = Sigma.to_numpy()
    assert np.allclose(Sigma_np, Sigma_np.T)  # 對稱
    assert np.linalg.eigvalsh(Sigma_np).min() >= -1e-10  # PSD
    for t in sigma:
        assert Sigma.loc[t, t] == pytest.approx(sigma[t] ** 2)  # 對角線=個別變異數（label-based）


def test_inv3_holds_with_ewma_R():
    # Phase 5a：R 來自 EWMA 相關時，INV-3 仍成立。
    E = _resid()
    R = ewma_correlation(E, lam=0.94)
    sigma = {"A": 0.15, "B": 0.20, "C": 0.10}
    Sigma = build_covariance(sigma, R)
    Sigma_np = Sigma.to_numpy()
    assert np.allclose(Sigma_np, Sigma_np.T)  # 對稱
    assert np.linalg.eigvalsh(Sigma_np).min() >= -1e-10  # PSD
    for t in sigma:
        assert Sigma.loc[t, t] == pytest.approx(sigma[t] ** 2)  # 對角線=個別變異數（label-based）
