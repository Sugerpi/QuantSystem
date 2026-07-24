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
