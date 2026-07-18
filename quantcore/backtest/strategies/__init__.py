"""Phase 2 策略註冊表（規格 §6.3）。Phase 3-4 於此加入其餘五個策略。"""

from quantcore.backtest.strategies.bh_spy import BuyHoldSPY
from quantcore.backtest.strategies.ew_menu import EqualWeightMenu

STRATEGIES = {
    BuyHoldSPY.strategy_id: BuyHoldSPY,
    EqualWeightMenu.strategy_id: EqualWeightMenu,
}

__all__ = ["STRATEGIES", "BuyHoldSPY", "EqualWeightMenu"]
