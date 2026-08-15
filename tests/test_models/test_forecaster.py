"""VolForecaster：refit/filter、窗上界、fallback、無快取退化（規格 §5.2）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantcore.models.volatility.forecaster import VolForecaster
from tests.fixtures.synthetic import make_garch_t_returns


def _returns(n=1500, seed=5):
    return make_garch_t_returns(n, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=seed)


def _garch_like_series(n=400, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    return pd.Series(rng.standard_normal(n) * 0.01, index=idx)


def test_unsupported_spec_rejected_eagerly():
    with pytest.raises(ValueError):
        VolForecaster("rolling_std", ewma_lambda=0.94, horizon=21, garch_window=100)


def test_refit_returns_reasonable_annualized_vol():
    f = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    s = f.refit("AAA", _returns())
    assert 0.01 < s < 2.0  # 合理年化波動
    assert f.last_fell_back("AAA") is False


def test_filter_matches_garch_filter_forecast():
    from quantcore.models.volatility.base import annualize_variance_path
    from quantcore.models.volatility.garch_arch import GarchArch, garch_filter_forecast

    r = _returns()
    f = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    f.refit("AAA", r)  # 快取 arch 參數
    got = f.filter("AAA", r)
    # 與直接用 fit 出的參數濾波再年化一致
    params = GarchArch().fit(r.iloc[-1000:]).arch_params
    expected = annualize_variance_path(garch_filter_forecast(params, r.iloc[-1000:], 21))
    assert got == expected


def test_window_cap_slices_tail_only():
    # 前段插極端值、後段正常：refit 應只用尾端 garch_window 根 → 等同只餵尾端
    r = _returns(n=1500, seed=7)
    r_spiked = r.copy()
    r_spiked.iloc[:500] = 5.0  # 前 500 根極端值（應被切掉）
    f_full = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=800)
    f_tail = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=800)
    s_full = f_full.refit("X", r_spiked)
    s_tail = f_tail.refit("X", r_spiked.iloc[-800:])
    assert s_full == s_tail  # 前段被切掉，兩者相同


def test_fallback_ticker_filter_reruns_ewma():
    # 造 GARCH 退化 → fell_back；filter 重跑 EWMA 不拋錯、回合理值
    from quantcore.models.volatility import base
    from quantcore.models.volatility.garch_arch import GarchArch

    r = _returns()
    f = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    orig = GarchArch._estimate

    def _boom(self, scaled):
        raise base.GarchDegenerateError("造退化")

    GarchArch._estimate = _boom
    try:
        f.refit("BBB", r)
        assert f.last_fell_back("BBB") is True
        s = f.filter("BBB", r)
        assert 0.01 < s < 2.0
    finally:
        GarchArch._estimate = orig


def test_filter_without_cache_falls_back_to_refit():
    f = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    s = f.filter("NEW", _returns())  # 從未 refit
    assert 0.01 < s < 2.0
    assert "NEW" in f._cache  # filter 已代為 refit 並快取


def test_refit_and_filter_agree_on_same_window():
    r = _returns()
    f = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    s_refit = f.refit("AAA", r)
    s_filter = f.filter("AAA", r)  # 同窗、同快取參數 → 應相同
    assert s_filter == pytest.approx(s_refit)


def test_last_params_returns_readable_dict_for_garch():
    f = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    f.refit("AAA", _returns())
    p = f.last_params("AAA")
    assert set(p) == {"omega", "alpha", "beta", "nu"}
    assert p["alpha"] + p["beta"] < 1.0  # 平穩


def test_last_params_none_for_ewma_spec():
    f = VolForecaster("ewma", ewma_lambda=0.94, horizon=21, garch_window=1000)
    f.refit("AAA", _returns())
    assert f.last_params("AAA") is None


def test_refit_caches_standardized_residuals_with_index():
    fc = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    r = _garch_like_series()
    fc.refit("SPY", r)
    resid = fc.last_standardized_residuals("SPY")
    assert isinstance(resid, pd.Series)
    assert isinstance(resid.index, pd.DatetimeIndex)
    assert np.isfinite(resid.to_numpy()).all()
    assert 0.3 < resid.std() < 3.0  # 標準化殘差量級 ~O(1)


def test_filter_updates_standardized_residuals_cache():
    fc = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    r = _garch_like_series()
    fc.refit("SPY", r)
    r2 = pd.concat([r, _garch_like_series(5, seed=2).tail(5)])
    fc.filter("SPY", r2)
    resid = fc.last_standardized_residuals("SPY")
    assert resid.index[-1] == r2.index[-1]  # filter 後殘差含最新日


def test_gjr_spec_accepted_and_last_params_has_gamma():
    r = _returns()
    f = VolForecaster("gjr_garch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    s = f.refit("AAA", r)
    assert 0.01 < s < 2.0
    assert f.last_fell_back("AAA") is False
    lp = f.last_params("AAA")
    assert lp is not None and "gamma" in lp  # GJR 診斷須含 γ
    assert {"omega", "alpha", "beta", "nu", "gamma"} <= set(lp)
    # 交叉驗證：last_params 以位置索引解 arch_params 向量，須與模型具名 .params 一致。
    # 兩條獨立解碼路徑（位置 vs 名稱），此斷言防未來 arch 參數順序變動致靜默分歧。
    from quantcore.models.volatility.garch_arch import GjrGarchArch

    named = GjrGarchArch().fit(r.iloc[-1000:]).params
    for k in ("omega", "alpha", "gamma", "beta", "nu"):
        assert lp[k] == pytest.approx(named[k]), k


def test_gjr_filter_matches_gjr_filter_forecast():
    from quantcore.models.volatility.base import annualize_variance_path
    from quantcore.models.volatility.garch_arch import GjrGarchArch, garch_filter_forecast

    r = _returns()
    f = VolForecaster("gjr_garch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    f.refit("AAA", r)
    got = f.filter("AAA", r)
    params = GjrGarchArch().fit(r.iloc[-1000:]).arch_params
    expected = annualize_variance_path(garch_filter_forecast(params, r.iloc[-1000:], 21, o=1))
    assert got == expected
