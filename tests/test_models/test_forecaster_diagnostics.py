"""forecaster 診斷 accessor（Phase 7a 落盤 model_details 用）。"""

import numpy as np
import pandas as pd

from quantcore.models.correlation.forecaster import CorrelationForecaster


def _resid(n=400, k=3, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame(rng.standard_normal((n, k)), index=idx, columns=["A", "B", "C"])


def test_last_fell_back_none_before_refit_and_for_ewma():
    ew = CorrelationForecaster("ewma", 0.94, 0, (0.02, 0.97), 21, 0.0)
    assert ew.last_fell_back() is None  # ewma 無 fallback 概念
    ew.refit(_resid())
    assert ew.last_fell_back() is None


def test_last_fell_back_is_bool_after_dcc_refit():
    dcc = CorrelationForecaster("dcc", 0.94, 63, (0.02, 0.97), 21, 0.0)
    dcc.refit(_resid())
    assert isinstance(dcc.last_fell_back(), bool)


def test_all_standardized_residuals_returns_every_fit_ticker():
    from quantcore.models.volatility.forecaster import VolForecaster

    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2019-01-01", periods=500)
    f = VolForecaster("ewma", 0.94, 21, 1000)
    for t in ("A", "B"):
        r = pd.Series(rng.normal(0, 0.01, 500), index=idx)
        f.refit(t, r)
    allr = f.all_standardized_residuals()
    assert set(allr) == {"A", "B"}
    assert isinstance(allr["A"], pd.Series)
    # 回傳是拷貝，改它不影響內部快取
    allr.pop("A")
    assert set(f.all_standardized_residuals()) == {"A", "B"}
