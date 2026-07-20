"""事件時鐘（規格 §1.2、§1.7）。

決策日與執行日的**唯一**定義處——引擎不自行推算 t+1（INV-2）。
錨點：warmup 結束後的第一個交易日為第 0 天（設計文件 §2.3.1；§1.7 只給間隔未給起點）。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class EventClock:
    """交易日序列 + 再平衡時程 → 決策日／執行日。"""

    trading_days: pd.DatetimeIndex
    warmup: int
    selection_interval: int
    exposure_check_interval: int

    def __post_init__(self) -> None:
        if self.warmup < 0:
            raise ValueError(f"warmup 不可為負：{self.warmup}")
        if self.warmup >= len(self.trading_days):
            raise ValueError(f"warmup ({self.warmup}) 不可 ≥ 交易日數 ({len(self.trading_days)})")
        for name, v in (
            ("selection_interval", self.selection_interval),
            ("exposure_check_interval", self.exposure_check_interval),
        ):
            if v < 2:
                raise ValueError(f"{name} 間隔須 ≥ 2（間隔 1 會讓決策在執行前即被覆蓋）：{v}")

    @property
    def active_days(self) -> pd.DatetimeIndex:
        """實際跑回測的交易日（warmup 之後）。"""
        return self.trading_days[self.warmup :]

    def _offset(self, t: pd.Timestamp) -> int:
        """t 距錨點的交易日數。t 不在 active_days 內即為呼叫端的 bug。"""
        return int(self.active_days.get_loc(t))

    def is_selection_day(self, t: pd.Timestamp) -> bool:
        return self._offset(t) % self.selection_interval == 0

    def is_exposure_check_day(self, t: pd.Timestamp) -> bool:
        return self._offset(t) % self.exposure_check_interval == 0

    def is_decision_day(self, t: pd.Timestamp) -> bool:
        return self.is_selection_day(t) or self.is_exposure_check_day(t)

    def execution_day(self, decision_day: pd.Timestamp) -> pd.Timestamp | None:
        """決策日的下一個交易日；已無資料則回 None（INV-2 的唯一實作）。"""
        i = int(self.trading_days.get_loc(decision_day))
        if i + 1 >= len(self.trading_days):
            return None
        return self.trading_days[i + 1]
