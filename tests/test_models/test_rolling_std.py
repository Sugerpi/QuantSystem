"""滾動標準差波動 placeholder（Phase 3；Phase 4 由 GARCH 取代）。"""

import numpy as np
import pandas as pd
import pytest

from quantcore.models.volatility import estimate_annualized_vol
from quantcore.models.volatility.rolling_std import annualized_vol


def test_annualized_vol_matches_formula():
    s = pd.Series([100.0, 101.0, 103.0, 102.0, 105.0, 104.0])
    expected = s.pct_change().dropna().iloc[-3:].std(ddof=1) * np.sqrt(252)
    assert annualized_vol(s, window=3) == pytest.approx(expected)


def test_higher_dispersion_gives_higher_vol():
    calm = pd.Series([100.0, 100.5, 101.0, 101.5, 102.0, 102.5])
    wild = pd.Series([100.0, 110.0, 95.0, 115.0, 90.0, 120.0])
    assert annualized_vol(wild, 4) > annualized_vol(calm, 4)


def test_dispatch_rolling_std():
    s = pd.Series([100.0, 101.0, 103.0, 102.0, 105.0])
    assert estimate_annualized_vol("rolling_std", s, 3) == annualized_vol(s, 3)


def test_dispatch_unimplemented_raises():
    s = pd.Series([100.0, 101.0, 103.0])
    with pytest.raises(NotImplementedError):
        estimate_annualized_vol("garch_arch", s, 3)
