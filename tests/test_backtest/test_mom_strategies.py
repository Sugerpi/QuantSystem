"""動量策略（規格 §1.3/§1.4/§6.3）。以 decide() 直接驗證，避開 clock 設置。"""

from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategies import STRATEGIES
from quantcore.backtest.strategy import DecisionEvent
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot

# lookback=4, skip=1, top_k=2, min_history=5, vol_window=3
_CFG_KW = dict(
    signal={"momentum_lookback": 4, "momentum_skip": 1, "top_k": 2},
    universe={"min_history_days": 5},
    risk={"vol_model": "rolling_std", "vol_window": 3},
)


def _snap(dates):
    # WIN/MID 動量為正且通過絕對動量；LOSE 動量最低、被排除
    return make_snapshot(
        {
            "WIN": [10.0, 11.0, 12.0, 13.0, 15.0, 18.0],
            "MID": [10.0, 10.5, 11.0, 11.5, 12.5, 13.0],
            "LOSE": [20.0, 19.0, 18.0, 17.0, 16.0, 15.0],
        },
        dates,
    )


def test_mom_only_selects_top_k_equal_weight():
    dates = make_dates(6)
    cfg = make_cfg(["WIN", "MID", "LOSE"], **_CFG_KW)
    strat = STRATEGIES["mom_only"](cfg)
    d = strat.decide(make_view(_snap(dates), dates[-1]), DecisionEvent.SELECTION)
    # 前 2 高動量 = WIN, MID；等權 0.5/0.5，皆通過絕對動量
    assert set(d.diagnostics.selected) == {"WIN", "MID"}
    assert d.target_weights["WIN"] == 0.5
    assert d.target_weights["MID"] == 0.5
    assert d.target_weights["CASH"] == 0.0


def test_mom_only_diagnostics_populated_but_no_sigma():
    dates = make_dates(6)
    cfg = make_cfg(["WIN", "MID", "LOSE"], **_CFG_KW)
    strat = STRATEGIES["mom_only"](cfg)
    d = strat.decide(make_view(_snap(dates), dates[-1]), DecisionEvent.SELECTION)
    assert set(d.diagnostics.momentum_scores) == {"WIN", "MID", "LOSE"}  # 全合格
    assert set(d.diagnostics.absmom) == {"WIN", "MID"}  # 只入選檔
    assert d.diagnostics.sigma_hat is None  # mom_only 無波動
    assert d.diagnostics.w_risky == {"WIN": 0.5, "MID": 0.5}


def test_mom_only_routes_absmom_failure_to_cash():
    # CRASH 動量最高（s[-2]/s[-5]=30/10-1=2.0）故入選 top-2，
    # 但絕對動量 TR=s[-1]/s[-5]=8/10-1=-0.2 為負 → 轉現金。
    # 「入選但 absmom fail → cash」是本層核心整合行為，必須被守住
    # （cross-sectional 看 s[-2]、absmom 看 s[-1]）。
    dates = make_dates(6)
    snap = make_snapshot(
        {
            "WIN": [10.0, 11.0, 12.0, 13.0, 15.0, 18.0],  # 入選且通過 absmom
            "CRASH": [10.0, 10.0, 10.0, 10.0, 30.0, 8.0],  # 動量最高入選；TR 為負 → absmom fail
            "LOSE": [20.0, 19.0, 18.0, 17.0, 16.0, 15.0],  # 動量最低，未入選
        },
        dates,
    )
    cfg = make_cfg(["WIN", "CRASH", "LOSE"], **_CFG_KW)
    strat = STRATEGIES["mom_only"](cfg)
    d = strat.decide(make_view(snap, dates[-1]), DecisionEvent.SELECTION)
    assert set(d.diagnostics.selected) == {"WIN", "CRASH"}
    assert d.diagnostics.absmom == {"WIN": True, "CRASH": False}
    assert "CRASH" not in d.target_weights  # absmom fail → 不在風險部位
    assert d.target_weights["WIN"] == 0.5  # 原配額保留，未重新歸一
    assert d.target_weights["CASH"] == 0.5  # CRASH 的 0.5 轉入現金
    assert sum(d.target_weights.values()) == 1.0  # 權重守恆（INV-5）
