"""mom_ivol —— 動量 + inverse-vol（無波動目標）（規格 §6.3）。

存在理由：消融——有相對權重層但無總曝險控制（E=1）。σ̂ 由 GARCH（VolForecaster），
與 full 同估計器，使消融只差「曝險層」。無曝險檢查、不需 filter。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategies.momentum_base import MomentumStrategy
from quantcore.backtest.strategies.vol_target_base import ticker_returns
from quantcore.models.volatility.forecaster import VolForecaster
from quantcore.portfolio.weighting import inverse_vol


class MomentumInverseVol(MomentumStrategy):
    strategy_id = "mom_ivol"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self._forecaster = VolForecaster(
            cfg.risk.vol_model,
            cfg.risk.ewma_lambda,
            cfg.risk.forecast_horizon,
            cfg.risk.garch_window,
        )

    def _risky_weights(
        self, selected: list[str], view: PointInTimeView
    ) -> tuple[dict[str, float], dict[str, float]]:
        sigma_hat = {t: self._forecaster.refit(t, ticker_returns(view, t)) for t in selected}
        return inverse_vol(sigma_hat), sigma_hat

    def _vol_diagnostics(self, selected):
        return (
            {t: self._forecaster.last_params(t) for t in selected},
            {t: self._forecaster.last_fell_back(t) for t in selected},
        )
