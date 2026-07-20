"""波動率模型層（規格 §5）。Phase 3 只有 rolling_std placeholder。"""

from __future__ import annotations

import pandas as pd

from quantcore.models.volatility.rolling_std import annualized_vol


def estimate_annualized_vol(vol_model: str, adj_close: pd.Series, window: int) -> float:
    """依 config 的 vol_model 派發 σ̂ 估計。未實作模型明確拋錯，不靜默。"""
    if vol_model == "rolling_std":
        return annualized_vol(adj_close, window)
    raise NotImplementedError(f"vol_model={vol_model!r} 尚未實作（Phase 4）")


__all__ = ["annualized_vol", "estimate_annualized_vol"]
