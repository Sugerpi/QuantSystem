"""DCC(1,1) 兩步 QMLE 的第二步（規格 §5.3）。

單變量 σ_t 由既有 GARCH 提供（標準化殘差為輸入）；本模組做 Q̄、Q_t 遞迴、
(a,b) QMLE、R 正規化。對稱化/shrinkage/正規化全封在此——呼叫端拿不到非法矩陣。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantcore.models.correlation.base import normalize_to_correlation


@dataclass(frozen=True, eq=False)
class DccParams:
    """eq=False 因 q_bar 為 ndarray（陣列相等無自然語意、且會使 __eq__/__hash__ 拋錯）；
    DccParams 作值載體用，以身分比較即可。呼叫端不應原地（in place）修改 q_bar。
    """

    a: float
    b: float
    q_bar: np.ndarray  # 標準化殘差的（shrink 後）樣本相關


def _resid_matrix(std_resid: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    cols = sorted(std_resid.columns)
    E = std_resid[cols].dropna().to_numpy(dtype="float64")
    if len(E) < 2:
        raise ValueError("DCC 需至少 2 筆觀測")
    return cols, E


def q_bar(std_resid: pd.DataFrame, shrink: float) -> np.ndarray:
    """Q̄ = (1−shrink)·樣本相關 + shrink·I，對稱正定。shrink 由 config 提供（可消融）。"""
    if not 0 <= shrink < 1:
        raise ValueError(f"q_bar shrink 須落在 [0,1)，收到 {shrink}")
    _, E = _resid_matrix(std_resid)
    C = np.atleast_2d(np.corrcoef(E, rowvar=False))
    if not np.isfinite(C).all():
        raise ValueError("Q̄：標準化殘差樣本相關含非有限值（零變異數殘差）")
    k = C.shape[0]
    return (1 - shrink) * C + shrink * np.eye(k)


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
