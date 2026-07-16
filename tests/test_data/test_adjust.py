"""決定性含息調整（back-adjust）測試（規格 §4.5 / AC-4，取代 yfinance 抖動 adj）。"""

import pandas as pd
import pytest

from quantcore.data.adjust import adjusted_close


def test_no_actions_returns_close():
    dates = pd.bdate_range("2024-01-02", periods=4)
    close = pd.Series([100.0, 101.0, 102.0, 103.0], index=dates)
    dividends = pd.Series([], dtype=float)
    splits = pd.Series([], dtype=float)

    adj = adjusted_close(close, dividends, splits)

    pd.testing.assert_series_equal(adj, close, check_dtype=False)
    assert adj.dtype == "float64"


def test_single_dividend():
    dates = pd.bdate_range("2024-01-02", periods=4)
    close = pd.Series([100.0, 101.0, 102.0, 103.0], index=dates)
    # 除息日為第 3 個日期（index 2），股息 1.0，c_prev = close[index1] = 101
    dividends = pd.Series([1.0], index=[dates[2]])
    splits = pd.Series([], dtype=float)

    adj = adjusted_close(close, dividends, splits)

    factor = 1.0 - 1.0 / 101.0
    assert adj.iloc[3] == 103.0
    assert adj.iloc[2] == 102.0
    assert adj.iloc[1] == pytest.approx(101.0 * factor)
    assert adj.iloc[0] == pytest.approx(100.0 * factor)

    # total-return 性質：調整後 index1->index2 報酬 = (102 / (101*f)) - 1 = 102/100 - 1 = 0.02
    # 註：規格文字中「raw_close_return + 1.0/101」一句與其自身給出的具體算式
    # （102/100 - 1 = 0.02）在數學上不一致（raw_close_return + 1/101 = 2/101 ≈
    # 0.019802 ≠ 0.02）；本測試以規格給出的具體數值（back-adjust 演算法的
    # 實際定義）為準。
    adjusted_return = (102.0 / (101.0 * factor)) - 1.0
    assert adjusted_return == pytest.approx(0.02)


def test_single_split():
    dates = pd.bdate_range("2024-01-02", periods=3)
    close = pd.Series([50.0, 25.0, 26.0], index=dates)
    # 2:1 拆分發生於 index1
    dividends = pd.Series([], dtype=float)
    splits = pd.Series([2.0], index=[dates[1]])

    adj = adjusted_close(close, dividends, splits)

    assert adj.iloc[0] == pytest.approx(25.0)
    assert adj.iloc[1] == pytest.approx(25.0)
    assert adj.iloc[2] == pytest.approx(26.0)

    # 拆分artifact 已消除：調整後 index0->index1 報酬應為 0
    adjusted_return = (adj.iloc[1] / adj.iloc[0]) - 1.0
    assert adjusted_return == pytest.approx(0.0)


def test_event_before_range_ignored():
    dates = pd.bdate_range("2024-01-02", periods=4)
    close = pd.Series([100.0, 101.0, 102.0, 103.0], index=dates)
    # 股息日期早於第一個 close 日期 -> snap 到第一個日期 -> 因無前一天而跳過
    early_date = dates[0] - pd.Timedelta(days=5)
    dividends = pd.Series([1.0], index=[early_date])
    splits = pd.Series([], dtype=float)

    adj = adjusted_close(close, dividends, splits)

    pd.testing.assert_series_equal(adj, close, check_dtype=False)


def test_anchor_latest_equals_close():
    dates = pd.bdate_range("2024-01-02", periods=5)
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0], index=dates)
    dividends = pd.Series([0.5], index=[dates[2]])
    splits = pd.Series([], dtype=float)

    adj = adjusted_close(close, dividends, splits)

    assert adj.iloc[-1] == close.iloc[-1]


def test_does_not_mutate_inputs():
    dates = pd.bdate_range("2024-01-02", periods=4)
    close = pd.Series([100.0, 101.0, 102.0, 103.0], index=dates)
    dividends = pd.Series([1.0], index=[dates[2]])
    splits = pd.Series([2.0], index=[dates[1]])

    close_copy = close.copy()
    dividends_copy = dividends.copy()
    splits_copy = splits.copy()

    adjusted_close(close, dividends, splits)

    pd.testing.assert_series_equal(close, close_copy)
    pd.testing.assert_series_equal(dividends, dividends_copy)
    pd.testing.assert_series_equal(splits, splits_copy)
