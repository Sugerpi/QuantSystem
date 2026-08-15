"""full_gjr —— full 策略但波動引擎改用 GJR-GARCH（非對稱項 γ）。

除 vol 引擎外，選股/inverse-vol/absmom/波動目標曝險全繼承 Full。內部強制
gjr_garch spec（不依賴 config.vol_model），使 full vs full_gjr 可同 suite 對比。
Step 2（σ̂_i→inverse-vol）與 Step 3（σ̂_p→曝險）共用此 forecaster，同時改用新變異數。
"""

from __future__ import annotations

from quantcore.backtest.strategies.full import Full
from quantcore.config import QuantConfig
from quantcore.models.volatility.forecaster import VolForecaster


class FullGjr(Full):
    strategy_id = "full_gjr"

    def __init__(self, cfg: QuantConfig) -> None:
        super().__init__(cfg)
        self._forecaster = VolForecaster(
            "gjr_garch",
            cfg.risk.ewma_lambda,
            cfg.risk.forecast_horizon,
            cfg.risk.garch_window,
        )
