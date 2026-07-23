"""過渡共變異數（規格 §1.6、INV-3）。Σ 的唯一出口。

Phase 4b 的相關 R 為滾動樣本相關（DCC 為 Phase 5，此為 placeholder，
比照 Phase 3 的 rolling_std→GARCH）。INV-3（對稱/PSD/對角線=個別變異數）靠
「投影 R 為合法 PSD 相關 → Σ=D·R·D」自然同時成立。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_correlation(returns_window: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """收 date×ticker 報酬窗，回 (樣本相關 R, 排序後 ticker 序)。欄序固定供對齊。"""
    cols = sorted(returns_window.columns)
    w = returns_window[cols].dropna()
    if len(w) < 2:
        raise ValueError("rolling_correlation 需至少 2 筆觀測")
    R = np.atleast_2d(np.corrcoef(w.to_numpy(), rowvar=False))
    return R, cols


def _project_to_psd_correlation(R: np.ndarray) -> np.ndarray:
    """對稱化 → 截負特徵值 → 重正規化對角線為 1（合法 PSD 相關矩陣）。"""
    R = (R + R.T) / 2.0
    vals, vecs = np.linalg.eigh(R)
    vals = np.clip(vals, 0.0, None)
    R_psd = (vecs * vals) @ vecs.T
    d = np.sqrt(np.diag(R_psd))
    d[d == 0.0] = 1.0  # 僅在某列完全落在被截零特徵空間才觸發——真實樣本相關恆 PSD、
    # 投影近恆等，故不可達；過渡期不另守護。
    R_corr = R_psd / np.outer(d, d)
    return (R_corr + R_corr.T) / 2.0  # 數值再對稱化


def build_covariance(sigma_hat: dict[str, float], R: np.ndarray, tickers: list[str]) -> np.ndarray:
    """Σ = D·R_psd·D，D = diag(σ̂[tickers 順序])。INV-3 三性質成立。

    tickers 必須是 rolling_correlation 回傳的那一份（R 的列/欄序即 tickers 序）；
    長度/順序須一致。
    """
    for t in tickers:
        s = sigma_hat.get(t)
        if s is None or not np.isfinite(s) or s <= 0.0:
            raise ValueError(f"σ̂[{t}]={s} 缺失/非正/非有限")
    R = np.atleast_2d(np.asarray(R, dtype="float64"))
    if not np.isfinite(R).all():
        raise ValueError("共變異數：相關矩陣 R 含非有限值（多為零變異數報酬窗，如停牌/常數資產）")
    if R.shape[0] != len(tickers):
        raise ValueError(f"R 維度 {R.shape} 與 tickers 長度 {len(tickers)} 不符")
    R_psd = _project_to_psd_correlation(R)
    d = np.array([sigma_hat[t] for t in tickers], dtype="float64")
    return (d[:, None] * R_psd) * d[None, :]  # D R D


def portfolio_vol(w_risky: dict[str, float], cov: np.ndarray, tickers: list[str]) -> float:
    """sqrt(w'Σw)，w 依 tickers 順序取自 w_risky（缺者為 0）。回年化組合波動 σ̂_p。"""
    w = np.array([w_risky.get(t, 0.0) for t in tickers], dtype="float64")
    var = float(w @ np.asarray(cov, dtype="float64") @ w)
    return float(np.sqrt(max(var, 0.0)))  # 數值噪音可能使 var 微負
