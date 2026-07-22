"""INV-4：GARCH 數值慣例（規格 §3 INV-4）。

守護：報酬 ×100 估計 / ÷100² 還原、α+β<1（GARCH）、Student-t、EWMA 為 IGARCH 豁免。
"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.models.volatility import Ewma, GarchArch
from quantcore.models.volatility.base import GarchDegenerateError, VolatilityModel
from tests.fixtures.synthetic import make_garch_t_returns


def _series():
    return make_garch_t_returns(2000, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=21)


def test_garch_persistence_below_one():
    m = GarchArch().fit(_series())
    p = m.params
    assert p["alpha"] + p["beta"] < 1.0  # INV-4：平穩


def test_garch_uses_student_t_has_nu():
    m = GarchArch().fit(_series())
    assert "nu" in m.params
    assert m.params["nu"] > 2.0  # t 分配自由度存在且有限變異數


def test_backscaling_convention_variance_is_quadratic():
    # ×100 尺度變異數 ÷100² 還原：forecast 相對 _forecast_scaled 差 1e4 倍
    m = GarchArch().fit(_series())
    scaled = m._forecast_scaled(5)
    restored = m.forecast(5)
    assert np.allclose(restored, scaled / (100**2))


def test_ewma_is_igarch_exempt_from_stationarity():
    # EWMA α+β=1（IGARCH），不得被平穩性檢查擋下
    m = Ewma(0.94).fit(_series())
    assert m.enforce_stationarity is False
    m.forecast(21)  # 不拋 GarchDegenerateError


def test_stationarity_check_has_teeth():
    # 變異守護：若把 GARCH 的 enforce_stationarity 關掉，非平穩參數就不會被擋——
    # 這裡直接驗證 base 的檢查邏輯對 α+β≥1 會拋錯（防止 INV-4 檢查被靜默移除）。
    class _Fake(VolatilityModel):
        enforce_stationarity = True
        _min_obs = 2

        def _estimate(self, scaled_returns):
            self._s = scaled_returns

        def _forecast_scaled(self, horizon):
            return np.ones(horizon)

        @property
        def params(self):
            return {"alpha": 0.3, "beta": 0.8}  # α+β=1.1

        @property
        def standardized_residuals(self):
            return self._s

    with pytest.raises(GarchDegenerateError):
        _Fake().fit(_series())
