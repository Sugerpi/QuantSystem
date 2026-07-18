"""PointInTimeView：結構性防 look-ahead（規格 §1.2、INV-1）。

**只做時間閘門**——不懂合格性、不懂動量。業務規則屬 portfolio/（§2.1）。

關鍵設計：建構時即實體切片 ≤ t 並凍結，物件內物理上不存在未來資料。
這使 INV-1 可斷言「view 裡沒有未來」這個結構事實，而非斷言「呼叫者沒作弊」。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class PointInTimeView:
    """close(t) 之後可見的全部資料。"""

    t: pd.Timestamp
    prices: pd.DataFrame
    rates: pd.DataFrame

    def bar_count(self, ticker: str) -> int:
        """該檔在 ≤ t 的 bar 數（合格性判定的原料）。"""
        return int((self.prices["ticker"] == ticker).sum())

    def history(self, ticker: str) -> pd.DataFrame:
        """該檔 ≤ t 的完整歷史，依日期排序。"""
        h = self.prices[self.prices["ticker"] == ticker]
        return h.sort_values("date").reset_index(drop=True)

    def last_adj_close(self, ticker: str) -> float:
        h = self.history(ticker)
        if h.empty:
            raise KeyError(f"{ticker} 在 {self.t:%Y-%m-%d} 無資料")
        return float(h["adj_close"].iloc[-1])


def make_view(snapshot: dict, t: pd.Timestamp) -> PointInTimeView:
    """由快照與決策日建構 view。切片為副本——來源之後被竄改也不影響已建的 view。"""
    t = pd.Timestamp(t)
    p, r = snapshot["prices"], snapshot["rates"]
    return PointInTimeView(
        t=t,
        prices=p.loc[p["date"] <= t].reset_index(drop=True),
        rates=r.loc[r["date"] <= t].reset_index(drop=True),
    )
