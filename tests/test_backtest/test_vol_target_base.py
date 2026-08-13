"""VolTargetStrategy 基底：選擇/曝險檢查流程、權重守恆、band log-only。"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategies.vol_target_base import (
    RiskyState,
    VolTargetStrategy,
    ticker_returns,
)
from quantcore.backtest.strategy import DecisionEvent
from quantcore.portfolio.exposure import target_exposure
from quantcore.portfolio.weighting import inverse_vol
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


class _FixedRisky(VolTargetStrategy):
    """測試用：固定選 A、B，σ̂ 由 forecaster（ewma）決定；absmom 可注入。"""

    strategy_id = "fixed_risky_probe"

    def __init__(self, cfg, absmom):
        super().__init__(cfg)
        self._absmom = absmom

    @property
    def warmup_days(self):
        return 2

    def _select_and_weight(self, view):
        selected = ["A", "B"]
        sigma_hat = {t: self._forecaster.refit(t, ticker_returns(view, t)) for t in selected}
        return RiskyState(
            eligible=selected,
            selected=selected,
            momentum_scores=None,
            w_risky=inverse_vol(sigma_hat),
            sigma_hat=sigma_hat,
            absmom={t: self._absmom.get(t, True) for t in selected},
            garch_params={t: self._forecaster.last_params(t) for t in selected},
            fell_back={t: self._forecaster.last_fell_back(t) for t in selected},
        )


def _snap(n=60):
    dates = make_dates(n)
    rng = np.random.default_rng(0)
    a = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    b = 100 * np.cumprod(1 + rng.normal(0, 0.02, n))
    return make_snapshot({"A": list(a), "B": list(b)}, dates), dates


def _cfg():
    return make_cfg(
        ["A", "B"],
        risk={"vol_model": "ewma", "garch_window": 100},
        signal={"top_k": 2},
    )


def test_selection_produces_valid_weights_summing_to_one():
    snap, dates = _snap()
    strat = _FixedRisky(_cfg(), absmom={"A": True, "B": True})
    dec = strat.decide(make_view(snap, dates[50]), DecisionEvent.SELECTION)
    assert dec is not None and dec.execute is True
    assert sum(dec.target_weights.values()) == pytest.approx(1.0)
    E = dec.diagnostics.exposure_applied
    assert 0.0 < E <= 1.0
    assert dec.target_weights[CASH] == pytest.approx(1.0 - E)


def test_absmom_fail_routes_to_cash():
    snap, dates = _snap()
    strat = _FixedRisky(_cfg(), absmom={"A": True, "B": False})
    dec = strat.decide(make_view(snap, dates[50]), DecisionEvent.SELECTION)
    assert dec.target_weights.get("B", 0.0) == 0.0
    assert sum(dec.target_weights.values()) == pytest.approx(1.0)


def test_exposure_check_before_selection_returns_none():
    snap, dates = _snap()
    strat = _FixedRisky(_cfg(), absmom={"A": True, "B": True})
    assert strat.decide(make_view(snap, dates[50]), DecisionEvent.EXPOSURE_CHECK) is None


def test_band_block_yields_log_only_decision():
    snap, dates = _snap()
    strat = _FixedRisky(_cfg(), absmom={"A": True, "B": True})
    strat.decide(make_view(snap, dates[50]), DecisionEvent.SELECTION)
    e0 = strat._e_current
    dec = strat.decide(make_view(snap, dates[55]), DecisionEvent.EXPOSURE_CHECK)
    if dec.diagnostics.band_blocked:
        assert dec.execute is False
        assert strat._e_current == e0


def test_full_decides_under_both_corr_models():
    # full 在 corr_model ∈ {ewma, dcc} 下皆決策成功、σ̂_p 有限>0、權重和為 1
    from quantcore.backtest.strategies.full import Full

    dates = make_dates(320)
    rng = np.random.default_rng(1)
    prices = {}
    for i, tk in enumerate(["A", "B", "C", "D"]):
        drift = 0.0003 * (i + 1)
        prices[tk] = list(100 * np.cumprod(1 + rng.normal(drift, 0.01, 320)))
    snap = make_snapshot(prices, dates)
    view = make_view(snap, dates[300])

    base_cfg = make_cfg(
        ["A", "B", "C", "D"],
        risk={"vol_model": "ewma", "garch_window": 100},
        signal={"top_k": 2, "momentum_lookback": 120, "momentum_skip": 5},
        universe={"min_history_days": 130},
    )
    for corr in ("ewma", "dcc"):
        risk = base_cfg.risk.model_copy(update={"corr_model": corr})
        cfg = base_cfg.model_copy(update={"risk": risk})
        strat = Full(cfg)
        dec = strat.decide(view, DecisionEvent.SELECTION)
        assert dec is not None
        assert dec.diagnostics.sigma_p is not None
        assert np.isfinite(dec.diagnostics.sigma_p) and dec.diagnostics.sigma_p > 0
        assert sum(dec.target_weights.values()) == pytest.approx(1.0)


def test_collect_std_residuals_names_stale_ticker():
    # 逐檔新鮮度守衛：某 selected 檔的殘差快取末日 < view.t（未於本輪 refit/filter），
    # 必須 hard raise 且訊息點名該 ticker（而非只給矩陣層級的籠統日期不符）。
    snap, dates = _snap()
    strat = _FixedRisky(_cfg(), absmom={"A": True, "B": True})
    view = make_view(snap, dates[50])
    # 先跑一次正常 SELECTION，讓 forecaster 快取兩檔的標準化殘差。
    dec = strat.decide(view, DecisionEvent.SELECTION)
    assert dec is not None

    # 直接測 _collect_std_residuals：把 B 的殘差換成截斷（stale）版本。
    fresh_b = strat._forecaster.last_standardized_residuals("B")
    stale_b = fresh_b.iloc[:-3]  # 末日往前推，模擬本輪未 refit/filter 到的舊殘差
    orig = strat._forecaster.last_standardized_residuals

    def _patched(ticker):
        return stale_b if ticker == "B" else orig(ticker)

    strat._forecaster.last_standardized_residuals = _patched

    with pytest.raises(ValueError) as excinfo:
        strat._collect_std_residuals(view, ["A", "B"])
    msg = str(excinfo.value)
    assert "B" in msg
    assert "'A'" not in msg  # A 新鮮，不應被點名為 offender


def test_exposure_check_uses_log_band_mode():
    # 接線驗證：config 的 log 模式須流進 target_exposure。
    # 以決策落盤的 σ̂_p 與 e0 獨立重算 log 帶判定，應與策略內部一致。
    snap, dates = _snap()
    cfg = make_cfg(
        ["A", "B"],
        risk={"vol_model": "ewma", "garch_window": 100, "exposure_band_mode": "log"},
        signal={"top_k": 2},
    )
    strat = _FixedRisky(cfg, absmom={"A": True, "B": True})
    strat.decide(make_view(snap, dates[50]), DecisionEvent.SELECTION)
    e0 = strat._e_current
    dec = strat.decide(make_view(snap, dates[55]), DecisionEvent.EXPOSURE_CHECK)
    expected = target_exposure(
        dec.diagnostics.sigma_p,
        cfg.risk.vol_target_annual,
        cfg.risk.exposure_min,
        cfg.risk.exposure_band,
        e0,
        "log",
    )
    assert dec.diagnostics.band_blocked == expected.band_blocked
    assert dec.diagnostics.exposure_applied == pytest.approx(expected.exposure_applied)


def test_forecast_selected_returns_sigma_params_fellback_triple():
    from quantcore.backtest.strategies.vol_target_base import forecast_selected
    from quantcore.models.volatility.forecaster import VolForecaster

    snap, dates = _snap()
    view = make_view(snap, dates[50])
    f = VolForecaster("ewma", ewma_lambda=0.94, horizon=21, garch_window=100)
    sigma_hat, garch_params, fell_back = forecast_selected(f, view, ["A", "B"])
    assert set(sigma_hat) == {"A", "B"} and all(v > 0 for v in sigma_hat.values())
    assert garch_params == {"A": None, "B": None}  # ewma → 無 GARCH 參數
    assert fell_back == {"A": False, "B": False}
