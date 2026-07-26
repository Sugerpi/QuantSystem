"""DCC(1,1) 兩步 QMLE 的第二步（規格 §5.3）。

單變量 σ_t 由既有 GARCH 提供（標準化殘差為輸入）；本模組做 Q̄、Q_t 遞迴、
(a,b) QMLE、R 正規化。對稱化/shrinkage/正規化全封在此——呼叫端拿不到非法矩陣。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantcore.models.correlation.base import normalize_to_correlation

_QBAR_SHRINK = 0.10  # Q̄ 向單位對角收縮係數（小樣本病態防護；plan 值，可消融）


@dataclass(frozen=True)
class DccParams:
    a: float
    b: float
    q_bar: np.ndarray  # 標準化殘差的（shrink 後）樣本相關


def _resid_matrix(std_resid: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    cols = sorted(std_resid.columns)
    E = std_resid[cols].dropna().to_numpy(dtype="float64")
    if len(E) < 2:
        raise ValueError("DCC 需至少 2 筆觀測")
    return cols, E


def q_bar(std_resid: pd.DataFrame) -> np.ndarray:
    """Q̄ = (1−δ)·樣本相關 + δ·I（δ=_QBAR_SHRINK），對稱正定。"""
    _, E = _resid_matrix(std_resid)
    C = np.atleast_2d(np.corrcoef(E, rowvar=False))
    if not np.isfinite(C).all():
        raise ValueError("Q̄：標準化殘差樣本相關含非有限值（零變異數殘差）")
    k = C.shape[0]
    return (1 - _QBAR_SHRINK) * C + _QBAR_SHRINK * np.eye(k)


def dcc_recursion(std_resid: pd.DataFrame, params: DccParams) -> pd.DataFrame:
    """Q_t = (1−a−b)Q̄ + a·ε_{t−1}ε_{t−1}' + b·Q_{t−1}，Q_0=Q̄；回 last 的 R（label-aligned）。"""
    cols, E = _resid_matrix(std_resid)
    a, b, Qbar = params.a, params.b, params.q_bar
    Q = Qbar.copy()
    for t in range(1, len(E)):
        e = E[t - 1][:, None]
        Q = (1 - a - b) * Qbar + a * (e @ e.T) + b * Q
    R = normalize_to_correlation(Q)
    return pd.DataFrame(R, index=cols, columns=cols)
