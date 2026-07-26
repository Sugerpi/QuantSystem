import numpy as np
import pandas as pd
import pytest

from quantcore.models.correlation.base import normalize_to_correlation
from quantcore.models.correlation.dcc import DccParams, dcc_recursion, q_bar
from quantcore.models.correlation.ewma_corr import ewma_correlation


def test_normalize_valid_correlation_is_near_identity():
    # 已是合法相關矩陣：正規化近乎恆等
    R = np.array([[1.0, 0.3, -0.2], [0.3, 1.0, 0.1], [-0.2, 0.1, 1.0]])
    out = normalize_to_correlation(R)
    assert np.allclose(out, R, atol=1e-10)


def test_normalize_projects_non_psd_to_valid_correlation():
    # 刻意非 PSD（最小特徵值 < 0）→ 輸出對稱、PSD、單位對角
    bad = np.array([[1.0, 0.9, 0.9], [0.9, 1.0, -0.9], [0.9, -0.9, 1.0]])
    out = normalize_to_correlation(bad)
    assert np.allclose(out, out.T, atol=1e-12)  # 對稱
    assert np.min(np.linalg.eigvalsh(out)) >= -1e-10  # PSD
    assert np.allclose(np.diag(out), 1.0, atol=1e-10)  # 單位對角


def test_normalize_covariance_like_input_returns_correlation():
    # 非單位對角的 Q（DCC 的 Q_t）→ 正規化為相關矩陣
    Q = np.array([[4.0, 1.0], [1.0, 9.0]])
    out = normalize_to_correlation(Q)
    assert np.allclose(np.diag(out), 1.0)
    assert np.isclose(out[0, 1], 1.0 / np.sqrt(4.0 * 9.0))


def _resid_frame():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2020-01-01", periods=200, freq="B")
    data = rng.standard_normal((200, 3))
    return pd.DataFrame(data, index=idx, columns=["B", "A", "C"])


def test_ewma_correlation_returns_valid_labeled_correlation():
    R = ewma_correlation(_resid_frame(), lam=0.94)
    assert list(R.columns) == ["A", "B", "C"]  # 依 label 排序
    assert list(R.index) == ["A", "B", "C"]
    assert np.allclose(np.diag(R.to_numpy()), 1.0)
    assert np.min(np.linalg.eigvalsh(R.to_numpy())) >= -1e-10


def test_ewma_first_step_matches_hand_recursion():
    # S_0 = 樣本共變異數；S_1 = (1-λ) e_0 e_0' + λ S_0；R = normalize(S_last)
    idx = pd.date_range("2020-01-01", periods=3, freq="B")
    E = pd.DataFrame([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], index=idx, columns=["A", "B"])
    lam = 0.9
    arr = E.to_numpy()
    S = np.cov(arr, rowvar=False)
    for t in range(1, len(arr)):
        e = arr[t - 1][:, None]
        S = (1 - lam) * (e @ e.T) + lam * S
    expected = normalize_to_correlation(S)
    got = ewma_correlation(E, lam=lam).to_numpy()
    assert np.allclose(got, expected, atol=1e-12)


def test_normalize_raises_on_degenerate_zero_variance_diagonal():
    # 零變異數資產（整列/欄為 0）→ 對角線塌陷，須誠實拋錯而非靜默產出 R_ii=0
    M = np.array([[1.0, 0.0], [0.0, 0.0]])  # 第二資產變異數為 0
    with pytest.raises(ValueError):
        normalize_to_correlation(M)


def test_ewma_correlation_raises_on_zero_variance_asset():
    # 常數（零）標準化殘差欄 → EWMA 相關應誠實拋錯（不靜默腐蝕下游變異數）
    idx = pd.date_range("2020-01-01", periods=50, freq="B")
    rng = np.random.default_rng(1)
    data = rng.standard_normal((50, 2))
    data[:, 1] = 0.0  # B 資產全 0
    E = pd.DataFrame(data, index=idx, columns=["A", "B"])
    with pytest.raises(ValueError):
        ewma_correlation(E, lam=0.94)


def test_q_bar_shrinks_toward_identity():
    E = _resid_frame()
    Q = q_bar(E)
    assert np.allclose(Q, Q.T)
    assert np.min(np.linalg.eigvalsh(Q)) > 0  # shrink 後正定
    # 對角線 ≈ 1（相關矩陣 shrink 到單位對角仍為 1）
    assert np.allclose(np.diag(Q), 1.0, atol=1e-10)


def test_dcc_recursion_first_step_matches_hand():
    idx = pd.date_range("2020-01-01", periods=3, freq="B")
    E = pd.DataFrame([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], index=idx, columns=["A", "B"])
    Qbar = q_bar(E)
    a, b = 0.05, 0.90
    Q = Qbar.copy()
    arr = E.to_numpy()
    for t in range(1, len(arr)):
        e = arr[t - 1][:, None]
        Q = (1 - a - b) * Qbar + a * (e @ e.T) + b * Q
    expected = normalize_to_correlation(Q)
    got = dcc_recursion(E, DccParams(a=a, b=b, q_bar=Qbar)).to_numpy()
    assert np.allclose(got, expected, atol=1e-12)


def test_dcc_recursion_returns_valid_labeled_correlation():
    R = dcc_recursion(_resid_frame(), DccParams(a=0.05, b=0.9, q_bar=q_bar(_resid_frame())))
    assert list(R.columns) == ["A", "B", "C"]
    assert np.allclose(np.diag(R.to_numpy()), 1.0)
    assert np.min(np.linalg.eigvalsh(R.to_numpy())) >= -1e-10
