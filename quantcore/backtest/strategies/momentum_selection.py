"""共用選標的序列（規格 §1.3/§1.4/§6.2）。full/mom_only/mom_ivol 的唯一實作。

抽出前為 MomentumStrategy.decide 與 Full._select_and_weight 兩份逐字複本；
消融是 Phase 4 的科學交付物，選擇一致性應由結構保證（apples-to-apples）。
"""

from __future__ import annotations

from dataclasses import dataclass

from quantcore.backtest.ptview import PointInTimeView
from quantcore.config import QuantConfig
from quantcore.portfolio.selection import eligible_assets, select_top_k
from quantcore.signals.momentum import absolute_momentum, cross_sectional_momentum


@dataclass(frozen=True)
class MomentumSelection:
    eligible: list[str]
    scores: dict[str, float]  # 全體合格資產的 12-1 分數（不只前 K）
    selected: list[str]
    absmom: dict[str, bool]  # 入選資產的絕對動量 pass/fail


def momentum_select(view: PointInTimeView, cfg: QuantConfig) -> MomentumSelection | None:
    """eligible→動量→取 K→absmom。無合格資產回 None。"""
    elig = eligible_assets(view.prices, cfg.universe.menu, cfg.universe.min_history_days)
    scores = cross_sectional_momentum(
        view.prices, cfg.signal.momentum_lookback, cfg.signal.momentum_skip
    )
    scores = {t: v for t, v in scores.items() if t in elig}
    if not scores:
        return None
    selected = select_top_k(scores, cfg.signal.top_k)
    absmom_all = absolute_momentum(view.prices, view.rates, cfg.signal.momentum_lookback)
    absmom = {t: bool(absmom_all.get(t, False)) for t in selected}
    return MomentumSelection(eligible=elig, scores=scores, selected=selected, absmom=absmom)
