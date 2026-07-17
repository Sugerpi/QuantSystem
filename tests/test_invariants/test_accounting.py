"""INV-5：會計恆等式——NAV 遞推 + 權重恆和為 1（規格 §1.5、§1.8、§3、§6.1）。

三日手算 golden case 的完整算式見 test_three_day_golden_case 的 docstring。
本檔亦是 Phase 2 唯一實際驗證現金計息的地方（bh_spy/ew_menu 恆滿倉，w_cash = 0）。
"""

import pytest

from quantcore.backtest.accounting import (
    CASH,
    apply_costs,
    apply_returns,
    portfolio_return,
    turnover,
)

RATE = 0.0001  # DTB3 2.52% 年化 ÷ 252


def test_portfolio_return_includes_cash_interest():
    assert portfolio_return({CASH: 1.0}, {}, RATE) == pytest.approx(0.0001)


def test_portfolio_return_mixes_assets_and_cash():
    r = portfolio_return({"A": 0.5, CASH: 0.5}, {"A": 0.10}, RATE)
    assert r == pytest.approx(0.5 * 0.10 + 0.5 * 0.0001)


def test_portfolio_return_raises_when_held_asset_has_no_return():
    with pytest.raises(KeyError, match="無報酬資料"):
        portfolio_return({"A": 1.0}, {}, RATE)


def test_turnover_excludes_cash_leg():
    """§1.8：賣 10% A 換現金 = 單邊 10% 換手，不是 20%（設計文件 §2.2）。"""
    assert turnover({"A": 1.0, CASH: 0.0}, {"A": 0.9, CASH: 0.1}) == pytest.approx(0.1)


def test_weights_sum_to_one_after_drift():
    _, drifted = apply_returns(1.0, {"A": 0.6, "B": 0.4, CASH: 0.0}, {"A": 0.10, "B": -0.05}, RATE)
    assert sum(drifted.values()) == pytest.approx(1.0)


def test_weights_sum_to_one_after_drift_with_cash():
    _, drifted = apply_returns(1.0, {"A": 0.5, CASH: 0.5}, {"A": 0.10}, RATE)
    assert sum(drifted.values()) == pytest.approx(1.0)


def test_three_day_golden_case():
    """三日手算 golden case（Phase 2 AC-2）。

    設定：資產 A、B + 合成現金。per_side_bps = 5（= 0.0005）。
          日利率 = 0.0252 / 252 = 0.0001。
          初始 NAV = 1.0，初始持倉 100% 現金。

    Day 1（r_A = +10%, r_B = -5%，持倉全現金故報酬不影響）
        組合報酬 = 1.0 × 0.0001                    = 0.0001
        NAV      = 1.0 × 1.0001                    = 1.0001
        漂移後   = CASH 1.0 × 1.0001 / 1.0001      = 1.0
        （Day 1 為決策日，target = {A: 0.6, B: 0.4}，Day 2 執行）

    Day 2（r_A = 0, r_B = 0；執行日）
        組合報酬 = 1.0 × 0.0001                    = 0.0001
        NAV(損益後) = 1.0001 × 1.0001              = 1.00020001
        漂移後   = CASH 1.0
        換手     = |0.6 − 0| + |0.4 − 0|           = 1.0      （不含 CASH 腿）
        成本     = 1.00020001 × 1.0 × 0.0005       = 0.000500100005
        NAV      = 1.00020001 − 0.000500100005     = 0.999699909995
        持倉     = {A: 0.6, B: 0.4, CASH: 0.0}

    Day 3（r_A = +10%, r_B = -5%）
        組合報酬 = 0.6 × 0.10 + 0.4 × (−0.05)      = 0.04
        NAV      = 0.999699909995 × 1.04           = 1.0396879063948
        漂移後   A = 0.6 × 1.10 / 1.04             = 0.6346153846153846
                 B = 0.4 × 0.95 / 1.04             = 0.3653846153846154
                 合計                               = 1.0
    """
    bps = 5.0

    # Day 1
    nav, w = apply_returns(1.0, {CASH: 1.0}, {"A": 0.10, "B": -0.05}, RATE)
    assert nav == pytest.approx(1.0001, rel=1e-12)
    assert w[CASH] == pytest.approx(1.0, rel=1e-12)
    target = {"A": 0.6, "B": 0.4, CASH: 0.0}

    # Day 2（執行日）
    nav, w = apply_returns(nav, w, {"A": 0.0, "B": 0.0}, RATE)
    assert nav == pytest.approx(1.00020001, rel=1e-12)
    nav, to = apply_costs(nav, w, target, bps)
    assert to == pytest.approx(1.0, rel=1e-12)
    assert nav == pytest.approx(0.999699909995, rel=1e-12)
    w = dict(target)

    # Day 3
    nav, w = apply_returns(nav, w, {"A": 0.10, "B": -0.05}, RATE)
    assert nav == pytest.approx(1.0396879063948, rel=1e-12)
    assert w["A"] == pytest.approx(0.6346153846153846, rel=1e-12)
    assert w["B"] == pytest.approx(0.3653846153846154, rel=1e-12)
    assert sum(w.values()) == pytest.approx(1.0, rel=1e-12)
