"""動量策略共用基底（DRY：mom_only 與 mom_ivol 只差相對權重演算法）。

組合根：策略層在依賴鏈下游，串起 signals → portfolio → models。
"""

from __future__ import annotations

from abc import abstractmethod

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.portfolio.selection import eligible_assets, select_top_k
from quantcore.portfolio.weighting import route_absmom_to_cash
from quantcore.signals.momentum import absolute_momentum, cross_sectional_momentum


class MomentumStrategy(Strategy):
    """選標的 + 絕對動量 + 相對權重。子類實作 _risky_weights。"""

    @property
    def warmup_days(self) -> int:
        # momentum 需 lookback+1 根 bar 才算得出 t-lookback
        return self._cfg.signal.momentum_lookback + 1

    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        if event is not DecisionEvent.SELECTION:
            return None
        cfg = self._cfg
        # 此選標的序列與 Full._select_and_weight 相同（見該處註解）；改動須同步兩處。
        elig = eligible_assets(view.prices, cfg.universe.menu, cfg.universe.min_history_days)
        scores = cross_sectional_momentum(
            view.prices, cfg.signal.momentum_lookback, cfg.signal.momentum_skip
        )
        scores = {t: v for t, v in scores.items() if t in elig}
        if not scores:
            return None
        selected = select_top_k(scores, cfg.signal.top_k)
        w_risky, sigma_hat = self._risky_weights(selected, view)
        garch_params, fell_back = self._vol_diagnostics(selected)
        absmom_all = absolute_momentum(view.prices, view.rates, cfg.signal.momentum_lookback)
        absmom = {t: bool(absmom_all.get(t, False)) for t in selected}
        weights, cash = route_absmom_to_cash(w_risky, absmom)
        target = {**weights, CASH: cash}
        return Decision(
            target_weights=target,
            diagnostics=Diagnostics(
                eligible=elig,
                selected=selected,
                momentum_scores=scores,
                absmom=absmom,
                sigma_hat=sigma_hat,
                w_risky=w_risky,
                vol_fell_back=fell_back,
                garch_params=garch_params,
            ),
        )

    @abstractmethod
    def _risky_weights(
        self, selected: list[str], view: PointInTimeView
    ) -> tuple[dict[str, float], dict[str, float] | None]:
        """回傳 (相對權重 Σ=1, σ̂ 或 None)。"""

    def _vol_diagnostics(
        self, selected: list[str]
    ) -> tuple[dict[str, dict[str, float] | None] | None, dict[str, bool] | None]:
        """(garch_params, fell_back)；預設 None（無 GARCH，如 mom_only）。子類可覆寫。"""
        return None, None
