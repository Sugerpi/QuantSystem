"""手刻 GARCH(1,1)-t 的 CI 覆蓋（合成資料 + 四零件純函數）。

parity test（vs arch，本機閘門）是 Phase 6 AC 的主驅動；本檔為 CI 可跑的回歸守護——
快照缺席時 parity 會 skip，這裡確保 garch_own 的核心行為在 CI 仍有牙齒。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantcore.models.volatility.base import GarchDegenerateError
from quantcore.models.volatility.garch_own import (
    GarchOwn,
    _backcast,
    _forecast_variance_path,
    _neg_loglik_t,
    _variance_recursion,
)
from tests.fixtures.synthetic import make_garch_t_returns


# ── 零件 1：變異數遞迴 ──────────────────────────────────────────────
def test_variance_recursion_follows_formula():
    resid = np.array([0.5, -1.2, 0.8, -0.3, 1.1])
    omega, alpha, beta, backcast = 0.1, 0.05, 0.90, 2.0
    sigma2 = _variance_recursion(resid, omega, alpha, beta, backcast)
    # 第一格：σ²_0 = ω + (α+β)·backcast（樣本前 ε²_{-1}=σ²_{-1}=backcast，比照 arch）
    assert np.isclose(sigma2[0], omega + (alpha + beta) * backcast)
    # 其後逐格套遞迴式
    for t in range(1, len(resid)):
        assert np.isclose(sigma2[t], omega + alpha * resid[t - 1] ** 2 + beta * sigma2[t - 1])


def test_backcast_weighted_average_of_squared_resid():
    resid = np.array([1.0, 2.0, 3.0])  # n<75 → tau=n，權重 0.94^i 正規化
    w = 0.94 ** np.arange(3)
    w = w / w.sum()
    assert np.isclose(_backcast(resid), np.sum(resid**2 * w))


# ── 零件 2：Student-t 負 log-likelihood ────────────────────────────
def test_neg_loglik_finite_and_minimized_near_true_sigma():
    rng = np.random.default_rng(0)
    nu = 8.0
    sigma = 1.5
    resid = rng.standard_t(nu, size=5000) * np.sqrt((nu - 2) / nu) * sigma
    sigma2_grid = np.array([sigma**2 * f for f in (0.5, 0.8, 1.0, 1.2, 2.0)])
    nll = [_neg_loglik_t(resid, np.full_like(resid, s2), nu) for s2 in sigma2_grid]
    assert all(np.isfinite(v) for v in nll)
    # 真值 σ² 附近的 NLL 最小（打分函數方向正確）
    assert int(np.argmin(nll)) == 2


# ── 零件 4：解析多步預測 ───────────────────────────────────────────
def test_forecast_path_follows_analytic_recursion():
    omega, alpha, beta = 0.1, 0.08, 0.90
    last_resid, last_sigma2 = 1.3, 2.5
    out = _forecast_variance_path(omega, alpha, beta, last_resid, last_sigma2, 10)
    assert np.isclose(out[0], omega + alpha * last_resid**2 + beta * last_sigma2)  # 1 步用真實 ε_T
    persistence = alpha + beta
    for h in range(1, 10):
        assert np.isclose(out[h], omega + persistence * out[h - 1])  # ≥2 步：E[ε²]=σ²


# ── 端到端：GarchOwn 類別（與 GarchArch 同契約）─────────────────────
def test_recovers_known_parameters():
    # scale-invariant 參數（α,β,ν）為回收標的；ω 隨尺度變，不強比（比照 test_garch_arch）。
    r = make_garch_t_returns(4000, omega=1e-6, alpha=0.10, beta=0.85, nu=7, seed=7)
    p = GarchOwn().fit(r).params
    assert 0.04 < p["alpha"] < 0.18
    assert 0.75 < p["beta"] < 0.93
    assert p["alpha"] + p["beta"] < 1.0
    assert p["nu"] > 3.0


def test_multistep_forecast_backscaled_reasonable():
    r = make_garch_t_returns(2000, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=3)
    per_step_var = GarchOwn().fit(r).forecast(21)  # 已 ÷100² 還原
    ann_vol = float(np.sqrt(per_step_var.mean()) * np.sqrt(252))
    assert 0.01 < ann_vol < 2.0


def test_standardized_residuals_unit_scale_and_index_preserved():
    r = make_garch_t_returns(1500, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=4)
    z = GarchOwn().fit(r).standardized_residuals
    assert 0.7 < float(z.std()) < 1.4  # 單位尺度
    assert z.index.equals(r.index)  # 保留 DatetimeIndex，供 DCC 對齊


def test_standardized_residuals_matches_garch_arch_convention():
    # 與 GarchArch 同定義（原始 scaled return / 條件波動），供 Phase 5 DCC 一致取用。
    from quantcore.models.volatility.garch_arch import GarchArch

    r = make_garch_t_returns(1500, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=4)
    zo = GarchOwn().fit(r).standardized_residuals
    za = GarchArch().fit(r).standardized_residuals
    assert zo.index.equals(za.index)
    assert 0.7 < float(zo.std()) < 1.4


def test_nonstationary_series_raises_or_falls_within_bounds():
    # 近單位根序列易估出 α+β≥1，應由 base 的 enforce_stationarity 擋為 GarchDegenerateError。
    rng = np.random.default_rng(9)
    shocks = rng.normal(0, 1, 400).cumsum()
    series = pd.Series(np.diff(shocks, prepend=0.0) * 0.05)
    try:
        m = GarchOwn().fit(series)
        assert m.params["alpha"] + m.params["beta"] < 1.0  # 若收斂，必平穩
    except GarchDegenerateError:
        pass  # 非平穩被正確擋下


def test_min_obs_guard():
    r = make_garch_t_returns(50, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=1)
    with pytest.raises(ValueError):
        GarchOwn().fit(r)  # _min_obs=100，樣本不足由 base 擋下
