"""accounting 模組的 backtest 層測試：trade_deltas 與 turnover 的結構關係。

INV-5（會計恆等式）與現金計息等既有 accounting 測試在 tests/test_invariants/test_accounting.py。
本檔聚焦 turnover 的 per-ticker 分解（trade blotter 對帳的結構保證）。
"""

from quantcore.backtest.accounting import trade_deltas


def test_trade_deltas_excludes_cash_and_gives_signed_changes():
    drifted = {"A": 0.5, "B": 0.3, "CASH": 0.2}
    target = {"A": 0.2, "B": 0.3, "CASH": 0.5}
    d = trade_deltas(drifted, target)
    assert "CASH" not in d
    assert d["A"] == -0.3  # 賣
    assert d["B"] == 0.0  # 不動
    assert set(d) == {"A", "B"}


def test_turnover_equals_sum_abs_trade_deltas():
    """turnover 是 trade_deltas 的 |·| 總和——blotter 對帳的結構保證。"""
    from quantcore.backtest.accounting import turnover

    drifted = {"A": 0.5, "B": 0.1, "CASH": 0.4}
    target = {"A": 0.2, "C": 0.3, "CASH": 0.5}
    d = trade_deltas(drifted, target)
    assert turnover(drifted, target) == sum(abs(v) for v in d.values())
