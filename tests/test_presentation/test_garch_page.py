"""GARCH 頁：GJR run 顯示 γ、persistence 納入 0.5γ；純 GARCH 回歸不變。"""

from __future__ import annotations

import pandas as pd

from quantcore.presentation.web.routes.garch import _param_rows


def _sub(params):
    return pd.DataFrame(
        [{"decision_date": pd.Timestamp("2020-01-02"), "garch_params": {"AAA": params}}]
    )


def test_persistence_includes_half_gamma_for_gjr():
    rows = _param_rows(_sub({"omega": 1e-6, "alpha": 0.05, "beta": 0.88, "gamma": 0.10, "nu": 7.0}))
    assert len(rows) == 1
    r = rows[0]
    assert r["gamma"] == 0.10  # γ 帶入列（供軌跡圖）
    assert r["persistence"] == 0.05 + 0.88 + 0.5 * 0.10


def test_persistence_unchanged_for_standard_garch():
    rows = _param_rows(_sub({"omega": 1e-6, "alpha": 0.08, "beta": 0.90, "nu": 8.0}))
    r = rows[0]
    assert "gamma" not in r
    assert r["persistence"] == 0.08 + 0.90
