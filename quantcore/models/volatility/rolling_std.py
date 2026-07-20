"""滾動標準差波動估計（Phase 3 placeholder）。

規格 §1.6 Step 1 的 σ̂ 在 v1 應由 GARCH 產生；Phase 3 尚無 GARCH，暫以末 window 日
報酬的樣本標準差年化代替。Phase 4 的 models/volatility/base.py 模板會收編此估計，
並以 QLIKE/MZ-R²（§5.4）評估後由 GARCH 取代預設。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_DAYS_PER_YEAR = 252


def annualized_vol(adj_close: pd.Series, window: int) -> float:
    """末 window 日報酬的樣本標準差 × sqrt(252)。"""
    rets = adj_close.astype("float64").pct_change().dropna()
    tail = rets.iloc[-window:]
    return float(tail.std(ddof=1) * np.sqrt(_DAYS_PER_YEAR))
