"""相對權重與絕對動量轉現金（規格 §1.6 Step 2、§1.4）。"""

import pytest

from quantcore.portfolio.weighting import equal_weight, inverse_vol, route_absmom_to_cash


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


def test_equal_weight_sums_to_one():
    w = equal_weight(["A", "B", "C"])
    assert w == {"A": pytest.approx(1 / 3), "B": pytest.approx(1 / 3), "C": pytest.approx(1 / 3)}


def test_route_absmom_moves_failed_weight_to_cash():
    weights, cash = route_absmom_to_cash({"A": 0.6, "B": 0.4}, {"A": True, "B": False})
    assert weights == {"A": 0.6}
    assert cash == pytest.approx(0.4)
    assert sum(weights.values()) + cash == pytest.approx(1.0)


def test_route_absmom_all_fail_all_cash():
    weights, cash = route_absmom_to_cash({"A": 0.5, "B": 0.5}, {"A": False, "B": False})
    assert weights == {}
    assert cash == pytest.approx(1.0)
