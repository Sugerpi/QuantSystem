"""過渡共變異數：INV-3 三性質 + 手算 + 單資產退化（規格 §1.6、INV-3）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantcore.models.covariance import build_covariance, portfolio_vol, rolling_correlation


def test_rolling_correlation_returns_sorted_tickers_and_symmetric_R():
    rng = np.random.default_rng(0)
    df = pd.DataFrame(rng.normal(0, 0.01, (300, 3)), columns=["B", "A", "C"])
    R = rolling_correlation(df)
    assert list(R.columns) == ["A", "B", "C"]  # 排序
    assert R.shape == (3, 3)
    assert np.allclose(R.to_numpy(), R.to_numpy().T)
    assert np.allclose(np.diag(R.to_numpy()), 1.0)


def test_build_covariance_hand_computation():
    # 已知 R 與 σ̂，Σ = D R D 逐元比對
    sigma = {"A": 0.2, "B": 0.3}
    R = pd.DataFrame([[1.0, 0.5], [0.5, 1.0]], index=["A", "B"], columns=["A", "B"])
    Sigma = build_covariance(sigma, R)
    expected = np.array([[0.2 * 0.2 * 1.0, 0.2 * 0.3 * 0.5], [0.3 * 0.2 * 0.5, 0.3 * 0.3 * 1.0]])
    assert np.allclose(Sigma.to_numpy(), expected)


def test_build_covariance_inv3_symmetric_psd_diag():
    sigma = {"A": 0.2, "B": 0.3, "C": 0.25}
    rng = np.random.default_rng(1)
    df = pd.DataFrame(rng.normal(0, 0.01, (300, 3)), columns=["A", "B", "C"])
    R = rolling_correlation(df)
    Sigma = build_covariance(sigma, R)
    tickers = list(Sigma.columns)
    assert np.allclose(Sigma.to_numpy(), Sigma.to_numpy().T)  # 對稱
    assert np.linalg.eigvalsh(Sigma.to_numpy()).min() >= -1e-10  # PSD
    for t in tickers:
        assert Sigma.loc[t, t] == pytest.approx(sigma[t] ** 2)  # 對角線=個別變異數


def test_build_covariance_projects_non_psd_R():
    # 刻意非 PSD 的 R（有負特徵值），投影後 Σ 仍 PSD 且對角線正確
    sigma = {"A": 0.2, "B": 0.2, "C": 0.2}
    R_bad = pd.DataFrame(
        [[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]],
        index=["A", "B", "C"],
        columns=["A", "B", "C"],
    )
    assert np.linalg.eigvalsh(R_bad.to_numpy()).min() < 0  # 確認輸入非 PSD
    Sigma = build_covariance(sigma, R_bad)
    assert np.linalg.eigvalsh(Sigma.to_numpy()).min() >= -1e-10  # 投影後 PSD
    for t in ["A", "B", "C"]:
        assert Sigma.loc[t, t] == pytest.approx(0.2**2)  # 對角線仍=σ²


def test_portfolio_vol_hand_computation():
    Sigma = pd.DataFrame([[0.04, 0.03], [0.03, 0.09]], index=["A", "B"], columns=["A", "B"])
    w = {"A": 0.5, "B": 0.5}
    sp = portfolio_vol(w, Sigma)
    expected = float(np.sqrt(0.25 * 0.04 + 0.25 * 0.09 + 2 * 0.25 * 0.03))
    assert sp == pytest.approx(expected)


def test_portfolio_vol_single_asset_equals_sigma():
    R = pd.DataFrame([[1.0]], index=["SPY"], columns=["SPY"])
    Sigma = build_covariance({"SPY": 0.15}, R)
    assert portfolio_vol({"SPY": 1.0}, Sigma) == pytest.approx(0.15)


def test_build_covariance_rejects_bad_sigma():
    with pytest.raises(ValueError):
        build_covariance(
            {"A": 0.2}, pd.DataFrame([[1.0, 0.0], [0.0, 1.0]], index=["A", "B"], columns=["A", "B"])
        )  # 缺 B
    with pytest.raises(ValueError):
        bad_sigma_R = pd.DataFrame(np.eye(2), index=["A", "B"], columns=["A", "B"])
        build_covariance({"A": -0.2, "B": 0.2}, bad_sigma_R)  # 非正


def test_build_covariance_rejects_non_finite_R():
    with pytest.raises(ValueError):
        build_covariance(
            {"A": 0.2, "B": 0.3},
            pd.DataFrame([[1.0, np.nan], [np.nan, 1.0]], index=["A", "B"], columns=["A", "B"]),
        )


def test_build_covariance_label_aligned_ignores_dict_order():
    # I-1 結構對齊：sigma_hat dict 順序與 R label 順序無關，結果只依 label
    R = pd.DataFrame([[1.0, 0.5], [0.5, 1.0]], index=["A", "B"], columns=["A", "B"])
    s1 = build_covariance({"A": 0.2, "B": 0.3}, R)
    s2 = build_covariance({"B": 0.3, "A": 0.2}, R)  # 反序 dict
    assert np.allclose(s1.to_numpy(), s2.to_numpy())
    assert s1.loc["A", "A"] == pytest.approx(0.2**2)
    assert s1.loc["B", "B"] == pytest.approx(0.3**2)


def test_portfolio_vol_rejects_weight_not_in_cov():
    # I-2：w_risky 含 cov 未涵蓋的資產（非零權重）→ 拒絕（σ̂_p 會被低估）
    cov_R = pd.DataFrame([[1.0, 0.0], [0.0, 1.0]], index=["A", "B"], columns=["A", "B"])
    cov = build_covariance({"A": 0.2, "B": 0.3}, cov_R)
    with pytest.raises(ValueError):
        portfolio_vol({"A": 0.5, "C": 0.5}, cov)  # C 不在 cov
