"""NYSE 日曆封裝。"""

import pandas as pd

from quantcore.data.calendar import NyseCalendar


def test_known_session_and_holiday():
    cal = NyseCalendar()
    # 2020-01-02 為交易日；2020-01-01（元旦）非交易日
    assert cal.is_session(pd.Timestamp("2020-01-02"))
    assert not cal.is_session(pd.Timestamp("2020-01-01"))


def test_sessions_in_range_are_sorted_unique():
    cal = NyseCalendar()
    sessions = cal.sessions_in_range("2020-01-01", "2020-01-10")
    assert list(sessions) == sorted(sessions)
    assert len(set(sessions)) == len(sessions)
    # 2020-01-02..01-10 有 7 個交易日（01-01 假日、週末排除）
    assert len(sessions) == 7


def test_covers_snapshot_start_2005():
    # 回歸測試：快照起點 2005 早於 exchange_calendars 預設 ~20 年界，
    # 必須不拋 DateOutOfBounds（見 calendar._START_BOUND）。
    cal = NyseCalendar()
    assert cal.is_session(pd.Timestamp("2005-01-03"))  # 2005 首個交易日
    sessions = cal.sessions_in_range("2005-01-03", "2005-01-10")
    assert len(sessions) == 6  # 01-03,04,05,06,07,10（週末排除）
