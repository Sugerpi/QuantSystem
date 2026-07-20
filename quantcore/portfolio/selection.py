"""選擇層（規格 §1.1、§1.3、§2.1）。

Phase 2 只有 point-in-time 合格性；Phase 3 於本檔加入排序、取 K 與平手規則。

合格性放在 portfolio/ 而非 ptview：view 是機制（時間閘門），合格性是業務規則。
本函式收「已切片的價格表」而非 PointInTimeView——portfolio 為 backtest 的下游層，
不得反向依賴 backtest 的型別（CLAUDE.md 依賴方向：portfolio ← backtest）。
呼叫端（backtest 層的策略）持有 view，把 view.prices 傳入。
"""

from __future__ import annotations

import pandas as pd


def eligible_assets(prices: pd.DataFrame, menu: list[str], min_history_days: int) -> list[str]:
    """在 t 日已累積 ≥ min_history_days 個 bar 的選單資產，依字母序（決定性）。

    prices 為 point-in-time 切片（≤ t）的價格表，須含 'ticker' 欄。
    """
    counts = prices["ticker"].value_counts()
    return sorted(t for t in menu if int(counts.get(t, 0)) >= min_history_days)


def select_top_k(momentum_scores: dict[str, float], k: int) -> list[str]:
    """依分數降序取前 K；平手以 ticker 字母序（決定性，§1.3）。

    前置條件：分數須為有限值。NaN 會使排序次序未定義（違反 INV-6），
    呼叫端（策略）只應傳入算得出動量的資產分數。
    """
    ranked = sorted(momentum_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [ticker for ticker, _ in ranked[:k]]
