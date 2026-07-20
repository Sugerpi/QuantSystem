"""相對權重與絕對動量轉現金（規格 §1.6 Step 2、§1.4）。純函數。

依賴方向：portfolio 上游於 backtest，只認基本型別，不 import view/策略。
"""

from __future__ import annotations

import math


def inverse_vol(sigma_hat: dict[str, float]) -> dict[str, float]:
    """w_i = (1/σ̂_i) / Σ_j(1/σ̂_j)，Σ w = 1（§1.6 Step 2）。

    σ̂ 須為正且有限。Phase 3 的 rolling_std 在資料退化時可能回 NaN，
    若放行會靜默污染權重——故此處明確拋錯（呼應 vol 派發的誠實失敗設計）。
    """
    for t, s in sigma_hat.items():
        if not math.isfinite(s) or s <= 0.0:
            raise ValueError(f"σ̂[{t}]={s} 非正或非有限，無法計算 inverse-vol")
    inv = {t: 1.0 / s for t, s in sigma_hat.items()}
    total = sum(inv.values())
    return {t: v / total for t, v in inv.items()}


def equal_weight(assets: list[str]) -> dict[str, float]:
    """入選資產等權，Σ w = 1。"""
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
