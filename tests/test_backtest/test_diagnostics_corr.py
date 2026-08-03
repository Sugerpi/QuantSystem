"""Diagnostics 帶相關矩陣 + corr_fell_back（決策當下記錄，§6.2）。"""

import pandas as pd

from quantcore.backtest.strategies.full import Full
from quantcore.backtest.strategies.vol_target_base import RiskyState
from quantcore.config import load_config
from quantcore.models.covariance import build_covariance


def _cfg():
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.risk.corr_model = "ewma"  # 預設；ewma 無 fallback → corr_fell_back None
    return cfg


def test_exposure_decision_carries_corr_matrix_and_fell_back():
    strat = Full(_cfg())
    selected = ["SPY", "QQQ"]
    state = RiskyState(
        eligible=selected,
        selected=selected,
        momentum_scores=None,
        w_risky={"SPY": 0.5, "QQQ": 0.5},
        sigma_hat={"SPY": 0.20, "QQQ": 0.25},
        absmom={"SPY": True, "QQQ": True},
        garch_params={"SPY": None, "QQQ": None},
        fell_back={"SPY": False, "QQQ": False},
    )
    R = pd.DataFrame([[1.0, 0.3], [0.3, 1.0]], index=selected, columns=selected)
    cov = build_covariance(state.sigma_hat, R)

    dec = strat._exposure_decision(state, cov, R, None)

    assert dec.diagnostics.corr_matrix is R
    assert dec.diagnostics.corr_fell_back is None  # ewma、且未 refit
