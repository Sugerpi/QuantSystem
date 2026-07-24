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


def test_forward_and_back_scaling_round_trip_to_return_scale():
    # INV-4 前向 ×100 估計與後向 ÷100² 還原必須抵消回「原始報酬」尺度。
    # 這是有牙齒的守護：若移除前向 ×100，_estimate 會吃到原始小報酬、
    # forecast 將偏離原始尺度約 1e4 倍；若移除後向 ÷100²，則偏大 1e4 倍。
    # （前一版斷言 forecast==_forecast_scaled/100² 是 base.forecast 的實作恆等式，無守護力。）
    r = _series()
    sample_var = float(r.var(ddof=1))
    fc = GarchArch().fit(r).forecast(21)
    assert np.all(np.isfinite(fc))
    assert 0.1 * sample_var < float(fc.mean()) < 10.0 * sample_var


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
