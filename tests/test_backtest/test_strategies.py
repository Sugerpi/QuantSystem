"""Phase 2 的兩個 benchmark 策略（規格 §6.3）。"""

import numpy as np

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategies import STRATEGIES
from quantcore.backtest.strategy import DecisionEvent
from quantcore.config import load_config
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot

CONFIG_YAML = "quantcore/config/default.yaml"


def _cfg(min_history_days=10):
    cfg = load_config(CONFIG_YAML).model_copy(deep=True)
    cfg.universe.menu = ["SPY", "QQQ", "LATE"]
    cfg.universe.min_history_days = min_history_days
    cfg.signal.top_k = 2
    return cfg


def _snap(n=30):
    dates = make_dates(n)
    snap = make_snapshot(
        {
            "SPY": list(100.0 + np.arange(n)),
            "QQQ": list(200.0 + np.arange(n)),
            "LATE": list(50.0 + np.arange(5)),
        },
        dates,
    )
    return snap, dates


def test_bh_spy_decides_once_then_never_again():
    """§6.3：Buy & Hold —— 全期僅一次交易。"""
    cfg = _cfg()
    snap, dates = _snap()
    s = STRATEGIES["bh_spy"](cfg)

    first = s.decide(make_view(snap, dates[10]), DecisionEvent.SELECTION)
    assert first is not None
    assert first.target_weights == {"SPY": 1.0, CASH: 0.0}
    assert first.diagnostics.selected == ["SPY"]

    assert s.decide(make_view(snap, dates[11]), DecisionEvent.SELECTION) is None
    assert s.decide(make_view(snap, dates[12]), DecisionEvent.EXPOSURE_CHECK) is None


def test_bh_spy_needs_no_warmup():
    assert STRATEGIES["bh_spy"](_cfg()).warmup_days == 0


def test_ew_menu_equal_weights_eligible_only():
    cfg = _cfg(min_history_days=10)
    snap, dates = _snap()
    s = STRATEGIES["ew_menu"](cfg)

    d = s.decide(make_view(snap, dates[-1]), DecisionEvent.SELECTION)
    assert d is not None
    # LATE 只有 5 個 bar < 10 → 不合格
    assert d.diagnostics.eligible == ["QQQ", "SPY"]
    assert d.target_weights == {"QQQ": 0.5, "SPY": 0.5, CASH: 0.0}
    assert sum(d.target_weights.values()) == 1.0


def test_ew_menu_ignores_exposure_check_days():
    """§1.7：曝險檢查日只重算 E(t)；ew_menu 無曝險模型故不動作。"""
    cfg = _cfg()
    snap, dates = _snap()
    s = STRATEGIES["ew_menu"](cfg)
    assert s.decide(make_view(snap, dates[-1]), DecisionEvent.EXPOSURE_CHECK) is None


def test_ew_menu_warmup_is_min_history_days():
    assert STRATEGIES["ew_menu"](_cfg(min_history_days=252)).warmup_days == 252


def test_ew_menu_returns_none_when_nothing_eligible():
    cfg = _cfg(min_history_days=999)
    snap, dates = _snap()
    s = STRATEGIES["ew_menu"](cfg)
    assert s.decide(make_view(snap, dates[-1]), DecisionEvent.SELECTION) is None


def test_sixty_forty_targets_60_40():
    dates = make_dates(10)
    snap = make_snapshot(
        {"SPY": [100.0 + i for i in range(10)], "IEF": [50.0 + i for i in range(10)]}, dates
    )
    cfg = make_cfg(["SPY", "IEF"], signal={"top_k": 2})
    strat = STRATEGIES["sixty_forty"](cfg)
    d = strat.decide(make_view(snap, dates[-1]), DecisionEvent.SELECTION)
    assert d.target_weights == {"SPY": 0.6, "IEF": 0.4, "CASH": 0.0}


def test_sixty_forty_no_action_on_exposure_check():
    dates = make_dates(10)
    snap = make_snapshot({"SPY": [100.0 + i for i in range(10)]}, dates)
    cfg = make_cfg(["SPY", "IEF"], signal={"top_k": 2})
    strat = STRATEGIES["sixty_forty"](cfg)
    assert strat.decide(make_view(snap, dates[-1]), DecisionEvent.EXPOSURE_CHECK) is None


def test_full_and_voltarget_only_registered():
    from quantcore.backtest.strategies import STRATEGIES

    assert "full" in STRATEGIES
    assert "voltarget_only" in STRATEGIES
    assert STRATEGIES["full"].strategy_id == "full"
    assert STRATEGIES["voltarget_only"].strategy_id == "voltarget_only"
