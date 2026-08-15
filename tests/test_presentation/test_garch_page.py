"""GARCH 頁：GJR run 顯示 γ、persistence 納入 0.5γ；純 GARCH 回歸不變。"""

from __future__ import annotations

import pandas as pd

from quantcore.presentation.web.routes.garch import _param_chart_cols, _param_rows


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


def test_chart_cols_inserts_gamma_between_alpha_and_beta_for_gjr():
    # GJR run（DataFrame 含 gamma 欄）：γ 系列插在 α 後、β 前，呼應參數向量順序。
    cols = _param_chart_cols(["omega", "alpha", "gamma", "beta", "nu", "persistence", "ticker"])
    assert cols == ["omega", "alpha", "gamma", "beta", "nu", "persistence"]


def test_chart_cols_omits_gamma_for_standard_garch():
    # 純 GARCH run（無 gamma 欄）：系列不含 γ，與 GJR 前行為一致。
    cols = _param_chart_cols(["omega", "alpha", "beta", "nu", "persistence", "ticker"])
    assert cols == ["omega", "alpha", "beta", "nu", "persistence"]
    assert "gamma" not in cols
