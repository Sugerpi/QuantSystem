"""相關矩陣合法性的單一出口（規格 §5.3、INV-3）。

DCC 的 Q_t 與 EWMA 的 S_t 都經此正規化為合法相關矩陣（對稱/PSD/單位對角）——
呼叫端拿不到非法 R。與 covariance.build_covariance 的 Σ 投影本是同一數學，統一於此。
"""

from __future__ import annotations

import numpy as np


def normalize_to_correlation(M: np.ndarray) -> np.ndarray:
    """收對稱（近似）方陣 M（相關或 Q_t/S_t），回合法相關矩陣。

    對稱化 → 截負特徵值（PSD）→ 正規化對角線為 1。退化塌陷（對角線 ≈0，
    多為零變異數/常數殘差窗）改為拋錯，不再靜默patch，故對合法輸入
    輸出恆對稱、PSD、單位對角。
    """
    M = (np.asarray(M, dtype="float64") + np.asarray(M, dtype="float64").T) / 2.0
    vals, vecs = np.linalg.eigh(M)
    vals = np.clip(vals, 0.0, None)
    M_psd = (vecs * vals) @ vecs.T
    d = np.sqrt(np.diag(M_psd))
    if np.any(d <= 1e-12):
        raise ValueError(
            "normalize_to_correlation：對角線塌陷（某資產變異數≈0，多為零變異數/常數殘差窗）"
            "——拒絕靜默產出非單位對角，風險出口誠實失敗"
        )
    R = M_psd / np.outer(d, d)
    return (R + R.T) / 2.0  # 數值再對稱化
