"""相對權重與絕對動量轉現金（規格 §1.6 Step 2、§1.4）。純函數。

依賴方向：portfolio 上游於 backtest，只認基本型別，不 import view/策略。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def inverse_vol(sigma_hat: dict[str, float]) -> dict[str, float]:
    """w_i = (1/σ̂_i) / Σ_j(1/σ̂_j)，Σ w = 1（§1.6 Step 2）。

    σ̂ 須為正且有限。Phase 3 的 rolling_std 在資料退化時可能回 NaN，
    若放行會靜默污染權重——故此處明確拋錯（呼應 vol 派發的誠實失敗設計）。
    """
    if not sigma_hat:
        raise ValueError("inverse_vol 收到空的 sigma_hat（呼叫端應先保證有入選資產）")
    for t, s in sigma_hat.items():
        if not math.isfinite(s) or s <= 0.0:
            raise ValueError(f"σ̂[{t}]={s} 非正或非有限，無法計算 inverse-vol")
    inv = {t: 1.0 / s for t, s in sigma_hat.items()}
    total = sum(inv.values())
    return {t: v / total for t, v in inv.items()}


def equal_weight(assets: list[str]) -> dict[str, float]:
    """入選資產等權，Σ w = 1。"""
    if not assets:
        raise ValueError("equal_weight 收到空的資產清單（呼叫端應先保證有入選資產）")
    w = 1.0 / len(assets)
    return {t: w for t in assets}


def route_absmom_to_cash(
    w_risky: dict[str, float], absmom_pass: dict[str, bool]
) -> tuple[dict[str, float], float]:
    """絕對動量 fail 的資產配額整份轉入現金（§1.4）。不在 pass 檔上重新歸一。

    回傳 (通過檔的權重, 現金權重)。兩者總和守恆 = Σ w_risky。
    """
    weights = {t: w for t, w in w_risky.items() if absmom_pass.get(t, False)}
    cash = sum(w for t, w in w_risky.items() if not absmom_pass.get(t, False))
    return weights, cash


_ERC_TOL = 1e-10  # CCD 收斂容差（權重最大變動）
_ERC_MAX_ITER = 10000  # CCD 迭代上限（演算法常數，正定 Σ 通常數十輪收斂）


def erc_weights(cov: pd.DataFrame) -> dict[str, float]:
    """等風險貢獻權重（長單、Σw=1）：各檔風險貢獻 w_i·(Σw)_i 相等。

    Spinu(2013) 循環座標下降（Gauss-Seidel）：對每檔解一元二次
    Σ_ii w_i² + β_i w_i − c = 0（β_i=Σ_{j≠i}Σ_ij w_j）取正根，掃至收斂後正規化。
    長單由結構保證（正根），對正定 Σ 收斂、決定性（無亂數，INV-6）。
    Σ 由 build_covariance 已保證 PSD/對稱/正對角。
    """
    tickers = list(cov.columns)
    n = len(tickers)
    if n == 0:
        raise ValueError("erc_weights 收到空共變異數")
    s = np.asarray(cov.to_numpy(), dtype="float64")
    if not np.isfinite(s).all():
        raise ValueError("erc_weights：共變異數含非有限值")
    if n == 1:
        return {tickers[0]: 1.0}
    diag = np.diag(s)
    if np.any(diag <= 0.0):
        raise ValueError("erc_weights：共變異數對角線須為正（零/負變異數）")
    c = 1.0  # 等風險預算；正規化後不影響解
    w = 1.0 / np.sqrt(diag)  # inverse-vol 暖啟
    w = w / w.sum()
    for _ in range(_ERC_MAX_ITER):
        w_old = w.copy()
        for i in range(n):
            beta = float(s[i] @ w - s[i, i] * w[i])  # Σ_{j≠i} Σ_ij w_j（Gauss-Seidel：用最新 w）
            w[i] = (-beta + np.sqrt(beta * beta + 4.0 * s[i, i] * c)) / (2.0 * s[i, i])
        if np.max(np.abs(w - w_old)) < _ERC_TOL:
            break
    w = w / w.sum()
    return {t: float(wi) for t, wi in zip(tickers, w, strict=True)}
