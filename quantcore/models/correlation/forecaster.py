"""相關預報器 refit/filter（規格 §5.3，鏡射 VolForecaster）。

貴的 (a,b) QMLE 週期重估（每 refit_interval 交易日 = 每 estimate_every 次選擇）、
便宜的 Q_t 遞迴每次決策。ewma 模式無待估參數。有狀態，策略每 run 新建（不破 INV-6）。
"""

from __future__ import annotations

import pandas as pd

from quantcore.models.correlation.dcc import DccParams, dcc_recursion, estimate_dcc, q_bar
from quantcore.models.correlation.ewma_corr import ewma_correlation


class CorrelationForecaster:
    def __init__(
        self,
        corr_model: str,
        ewma_lambda: float,
        refit_interval: int,
        fixed_ab: tuple[float, float],
        selection_interval: int,
        qbar_shrink: float,
    ) -> None:
        if corr_model not in ("dcc", "ewma"):
            raise ValueError(f"CorrelationForecaster 不支援 corr_model={corr_model!r}")
        self._model = corr_model
        self._lam = ewma_lambda
        self._refit_interval = refit_interval
        self._fixed_ab = fixed_ab
        self._qbar_shrink = qbar_shrink
        # 63÷21=3：每 3 次選擇重估 (a,b)。fixed 模式（refit_interval==0）不重估。
        self._estimate_every = max(1, round(refit_interval / selection_interval))
        self._n_sel = 0
        self._params: DccParams | None = None

    def refit(self, std_resid: pd.DataFrame) -> pd.DataFrame:
        """選擇日：ewma 直接算 R；dcc 依節奏重估或沿用 (a,b)，Q̄ 每次重算，回 R_t。"""
        if self._model == "ewma":
            return ewma_correlation(std_resid, self._lam)
        self._n_sel += 1
        reestimate = self._refit_interval > 0 and ((self._n_sel - 1) % self._estimate_every == 0)
        if reestimate or self._params is None:
            if self._refit_interval == 0:  # fixed 模式：(a,b) 固定、僅 Q̄
                self._params = DccParams(*self._fixed_ab, q_bar(std_resid, self._qbar_shrink))
            else:
                self._params = estimate_dcc(std_resid, self._fixed_ab, self._qbar_shrink)
        else:  # 沿用 (a,b)，Q̄ 隨（可能輪動的）資產集重算；保留 fell_back（否則消融漏算 fallback）
            self._params = DccParams(
                self._params.a,
                self._params.b,
                q_bar(std_resid, self._qbar_shrink),
                fell_back=self._params.fell_back,
            )
        return dcc_recursion(std_resid, self._params)

    def filter(self, std_resid: pd.DataFrame) -> pd.DataFrame:
        """曝險檢查日：ewma 直接算；dcc 沿用快取 (a,b,Q̄) 只推進遞迴，回 R_t（不重估）。"""
        if self._model == "ewma":
            return ewma_correlation(std_resid, self._lam)
        assert self._params is not None  # 選擇日必先 refit
        return dcc_recursion(std_resid, self._params)

    def last_params(self) -> DccParams | None:
        """供測試/診斷：dcc 回當前 DccParams；ewma 回 None。"""
        return self._params
