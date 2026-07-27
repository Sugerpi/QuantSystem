"""相對權重與絕對動量轉現金（規格 §1.6 Step 2、§1.4）。"""

import numpy as np
import pandas as pd
import pytest

from quantcore.portfolio.weighting import (
    equal_weight,
    erc_weights,
    inverse_vol,
    route_absmom_to_cash,
)


def test_inverse_vol_lower_weight_for_higher_vol():
    w = inverse_vol({"A": 0.1, "B": 0.2})
    # 1/0.1=10, 1/0.2=5, sum=15
    assert w["A"] == pytest.approx(10 / 15)
    assert w["B"] == pytest.approx(5 / 15)
    assert sum(w.values()) == pytest.approx(1.0)


def test_inverse_vol_rejects_nonfinite_sigma():
    with pytest.raises(ValueError):
        inverse_vol({"A": float("nan"), "B": 0.2})


def test_inverse_vol_rejects_nonpositive_sigma():
    with pytest.raises(ValueError):
        inverse_vol({"A": 0.0, "B": 0.2})


def test_inverse_vol_rejects_empty():
    with pytest.raises(ValueError):
        inverse_vol({})


def test_equal_weight_rejects_empty():
    with pytest.raises(ValueError):
        equal_weight([])


def test_equal_weight_sums_to_one():
    w = equal_weight(["A", "B", "C"])
    assert w == {"A": pytest.approx(1 / 3), "B": pytest.approx(1 / 3), "C": pytest.approx(1 / 3)}


def test_route_absmom_moves_failed_weight_to_cash():
    weights, cash = route_absmom_to_cash({"A": 0.6, "B": 0.4}, {"A": True, "B": False})
    assert weights == {"A": 0.6}
    assert cash == pytest.approx(0.4)
    assert sum(weights.values()) + cash == pytest.approx(1.0)


def test_route_absmom_conserves_non_unit_total():
    # w_risky 總和刻意 = 0.8，驗證守恆的是「輸入總和」而非「歸一到 1」
    weights, cash = route_absmom_to_cash({"A": 0.5, "B": 0.3}, {"A": True, "B": False})
    assert weights == {"A": 0.5}
    assert cash == pytest.approx(0.3)
    assert sum(weights.values()) + cash == pytest.approx(0.8)


def test_route_absmom_all_fail_all_cash():
    weights, cash = route_absmom_to_cash({"A": 0.5, "B": 0.5}, {"A": False, "B": False})
    assert weights == {}
    assert cash == pytest.approx(1.0)


def _cov(sigmas, corr):
    """由波動向量 + 相關矩陣組共變異數 DataFrame（label-aligned）。"""
    d = np.diag(sigmas)
    s = d @ corr @ d
    n = len(sigmas)
    labels = [chr(ord("A") + i) for i in range(n)]
    return pd.DataFrame(s, index=labels, columns=labels)


def test_erc_equal_vol_equal_corr_is_equal_weight():
    corr = np.array([[1.0, 0.3, 0.3], [0.3, 1.0, 0.3], [0.3, 0.3, 1.0]])
    cov = _cov([0.2, 0.2, 0.2], corr)
    w = erc_weights(cov)
    assert set(w) == {"A", "B", "C"}
    assert np.allclose(list(w.values()), 1 / 3, atol=1e-6)


def test_erc_risk_contributions_are_equal():
    corr = np.array([[1.0, 0.5, 0.2], [0.5, 1.0, 0.4], [0.2, 0.4, 1.0]])
    cov = _cov([0.15, 0.25, 0.10], corr)
    w = erc_weights(cov)
    labels = list(cov.columns)
    wv = np.array([w[t] for t in labels])
    s = cov.to_numpy()
    rc = wv * (s @ wv)
    assert np.allclose(rc, rc.mean(), rtol=1e-4)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert all(v > 0 for v in w.values())


def test_erc_lower_vol_gets_more_weight():
    corr = np.array([[1.0, 0.3], [0.3, 1.0]])
    cov = _cov([0.10, 0.30], corr)
    w = erc_weights(cov)
    assert w["A"] > w["B"]


def test_erc_single_asset():
    cov = pd.DataFrame([[0.04]], index=["A"], columns=["A"])
    assert erc_weights(cov) == {"A": 1.0}


def test_erc_rejects_nonfinite_and_nonpositive_diag():
    bad = pd.DataFrame([[np.nan, 0.0], [0.0, 0.04]], index=["A", "B"], columns=["A", "B"])
    with pytest.raises(ValueError):
        erc_weights(bad)
    zero = pd.DataFrame([[0.0, 0.0], [0.0, 0.04]], index=["A", "B"], columns=["A", "B"])
    with pytest.raises(ValueError):
        erc_weights(zero)


def test_erc_deterministic():
    corr = np.array([[1.0, 0.5], [0.5, 1.0]])
    cov = _cov([0.15, 0.25], corr)
    assert erc_weights(cov) == erc_weights(cov)


def test_erc_near_singular_high_correlation_converges():
    # normalize_to_correlation 可能交出趨近奇異的 Σ（相關近 1）；CCD 仍應收斂
    rho = 0.98
    corr = np.array([[1.0, rho, rho], [rho, 1.0, rho], [rho, rho, 1.0]])
    cov = _cov([0.15, 0.20, 0.25], corr)
    w = erc_weights(cov)
    labels = list(cov.columns)
    wv = np.array([w[t] for t in labels])
    rc = wv * (cov.to_numpy() @ wv)
    assert np.allclose(rc, rc.mean(), rtol=1e-3)
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_erc_raises_on_nonconvergence(monkeypatch):
    import quantcore.portfolio.weighting as wmod

    monkeypatch.setattr(wmod, "_ERC_MAX_ITER", 1)  # 1 輪不足以收斂到 1e-10
    corr = np.array([[1.0, 0.5, 0.2], [0.5, 1.0, 0.4], [0.2, 0.4, 1.0]])
    cov = _cov([0.15, 0.25, 0.10], corr)
    with pytest.raises(ValueError):
        erc_weights(cov)


def test_erc_single_asset_nonpositive_diag_raises():
    import pytest

    cov = pd.DataFrame([[0.0]], index=["A"], columns=["A"])
    with pytest.raises(ValueError):
        erc_weights(cov)
