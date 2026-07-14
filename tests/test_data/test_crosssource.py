"""§4.5 跨源日報酬比對（v1：yfinance vs Tiingo）。"""

import numpy as np
import pandas as pd

from quantcore.data.crosssource import cross_validate


def _prices(ticker, dates, adj):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "ticker": ticker,
            "close": adj,
            "adj_close": adj,
            "volume": [1e6] * len(dates),
        }
    )


def test_identical_sources_pass():
    dates = pd.bdate_range("2020-01-02", periods=40)
    adj = list(100 + np.arange(40) * 0.5)
    primary = _prices("SPY", dates, adj)
    validation = _prices("SPY", dates, adj)
    res = cross_validate(primary, validation, discrepancy_bps=50, window_days=30, window_max_hits=3)
    assert res.passed
    assert len(res.report) == 0


def test_isolated_discrepancy_passes_but_reported():
    dates = pd.bdate_range("2020-01-02", periods=40)
    adj_p = list(100 + np.arange(40) * 0.5)
    adj_v = adj_p.copy()
    adj_v[10] = adj_v[10] * 1.02  # 單一日 ~2% 差異（孤立）
    primary = _prices("SPY", dates, adj_p)
    validation = _prices("SPY", dates, adj_v)
    res = cross_validate(primary, validation, discrepancy_bps=50, window_days=30, window_max_hits=3)
    assert res.passed  # 孤立差異放行
    assert len(res.report) >= 1  # 但仍入報告


def test_clustered_discrepancy_fails():
    dates = pd.bdate_range("2020-01-02", periods=40)
    adj_p = list(100 + np.arange(40) * 0.5)
    adj_v = adj_p.copy()
    for i in (10, 12, 14):  # 30 日窗內 3 筆 → 失敗
        adj_v[i] = adj_v[i] * 1.02
    primary = _prices("SPY", dates, adj_p)
    validation = _prices("SPY", dates, adj_v)
    res = cross_validate(primary, validation, discrepancy_bps=50, window_days=30, window_max_hits=3)
    assert not res.passed
    assert "SPY" in res.failed_assets


def test_trading_day_window_catches_spread_cluster():
    # 3 筆孤立差異落在 30 交易日內、但跨越 >30 日曆日；交易日窗應判定失敗
    dates = pd.bdate_range("2020-01-02", periods=45)
    adj_p = list(100 + np.arange(45) * 0.5)
    adj_v = adj_p.copy()
    # index 3/17/31 各做一次階梯位移（每次僅產生單日報酬差異，無反轉）
    for k in (3, 17, 31):
        for j in range(k, 45):
            adj_v[j] += 1.0
    primary = _prices("SPY", dates, adj_p)
    validation = _prices("SPY", dates, adj_v)
    res = cross_validate(
        primary,
        validation,
        discrepancy_bps=50,
        window_days=30,
        window_max_hits=3,
    )
    assert not res.passed
    assert "SPY" in res.failed_assets
