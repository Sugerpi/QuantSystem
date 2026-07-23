"""過渡共變異數：INV-3 三性質 + 手算 + 單資產退化（規格 §1.6、INV-3）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantcore.models.covariance import build_covariance, portfolio_vol, rolling_correlation


def test_rolling_correlation_returns_sorted_tickers_and_symmetric_R():
    rng = np.random.default_rng(0)
    df = pd.DataFrame(rng.normal(0, 0.01, (300, 3)), columns=["B", "A", "C"])
    R, tickers = rolling_correlation(df)
    assert tickers == ["A", "B", "C"]  # 排序
    assert R.shape == (3, 3)
    assert np.allclose(R, R.T)
    assert np.allclose(np.diag(R), 1.0)


def test_build_covariance_hand_computation():
    # 已知 R 與 σ̂，Σ = D R D 逐元比對
    sigma = {"A": 0.2, "B": 0.3}
    R = np.array([[1.0, 0.5], [0.5, 1.0]])
    Sigma = build_covariance(sigma, R, ["A", "B"])
    expected = np.array([[0.2 * 0.2 * 1.0, 0.2 * 0.3 * 0.5], [0.3 * 0.2 * 0.5, 0.3 * 0.3 * 1.0]])
    assert np.allclose(Sigma, expected)


def test_build_covariance_inv3_symmetric_psd_diag():
    sigma = {"A": 0.2, "B": 0.3, "C": 0.25}
    rng = np.random.default_rng(1)
    df = pd.DataFrame(rng.normal(0, 0.01, (300, 3)), columns=["A", "B", "C"])
    R, tickers = rolling_correlation(df)
    Sigma = build_covariance(sigma, R, tickers)
    assert np.allclose(Sigma, Sigma.T)  # 對稱
    assert np.linalg.eigvalsh(Sigma).min() >= -1e-10  # PSD
    for i, t in enumerate(tickers):
        assert Sigma[i, i] == pytest.approx(sigma[t] ** 2)  # 對角線=個別變異數


def test_build_covariance_projects_non_psd_R():
    # 刻意非 PSD 的 R（有負特徵值），投影後 Σ 仍 PSD 且對角線正確
    sigma = {"A": 0.2, "B": 0.2, "C": 0.2}
    R_bad = np.array([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]])
    assert np.linalg.eigvalsh(R_bad).min() < 0  # 確認輸入非 PSD
    Sigma = build_covariance(sigma, R_bad, ["A", "B", "C"])
    assert np.linalg.eigvalsh(Sigma).min() >= -1e-10  # 投影後 PSD
    for i in range(3):
        assert Sigma[i, i] == pytest.approx(0.2**2)  # 對角線仍=σ²


def test_portfolio_vol_hand_computation():
    Sigma = np.array([[0.04, 0.03], [0.03, 0.09]])
    w = {"A": 0.5, "B": 0.5}
    sp = portfolio_vol(w, Sigma, ["A", "B"])
    expected = float(np.sqrt(0.25 * 0.04 + 0.25 * 0.09 + 2 * 0.25 * 0.03))
    assert sp == pytest.approx(expected)


def test_portfolio_vol_single_asset_equals_sigma():
    Sigma = build_covariance({"SPY": 0.15}, np.array([[1.0]]), ["SPY"])
    assert portfolio_vol({"SPY": 1.0}, Sigma, ["SPY"]) == pytest.approx(0.15)


def test_build_covariance_rejects_bad_sigma():
    with pytest.raises(ValueError):
        build_covariance({"A": 0.2}, np.array([[1.0, 0.0], [0.0, 1.0]]), ["A", "B"])  # 缺 B
    with pytest.raises(ValueError):
        build_covariance({"A": -0.2, "B": 0.2}, np.eye(2), ["A", "B"])  # 非正


def test_build_covariance_rejects_non_finite_R():
    with pytest.raises(ValueError):
        build_covariance({"A": 0.2, "B": 0.3}, np.array([[1.0, np.nan], [np.nan, 1.0]]), ["A", "B"])


def test_build_covariance_rejects_R_ticker_length_mismatch():
    with pytest.raises(ValueError):
        build_covariance({"A": 0.2, "B": 0.3}, np.array([[1.0]]), ["A", "B"])  # 1x1 R vs 2 tickers
