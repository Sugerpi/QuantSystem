"""Σ 的唯一出口（規格 §1.6、INV-3）。

R 由相關模型層（models/correlation/，CorrelationForecaster：dcc | ewma）提供；
本模組只負責「σ̂ 與合法相關 R → Σ=D·R·D」。INV-3（對稱/PSD/對角線=個別變異數）靠
「R 經 normalize_to_correlation 為合法 PSD 相關 → Σ=D·R·D」自然同時成立。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantcore.models.correlation.base import normalize_to_correlation


def rolling_correlation(returns_window: pd.DataFrame) -> pd.DataFrame:
    """收 date×ticker 報酬窗，回樣本相關矩陣（index/columns = 排序後 ticker，label-aligned）。

    Phase 5a 起已自 production path 退役（由 CorrelationForecaster 的 dcc/ewma 取代，
    見 backtest/strategies/vol_target_base.py）。僅保留供測試/研究對照使用。
    """
    cols = sorted(returns_window.columns)
    w = returns_window[cols].dropna()
    if len(w) < 2:
        raise ValueError("rolling_correlation 需至少 2 筆觀測")
    R = np.atleast_2d(np.corrcoef(w.to_numpy(), rowvar=False))
    return pd.DataFrame(R, index=cols, columns=cols)


def build_covariance(sigma_hat: dict[str, float], R: pd.DataFrame) -> pd.DataFrame:
    """Σ = D·R_psd·D，label-aligned。資產集由 R 的 columns 決定（結構對齊，無位置耦合）。

    INV-3：投影 R 為合法 PSD 相關（對稱/PSD/單位對角）→ Σ=D·R·D。D=diag(σ̂[R.columns 序])。
    congruence 保 PSD、R_ii=1 保 Σ_ii=σ_i²。
    """
    tickers = list(R.columns)
    for t in tickers:
        s = sigma_hat.get(t)
        if s is None or not np.isfinite(s) or s <= 0.0:
            raise ValueError(f"σ̂[{t}]={s} 缺失/非正/非有限")
    Rv = np.asarray(R.to_numpy(), dtype="float64")
    if not np.isfinite(Rv).all():
        raise ValueError("共變異數：相關矩陣 R 含非有限值（多為零變異數報酬窗，如停牌/常數資產）")
    R_psd = normalize_to_correlation(Rv)
    d = np.array([sigma_hat[t] for t in tickers], dtype="float64")
    Sigma = (d[:, None] * R_psd) * d[None, :]
    return pd.DataFrame(Sigma, index=tickers, columns=tickers)


def portfolio_vol(w_risky: dict[str, float], cov: pd.DataFrame) -> float:
    """sqrt(w'Σw)，label-aligned。回年化組合波動 σ̂_p。

    w_risky 中任何非零權重的 ticker 都必須在 cov 的 label 內——否則其風險會被靜默漏掉、
    σ̂_p 低估、曝險過高（避險不足）。缺涵蓋即拋錯（風險出口誠實失敗）。
    """
    tickers = list(cov.columns)
    missing = [t for t, wv in w_risky.items() if wv != 0.0 and t not in tickers]
    if missing:
        raise ValueError(f"w_risky 含 cov 未涵蓋的資產 {missing}：σ̂_p 會被低估，拒絕計算")
    w = np.array([w_risky.get(t, 0.0) for t in tickers], dtype="float64")
    var = float(w @ np.asarray(cov.to_numpy(), dtype="float64") @ w)
    return float(np.sqrt(max(var, 0.0)))  # 數值噪音可能使 var 微負
