"""GARCH(1,1)-t：生成器自檢（Task 5）、估計器回收與多步（Task 6）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantcore.models.volatility.base import GarchDegenerateError
from quantcore.models.volatility.garch_arch import GarchArch
from tests.fixtures.synthetic import make_garch_t_returns


def test_generator_is_deterministic_and_stationary():
    a = make_garch_t_returns(1000, omega=1e-6, alpha=0.1, beta=0.85, nu=7, seed=42)
    b = make_garch_t_returns(1000, omega=1e-6, alpha=0.1, beta=0.85, nu=7, seed=42)
    assert np.allclose(a.to_numpy(), b.to_numpy())  # 同 seed 決定性
    assert len(a) == 1000
    assert np.all(np.isfinite(a.to_numpy()))
    # 樣本波動叢聚：|r| 的一階自相關為正（GARCH 特徵）
    absr = np.abs(a.to_numpy())
    ac1 = np.corrcoef(absr[:-1], absr[1:])[0, 1]
    assert ac1 > 0.05


def test_recovers_known_parameters():
    # 以 scale-invariant 參數（α,β,ν）為回收標的；ω 隨尺度變，不強比。
    r = make_garch_t_returns(4000, omega=1e-6, alpha=0.10, beta=0.85, nu=7, seed=7)
    m = GarchArch().fit(r)
    p = m.params
    # 估回真值附近（非落邊界）。容差對 N=4000 固定 seed 之單次抽樣校準，
    # 若略偏可微調，但須保持「近真值」而非放寬到無意義。
    assert 0.04 < p["alpha"] < 0.18
    assert 0.75 < p["beta"] < 0.93
    assert p["alpha"] + p["beta"] < 1.0
    assert p["nu"] > 3.0


def test_multistep_follows_analytic_recursion():
    r = make_garch_t_returns(2000, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=3)
    m = GarchArch().fit(r)
    # 取 ×100 尺度的每步變異數（子類原始輸出），驗證解析遞迴關係
    scaled = m._forecast_scaled(10)
    p = m.params
    persistence = p["alpha"] + p["beta"]
    for h in range(1, 10):
        assert np.isclose(scaled[h], p["omega"] + persistence * scaled[h - 1], rtol=1e-6)


def test_forecast_backscaled_reasonable_annualized_vol():
    r = make_garch_t_returns(2000, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=3)
    m = GarchArch().fit(r)
    per_step_var = m.forecast(21)  # 已還原
    ann_vol = float(np.sqrt(per_step_var.mean()) * np.sqrt(252))
    assert 0.01 < ann_vol < 2.0  # 合理年化波動區間（非退化）


def test_nonstationary_series_raises_or_falls_within_bounds():
    # 近單位根 / 極端序列易使 arch 估出 α+β≥1，應由 base 擋為 GarchDegenerateError。
    rng = np.random.default_rng(9)
    shocks = rng.normal(0, 1, 400).cumsum()
    series = pd.Series(np.diff(shocks, prepend=0.0) * 0.05)
    try:
        m = GarchArch().fit(series)
        assert m.params["alpha"] + m.params["beta"] < 1.0  # 若收斂，必平穩
    except GarchDegenerateError:
        pass  # 非平穩被正確擋下，即符合預期


def test_standardized_residuals_unit_scale_and_index_preserved():
    r = make_garch_t_returns(1500, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=4)
    m = GarchArch().fit(r)
    z = m.standardized_residuals
    assert 0.7 < float(z.std()) < 1.4  # 單位尺度
    assert z.index.equals(r.index)  # 保留 DatetimeIndex，供 DCC 對齊
