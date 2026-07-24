"""Decision.execute 與 Diagnostics 新欄位的預設與可設定性。"""

from __future__ import annotations

from quantcore.backtest.strategy import Decision, Diagnostics


def test_decision_execute_defaults_true():
    d = Decision(target_weights={"CASH": 1.0}, diagnostics=Diagnostics(eligible=[], selected=[]))
    assert d.execute is True


def test_decision_execute_can_be_false():
    d = Decision(
        target_weights={"CASH": 1.0},
        diagnostics=Diagnostics(eligible=[], selected=[]),
        execute=False,
    )
    assert d.execute is False


def test_diagnostics_vol_fields_default_none():
    diag = Diagnostics(eligible=[], selected=[])
    assert diag.vol_fell_back is None
    assert diag.garch_params is None


def test_diagnostics_vol_fields_settable():
    diag = Diagnostics(
        eligible=["A"],
        selected=["A"],
        vol_fell_back={"A": True},
        garch_params={"A": {"omega": 0.1, "alpha": 0.08, "beta": 0.9, "nu": 7.0}},
    )
    assert diag.vol_fell_back == {"A": True}
    assert diag.garch_params["A"]["beta"] == 0.9
