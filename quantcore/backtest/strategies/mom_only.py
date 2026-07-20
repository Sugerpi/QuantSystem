"""mom_only —— 動量選 K + 等權 + 絕對動量（規格 §6.3）。

存在理由：消融——只有選擇層，無 inverse-vol、無波動目標。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategies.momentum_base import MomentumStrategy
from quantcore.portfolio.weighting import equal_weight


class MomentumOnly(MomentumStrategy):
    strategy_id = "mom_only"

    def _risky_weights(
        self, selected: list[str], view: PointInTimeView
    ) -> tuple[dict[str, float], None]:
        return equal_weight(selected), None
