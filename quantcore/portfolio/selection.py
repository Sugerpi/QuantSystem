"""選擇層（規格 §1.1、§1.3、§2.1）。

Phase 2 只有 point-in-time 合格性；Phase 3 於本檔加入排序、取 K 與平手規則。

合格性放在 portfolio/ 而非 ptview：view 是機制（時間閘門），合格性是業務規則。
混在一起的話，Phase 3 的排序與 top-K 會開始往 view 塞邏輯。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView


def eligible_assets(view: PointInTimeView, menu: list[str], min_history_days: int) -> list[str]:
    """在 t 日已累積 ≥ min_history_days 個 bar 的選單資產，依字母序（決定性）。"""
    return sorted(t for t in menu if view.bar_count(t) >= min_history_days)
