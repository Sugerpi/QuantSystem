"""mom_ivol —— 動量 + inverse-vol（無波動目標）（規格 §6.3）。

存在理由：消融——有相對權重層但無總曝險控制（E=1）。
σ̂ 由 config 的 vol_model 決定，Phase 3 為 rolling_std。vol_window ≤ momentum_lookback
的約束（schema）確保每個入選資產都算得出波動窗。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategies.momentum_base import MomentumStrategy
from quantcore.models.volatility import estimate_annualized_vol
from quantcore.portfolio.weighting import inverse_vol


class MomentumInverseVol(MomentumStrategy):
    strategy_id = "mom_ivol"

    def _risky_weights(
        self, selected: list[str], view: PointInTimeView
    ) -> tuple[dict[str, float], dict[str, float]]:
        model = self._cfg.risk.vol_model
        window = self._cfg.risk.vol_window
        sigma_hat = {
            ticker: estimate_annualized_vol(model, view.history(ticker)["adj_close"], window)
            for ticker in selected
        }
        return inverse_vol(sigma_hat), sigma_hat
