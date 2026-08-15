"""AC5 匹配-turnover 配對挑選（純函數，不跑回測）。"""

from __future__ import annotations

import pandas as pd
import pytest

from quantcore.experiments.ac5_exposure_band import matched_turnover_pair


def _front() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"strategy_id": "full", "mode": "absolute", "band": 0.05, "turnover": 6.8},
            {"strategy_id": "full", "mode": "absolute", "band": 0.22, "turnover": 5.69},
            {"strategy_id": "full", "mode": "log", "band": 0.10, "turnover": 6.58},
            {"strategy_id": "full", "mode": "log", "band": 0.30, "turnover": 5.72},
        ]
    )


def test_matched_pair_picks_closest_turnover_cross_mode():
    ar, lr = matched_turnover_pair(_front(), "full")
    # 最接近的一對：absolute 0.22 (5.69) 與 log 0.30 (5.72)，差 0.03
    assert ar["mode"] == "absolute" and ar["band"] == 0.22
    assert lr["mode"] == "log" and lr["band"] == 0.30


def test_matched_pair_raises_when_a_mode_missing():
    only_abs = _front()
    only_abs = only_abs[only_abs["mode"] == "absolute"]
    with pytest.raises(ValueError):
        matched_turnover_pair(only_abs, "full")
