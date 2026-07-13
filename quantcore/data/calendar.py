"""NYSE 交易日曆封裝（規格 §4.3-4/5，套件 exchange_calendars XNYS）。"""

from __future__ import annotations

import exchange_calendars as xcals
import pandas as pd


class NyseCalendar:
    """XNYS 交易日曆的薄封裝，對外只暴露本專案需要的查詢。"""

    def __init__(self) -> None:
        self._cal = xcals.get_calendar("XNYS")

    def is_session(self, day: pd.Timestamp) -> bool:
        return self._cal.is_session(pd.Timestamp(day).normalize())

    def sessions_in_range(self, start, end) -> pd.DatetimeIndex:
        sessions = self._cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
        # 回傳 tz-naive、normalize 到午夜的 DatetimeIndex。
        # 注意：不同版本的 exchange_calendars 對 tz-awareness 的處理不一致，
        # 已安裝版本（4.13.2）回傳 tz-naive DatetimeIndex，直接呼叫
        # tz_localize(None) 會拋出 TypeError: Already tz-naive，故僅在
        # 確實帶時區時才做轉換。
        idx = pd.DatetimeIndex(sessions)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        return idx.normalize()
