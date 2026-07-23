"""VolForecaster：refit/filter、窗上界、fallback、無快取退化（規格 §5.2）。"""

from __future__ import annotations

from quantcore.models.volatility.forecaster import VolForecaster
from tests.fixtures.synthetic import make_garch_t_returns


def _returns(n=1500, seed=5):
    return make_garch_t_returns(n, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=seed)


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
