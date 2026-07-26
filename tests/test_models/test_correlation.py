import numpy as np

from quantcore.models.correlation.base import normalize_to_correlation


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
