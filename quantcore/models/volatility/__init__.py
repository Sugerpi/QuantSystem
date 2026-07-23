"""波動率模型層（規格 §5）。

- rolling_std：Phase 3 placeholder（保留，4b 前 mom_ivol 仍用）。
- VolatilityModel/Ewma/GarchArch：Phase 4a 正式模型。
- fit_volatility：GARCH 失敗退回 EWMA 的封裝（設計文件 §1.4）。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quantcore.models.volatility.base import (
    DAYS_PER_YEAR,
    GarchDegenerateError,
    VolatilityModel,
    annualize_variance_path,
)
from quantcore.models.volatility.ewma import Ewma
from quantcore.models.volatility.garch_arch import GarchArch
from quantcore.models.volatility.rolling_std import annualized_vol


def estimate_annualized_vol(vol_model: str, adj_close: pd.Series, window: int) -> float:
    """依 config 的 vol_model 派發 σ̂ 估計（Phase 3 相容路徑，4b 前 mom_ivol 用）。"""
    if vol_model == "rolling_std":
        return annualized_vol(adj_close, window)
    raise NotImplementedError(f"vol_model={vol_model!r} 於此相容路徑未實作；請用 fit_volatility")


def annualized_forecast_vol(model: VolatilityModel, horizon: int) -> float:
    """σ̂ = sqrt( (1/H)·Σ Var(t+h) )·sqrt(252)（規格 §1.6 Step 1）。"""
    return annualize_variance_path(model.forecast(horizon))


@dataclass(frozen=True)
class FitOutcome:
    model: VolatilityModel
    fell_back: bool
    reason: str | None


def fit_volatility(spec: str, returns: pd.Series, *, ewma_lambda: float) -> FitOutcome:
    """依 spec 建模型並 fit。garch_arch 失敗退回 EWMA 並記標記（設計文件 §1.4）。

    fallback 契約僅涵蓋 **fit-time** 退化（不收斂 / α+β≥1 / 非有限參數）。
    fit 成功後的 forecast 不在保護傘下——但 fit 已強制 α+β<1 且 ω 有限，
    GARCH(1,1) 解析多步變異數因此恆為有限，forecast-time 退化不可達。
    """
    if spec == "garch_arch":
        try:
            return FitOutcome(GarchArch().fit(returns), False, None)
        except GarchDegenerateError as exc:
            return FitOutcome(Ewma(ewma_lambda).fit(returns), True, str(exc))
    if spec == "ewma":
        return FitOutcome(Ewma(ewma_lambda).fit(returns), False, None)
    raise ValueError(f"未知 vol spec：{spec!r}（可用：garch_arch | ewma）")


__all__ = [
    "DAYS_PER_YEAR",
    "Ewma",
    "FitOutcome",
    "GarchArch",
    "GarchDegenerateError",
    "VolatilityModel",
    "annualize_variance_path",
    "annualized_forecast_vol",
    "annualized_vol",
    "estimate_annualized_vol",
    "fit_volatility",
]
