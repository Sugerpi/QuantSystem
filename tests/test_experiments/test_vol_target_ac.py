"""σ*±2% AC 條件式量測：voltarget_only 全期、full 日層級閾值子集。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quantcore.experiments.vol_target_ac import (
    full_conditional_realized_vol,
    realized_annual_vol,
)


def test_realized_annual_vol_hand():
    nav = pd.Series([1.0, 1.01, 0.9999, 1.02])
    r = nav.pct_change().dropna().to_numpy()
    assert realized_annual_vol(nav) == pytest.approx(float(np.std(r, ddof=1) * np.sqrt(252)))


def _full_decisions(rows):
    recs = []
    for ed, c in rows:
        absmom = {"A": True, "B": c < 0.5}  # c=0.5 → B fail(轉現金 0.5); c=0 → 皆過
        w_risky = {"A": 0.5, "B": 0.5}
        recs.append(
            {
                "strategy_id": "full",
                "event": "selection",
                "execution_date": pd.Timestamp(ed),
                "absmom": json.dumps(absmom),
                "w_risky": json.dumps(w_risky),
            }
        )
    return pd.DataFrame(recs)


def test_full_conditional_excludes_high_cash_days():
    dec = _full_decisions([("2020-01-01", 0.0), ("2020-01-04", 0.5), ("2020-01-07", 0.0)])
    dates = pd.to_datetime([f"2020-01-0{i}" for i in range(1, 10)])
    nav = pd.Series(1.0 + 0.001 * np.arange(9), index=dates)
    res = full_conditional_realized_vol(dec, nav, threshold=0.10)
    assert res["n_included"] < res["n_total"]
    assert res["n_included"] > 0
    strict = full_conditional_realized_vol(dec, nav, threshold=0.0)
    assert strict["n_included"] <= res["n_included"]


def test_full_conditional_all_pass_includes_all():
    dec = _full_decisions([("2020-01-01", 0.0)])  # 單一 selection，absmom 全過（c=0）
    dates = pd.to_datetime([f"2020-01-0{i}" for i in range(1, 8)])
    nav = pd.Series(1.0 + 0.001 * np.arange(7), index=dates)
    res = full_conditional_realized_vol(dec, nav, threshold=0.10)
    assert res["n_included"] == res["n_total"]  # 全部報酬日納入


def test_full_conditional_days_before_first_selection_excluded():
    # 首個 selection 執行於 01-05：其前的報酬日（pos=-1）應被排除
    dec = _full_decisions([("2020-01-05", 0.0)])
    dates = pd.to_datetime([f"2020-01-0{i}" for i in range(1, 8)])
    nav = pd.Series(1.0 + 0.001 * np.arange(7), index=dates)
    res = full_conditional_realized_vol(dec, nav, threshold=0.10)
    assert 0 < res["n_included"] < res["n_total"]  # 01-05 之前的日子被排除


def test_full_conditional_fewer_than_two_included_is_nan():
    # exec 很晚 → 只 1 個報酬日納入 → realized_vol 為 nan
    dec = _full_decisions([("2020-01-07", 0.0)])
    dates = pd.to_datetime([f"2020-01-0{i}" for i in range(1, 8)])
    nav = pd.Series(1.0 + 0.001 * np.arange(7), index=dates)
    res = full_conditional_realized_vol(dec, nav, threshold=0.10)
    assert res["n_included"] < 2
    assert np.isnan(res["realized_vol"])


def test_full_conditional_threshold_boundary_inclusive():
    # 造 c == 0.10 的 selection：B 的 w_risky=0.10 且 absmom False
    dec = pd.DataFrame(
        [
            {
                "strategy_id": "full",
                "event": "selection",
                "execution_date": pd.Timestamp("2020-01-01"),
                "absmom": json.dumps({"A": True, "B": False}),
                "w_risky": json.dumps({"A": 0.90, "B": 0.10}),
            }
        ]
    )
    dates = pd.to_datetime([f"2020-01-0{i}" for i in range(1, 6)])
    nav = pd.Series(1.0 + 0.001 * np.arange(5), index=dates)
    at = full_conditional_realized_vol(dec, nav, threshold=0.10)  # c==0.10 ≤ 0.10 → 納入
    below = full_conditional_realized_vol(dec, nav, threshold=0.09)  # c==0.10 > 0.09 → 排除
    assert at["n_included"] == at["n_total"]
    assert below["n_included"] == 0


def test_measure_vol_target_ac_end_to_end(tmp_path):
    from quantcore.experiments.vol_target_ac import measure_vol_target_ac

    rng = np.random.default_rng(0)
    n = 300
    dates = pd.to_datetime(pd.date_range("2020-01-01", periods=n, freq="B"))
    # voltarget_only nav：日報酬 std ≈ 10%/√252 → 全期實現波動 ≈ 10%
    vt_ret = rng.normal(0.0, 0.10 / np.sqrt(252), n)
    vt_nav = 100 * np.cumprod(1 + vt_ret)
    full_ret = rng.normal(0.0, 0.10 / np.sqrt(252), n)
    full_nav = 100 * np.cumprod(1 + full_ret)
    nav = pd.DataFrame(
        [
            {"date": d, "strategy_id": "voltarget_only", "nav": v}
            for d, v in zip(dates, vt_nav, strict=True)
        ]
        + [
            {"date": d, "strategy_id": "full", "nav": v}
            for d, v in zip(dates, full_nav, strict=True)
        ]
    )
    nav.to_parquet(tmp_path / "nav.parquet")
    # full 決策：全過（c=0）→ full 全期納入
    dec = _full_decisions([(dates[0], 0.0)])
    dec.to_parquet(tmp_path / "decisions.parquet")

    ac = measure_vol_target_ac(tmp_path, threshold=0.10)
    assert set(ac) == {"voltarget_only", "full_threshold", "full_strict"}
    assert "passes" in ac["voltarget_only"]
    assert ac["voltarget_only"]["passes"] is True  # ≈10% 落 8-12%
    assert ac["full_threshold"]["n_included"] == ac["full_threshold"]["n_total"]  # 全過
    assert isinstance(ac["full_threshold"]["passes"], bool)
