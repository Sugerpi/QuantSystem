"""DCC(1,1) 兩步 QMLE 的第二步（規格 §5.3）。

單變量 σ_t 由既有 GARCH 提供（標準化殘差為輸入）；本模組做 Q̄、Q_t 遞迴、
(a,b) QMLE、R 正規化。對稱化/shrinkage/正規化全封在此——呼叫端拿不到非法矩陣。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from quantcore.models.correlation.base import normalize_to_correlation

_A_START, _B_START = 0.02, 0.95  # QMLE 固定起點（決定性，不吃亂數，INV-6）
_AB_UPPER = 0.999  # a+b 上界（保平穩）


@dataclass(frozen=True, eq=False)
class DccParams:
    """eq=False 因 q_bar 為 ndarray（陣列相等無自然語意、且會使 __eq__/__hash__ 拋錯）；
    DccParams 作值載體用，以身分比較即可。呼叫端不應原地（in place）修改 q_bar。
    """

    a: float
    b: float
    q_bar: np.ndarray  # 標準化殘差的（shrink 後）樣本相關（呼叫端勿就地改）
    # 重估失敗/退化而回退 fixed_ab 時 True（供消融觀測，比照 4a FitOutcome.fell_back）
    fell_back: bool = False


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


def _dcc_negloglik(theta: np.ndarray, E: np.ndarray, Qbar: np.ndarray) -> float:
    """DCC 準似然（僅相關部分）：Σ_t [log|R_t| + ε_t' R_t^{-1} ε_t]。"""
    a, b = float(theta[0]), float(theta[1])
    if a < 0 or b < 0 or a + b >= _AB_UPPER:
        return 1e12  # 不可行區重罰
    Q = Qbar.copy()
    total = 0.0
    for t in range(len(E)):
        if t > 0:
            e_prev = E[t - 1][:, None]
            Q = (1 - a - b) * Qbar + a * (e_prev @ e_prev.T) + b * Q
        R = normalize_to_correlation(Q)
        e = E[t][:, None]
        sign, logdet = np.linalg.slogdet(R)
        if sign <= 0 or not np.isfinite(logdet):
            return 1e12
        quad = float((e.T @ np.linalg.solve(R, e)).item())
        total += logdet + quad
    return total


def estimate_dcc(
    std_resid: pd.DataFrame, fixed_ab: tuple[float, float], shrink: float
) -> DccParams:
    """QMLE 估 (a,b)；不收斂 / a+b≥1 / 非有限 → 退回 fixed_ab（誠實 fallback + fell_back 標記，
    比照 4a）。

    僅「觀測不足（<2）」退化為 fixed（Q̄=I）；零變異數殘差與 shrink 非法由 q_bar 誠實拋錯（不吞）。
    """
    try:
        _, E = _resid_matrix(std_resid)
    except ValueError:
        k = len(std_resid.columns)
        return DccParams(*fixed_ab, np.eye(k), fell_back=True)
    Qbar = q_bar(std_resid, shrink)  # 零變異數/shrink 非法 → 拋錯，不吞
    res = minimize(
        _dcc_negloglik,
        x0=np.array([_A_START, _B_START], dtype="float64"),
        args=(E, Qbar),
        method="SLSQP",
        bounds=[(0.0, _AB_UPPER), (0.0, _AB_UPPER)],
        constraints=[{"type": "ineq", "fun": lambda x: _AB_UPPER - x[0] - x[1]}],
        options={"maxiter": 200, "ftol": 1e-8},
    )
    a, b = float(res.x[0]), float(res.x[1])
    ok = bool(res.success) and np.isfinite([a, b]).all() and a >= 0 and b >= 0 and a + b < 1.0
    if not ok:
        return DccParams(*fixed_ab, Qbar, fell_back=True)
    return DccParams(a=a, b=b, q_bar=Qbar, fell_back=False)
