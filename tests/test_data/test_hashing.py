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


def test_hash_independent_of_column_order():
    df1 = _frame()
    df2 = df1[["ticker", "date", "adj_close"]]  # 相同資料、欄序不同
    a = canonicalize(df1, sort_cols=["ticker", "date"])
    b = canonicalize(df2, sort_cols=["ticker", "date"])
    assert canonical_hash(a) == canonical_hash(b)


def test_int_and_bool_branches_stable_and_distinct():
    base = pd.DataFrame({"k": [0, 1, 2]})
    assert canonical_hash(base) == canonical_hash(base.copy())
    as_bool = pd.DataFrame({"k": [False, True, True]})
    # int 欄與 bool 欄不應碰撞（dtype kind 已折入雜湊）
    assert canonical_hash(base) != canonical_hash(as_bool)


def test_float_nan_and_signed_zero_normalized():
    canonical = pd.DataFrame({"x": [np.nan, 0.0, 1.0]})
    computed_nan = pd.DataFrame({"x": [np.float64(0.0) / np.float64(0.0), -0.0, 1.0]})
    assert canonical_hash(canonical) == canonical_hash(computed_nan)
