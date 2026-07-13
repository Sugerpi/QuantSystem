"""決定性 canonical hash（設計文件 §3.2）。"""

import numpy as np
import pandas as pd

from quantcore.data.hashing import canonical_hash, canonicalize, snapshot_id


def _frame():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-03", "2020-01-02"]),
            "ticker": ["SPY", "SPY"],
            "adj_close": [301.5, np.nan],
        }
    )


def test_hash_is_stable_across_row_order():
    a = canonicalize(_frame(), sort_cols=["ticker", "date"])
    shuffled = _frame().iloc[::-1].reset_index(drop=True)
    b = canonicalize(shuffled, sort_cols=["ticker", "date"])
    assert canonical_hash(a) == canonical_hash(b)


def test_hash_changes_on_value_change():
    a = canonicalize(_frame(), sort_cols=["ticker", "date"])
    df2 = _frame()
    df2.loc[0, "adj_close"] = 999.0
    b = canonicalize(df2, sort_cols=["ticker", "date"])
    assert canonical_hash(a) != canonical_hash(b)


def test_nan_is_deterministic():
    a = canonicalize(_frame(), sort_cols=["ticker", "date"])
    b = canonicalize(_frame(), sort_cols=["ticker", "date"])
    assert canonical_hash(a) == canonical_hash(b)


def test_snapshot_id_format():
    sid = snapshot_id(pd.Timestamp("2026-07-13"), "deadbeefcafe")
    assert sid == "2026-07-13_deadbe"
