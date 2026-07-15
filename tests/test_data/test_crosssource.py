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


def _prices_close(ticker, dates, close):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "ticker": ticker,
            "close": close,
            "adj_close": close,
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


def test_arbiter_resolves_validation_outlier():
    # 與 test_clustered_discrepancy_fails 同形狀：validation 在 10/12/14 出現價格竄動。
    # 提供仲裁源（Stooq），其 close 與 primary 一致 → 每筆被標記差異都應判為
    # validation_outlier（少數服從多數），因此不計入窗口失敗計數。
    dates = pd.bdate_range("2020-01-02", periods=40)
    adj_p = list(100 + np.arange(40) * 0.5)
    adj_v = adj_p.copy()
    for i in (10, 12, 14):
        adj_v[i] = adj_v[i] * 1.02
    primary = _prices("SPY", dates, adj_p)
    validation = _prices("SPY", dates, adj_v)
    arbiter = _prices_close("SPY", dates, adj_p)
    res = cross_validate(
        primary,
        validation,
        discrepancy_bps=50,
        window_days=30,
        window_max_hits=3,
        arbiter=arbiter,
    )
    assert res.passed is True
    assert "SPY" not in res.failed_assets
    assert len(res.overrides) >= 1
    assert all(o["verdict"] == "validation_outlier" for o in res.overrides)


def test_arbiter_confirms_primary_outlier_still_fails():
    # 這次讓 PRIMARY 偏離（validation 與 arbiter 一致，都等於基準序列）→
    # 仲裁應判 primary_outlier，仍計入窗口失敗計數，資產仍應失敗。
    dates = pd.bdate_range("2020-01-02", periods=40)
    base = list(100 + np.arange(40) * 0.5)
    adj_p = base.copy()
    for i in (10, 12, 14):
        adj_p[i] = adj_p[i] * 1.02
    primary = _prices("SPY", dates, adj_p)
    validation = _prices("SPY", dates, base)
    arbiter = _prices_close("SPY", dates, base)
    res = cross_validate(
        primary,
        validation,
        discrepancy_bps=50,
        window_days=30,
        window_max_hits=3,
        arbiter=arbiter,
    )
    assert res.passed is False
    assert "SPY" in res.failed_assets
    assert len(res.overrides) >= 1
    assert all(o["verdict"] == "primary_outlier" for o in res.overrides)


def test_arbiter_none_is_backward_compatible():
    dates = pd.bdate_range("2020-01-02", periods=40)
    adj_p = list(100 + np.arange(40) * 0.5)
    adj_v = adj_p.copy()
    for i in (10, 12, 14):
        adj_v[i] = adj_v[i] * 1.02
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
    assert res.overrides == []


def test_arbiter_missing_day_is_unresolved_and_counts():
    # 仲裁源涵蓋的日期範圍與被標記的差異日不重疊 → 該筆維持 unresolved，
    # 仍計入窗口失敗計數（與無仲裁時行為一致）。
    dates = pd.bdate_range("2020-01-02", periods=40)
    adj_p = list(100 + np.arange(40) * 0.5)
    adj_v = adj_p.copy()
    for i in (10, 12, 14):
        adj_v[i] = adj_v[i] * 1.02
    primary = _prices("SPY", dates, adj_p)
    validation = _prices("SPY", dates, adj_v)
    # 仲裁源只涵蓋前 5 個交易日，與被標記日（10 附近）不重疊。
    arbiter_dates = dates[:5]
    arbiter_close = adj_p[:5]
    arbiter = _prices_close("SPY", arbiter_dates, arbiter_close)
    res = cross_validate(
        primary,
        validation,
        discrepancy_bps=50,
        window_days=30,
        window_max_hits=3,
        arbiter=arbiter,
    )
    assert res.passed is False
    assert "SPY" in res.failed_assets
    unresolved_rows = [r for r in res.report if r["verdict"] == "unresolved"]
    assert len(unresolved_rows) >= 3
    assert res.overrides == []
