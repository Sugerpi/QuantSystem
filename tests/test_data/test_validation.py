"""§4.3 五項資料驗證。"""

import numpy as np
import pandas as pd

from quantcore.data.calendar import NyseCalendar
from quantcore.data.validation import (
    check_calendar,
    check_extreme_returns,
    check_missing_values,
    check_monotonic,
    check_total_return,
)


def _prices(ticker, dates, close, adj):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "ticker": ticker,
            "close": close,
            "adj_close": adj,
            "volume": [1e6] * len(dates),
        }
    )


def test_total_return_passes_when_consistent():
    # 除息日：adj 報酬 ≈ close 報酬 + div/prev_close
    dates = ["2020-03-19", "2020-03-20"]
    close = [100.0, 101.0]
    div = 1.0
    # adj_close 建構成滿足關係：adj_ret = close_ret + div/prev_close
    adj = [100.0, 100.0 * (1 + (101.0 / 100.0 - 1) + div / 100.0)]
    prices = _prices("SPY", dates, close, adj)
    dividends = pd.DataFrame({"date": pd.to_datetime(["2020-03-20"]), "dividend": [div]})
    res = check_total_return(prices, dividends, tol_bps=10)
    assert res.passed


def test_total_return_fails_when_dividend_ignored():
    dates = ["2020-03-19", "2020-03-20"]
    close = [100.0, 101.0]
    adj = [100.0, 101.0]  # adj 沒反映股息 → 應失敗
    prices = _prices("SPY", dates, close, adj)
    dividends = pd.DataFrame({"date": pd.to_datetime(["2020-03-20"]), "dividend": [1.0]})
    res = check_total_return(prices, dividends, tol_bps=10)
    assert not res.passed
    assert res.hard_fail


def test_extreme_returns_flagged():
    prices = _prices("XLE", ["2020-03-08", "2020-03-09"], [50.0, 35.0], [50.0, 35.0])  # -30%
    res = check_extreme_returns(prices, threshold=0.20)
    assert not res.passed
    assert len(res.report) == 1


def test_missing_values_reject_on_long_gap():
    adj = [100.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, 101.0]
    dates = pd.bdate_range("2020-01-02", periods=8)
    prices = _prices("SPY", dates, [100.0] * 8, adj)
    res = check_missing_values(prices, max_consecutive_nan=5)
    assert not res.passed
    assert res.hard_fail


def test_calendar_rejects_non_session():
    prices = _prices("SPY", ["2020-01-01"], [100.0], [100.0])  # 元旦非交易日
    res = check_calendar(prices, NyseCalendar())
    assert not res.passed


def test_monotonic_rejects_duplicate_dates():
    prices = _prices("SPY", ["2020-01-02", "2020-01-02"], [100.0, 101.0], [100.0, 101.0])
    res = check_monotonic(prices)
    assert not res.passed
