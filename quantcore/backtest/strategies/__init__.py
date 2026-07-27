"""Phase 2 策略註冊表（規格 §6.3）。Phase 3-4 於此加入其餘五個策略。"""

from quantcore.backtest.strategies.bh_spy import BuyHoldSPY
from quantcore.backtest.strategies.ew_menu import EqualWeightMenu
from quantcore.backtest.strategies.full import Full
from quantcore.backtest.strategies.full_erc import FullErc
from quantcore.backtest.strategies.mom_ivol import MomentumInverseVol
from quantcore.backtest.strategies.mom_only import MomentumOnly
from quantcore.backtest.strategies.sixty_forty import SixtyForty
from quantcore.backtest.strategies.voltarget_only import VoltargetOnly

STRATEGIES = {
    BuyHoldSPY.strategy_id: BuyHoldSPY,
    EqualWeightMenu.strategy_id: EqualWeightMenu,
    Full.strategy_id: Full,
    FullErc.strategy_id: FullErc,
    SixtyForty.strategy_id: SixtyForty,
    MomentumOnly.strategy_id: MomentumOnly,
    MomentumInverseVol.strategy_id: MomentumInverseVol,
    VoltargetOnly.strategy_id: VoltargetOnly,
}

__all__ = [
    "STRATEGIES",
    "BuyHoldSPY",
    "EqualWeightMenu",
    "Full",
    "FullErc",
    "SixtyForty",
    "MomentumOnly",
    "MomentumInverseVol",
    "VoltargetOnly",
]
