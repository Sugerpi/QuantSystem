"""FRED 正規化：DTB3 原始序列 → tz-naive、依日期排序的 Series（NaN 保留，缺值處理交驗證層）。"""

import numpy as np
import pandas as pd

from quantcore.data.providers.fred_adapter import normalize_fred


def test_normalize_drops_nan_and_sorts():
    idx = pd.to_datetime(["2020-01-03", "2020-01-02"])
    raw = pd.Series([1.55, np.nan], index=idx, name="DTB3")
    out = normalize_fred(raw)
    assert out.name == "DTB3"
    assert list(out.index) == [pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-03")]
    # NaN 保留位置但排序；缺值處理交給驗證層。此處僅排序 + 命名 + tz-naive
    assert out.index.tz is None
