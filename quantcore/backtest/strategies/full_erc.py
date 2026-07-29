"""full_erc —— 與 full 同層（動量+absmom+波動目標），權重改用 ERC（等風險貢獻，§1.6/§5.3）。

與 full apples-to-apples：同選股/σ̂/相關/曝險，只差 w_risky（ERC 用完整 Σ，inverse-vol 只用 σ̂）。
需 cov-first（ERC 吃 Σ），故走自有 decide()
（不呼叫 base 的 inverse_vol decide()，避免 corr double-refit）。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategies.momentum_selection import momentum_select
from quantcore.backtest.strategies.vol_target_base import (
    RiskyState,
    VolTargetStrategy,
    forecast_selected,
)
from quantcore.backtest.strategy import Decision, DecisionEvent
from quantcore.portfolio.weighting import erc_weights


class FullErc(VolTargetStrategy):
    strategy_id = "full_erc"

    @property
    def warmup_days(self) -> int:
        return max(self._cfg.signal.momentum_lookback + 1, self._cfg.universe.min_history_days)

    def _select_and_weight(self, view: PointInTimeView) -> RiskyState | None:
        raise NotImplementedError(
            "FullErc 用自有 decide()（cov-first ERC）；不走 base 的 _select_and_weight"
        )

    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        if event is DecisionEvent.SELECTION:
            sel = momentum_select(view, self._cfg)
            if sel is None:
                return None
            sigma_hat, garch_params, fell_back = forecast_selected(
                self._forecaster, view, sel.selected
            )
            cov, R = self._build_cov(view, sel.selected, sigma_hat, event)
            w_risky = erc_weights(cov)  # ← 與 full 唯一差異（full 用 inverse_vol(sigma_hat)）
            state = RiskyState(
                eligible=sel.eligible,
                selected=sel.selected,
                momentum_scores=sel.scores,
                w_risky=w_risky,
                sigma_hat=sigma_hat,
                absmom=sel.absmom,
                garch_params=garch_params,
                fell_back=fell_back,
            )
            self._cache = state
            e_current = None
        else:  # EXPOSURE_CHECK
            if self._cache is None:
                return None
            assert self._e_current is not None
            state = self._refilter(view, self._cache)  # 更新 σ̂，沿用快取 ERC 權重
            cov, R = self._build_cov(view, state.selected, state.sigma_hat, event)
            e_current = self._e_current
        return self._exposure_decision(state, cov, R, e_current)
