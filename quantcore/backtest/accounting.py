"""會計：NAV 遞推、權重漂移、現金計息、成本入帳（規格 §1.5、§1.8、§6.1；INV-5）。

全為純函式——不知道日期、不碰 I/O。權重 dict 一律含 'CASH' 鍵。
"""

from __future__ import annotations

CASH = "CASH"
"""合成現金的鍵（§1.5：直接以利率入帳，不持有 BIL/SHV）。"""

_BPS = 10_000.0


def portfolio_return(
    weights: dict[str, float], returns: dict[str, float], cash_rate_daily: float
) -> float:
    """當日組合報酬 = Σ w_i·r_i + w_cash·日利率（§6.1 step 3）。"""
    total = weights.get(CASH, 0.0) * cash_rate_daily
    for k, w in weights.items():
        if k == CASH or w == 0.0:
            continue
        if k not in returns:
            raise KeyError(f"持有 {k} 但當日無報酬資料")
        total += w * returns[k]
    return total


def apply_returns(
    nav: float,
    weights: dict[str, float],
    returns: dict[str, float],
    cash_rate_daily: float,
) -> tuple[float, dict[str, float]]:
    """當日損益 + 權重漂移，回傳 (新 NAV, 漂移後權重)。

    漂移後權重恆和為 1（INV-5）：分母為 1 + 組合報酬，與分子的成長因子一致。
    """
    pr = portfolio_return(weights, returns, cash_rate_daily)
    growth = 1.0 + pr
    if growth <= 0.0:
        raise ValueError(f"組合報酬 {pr} 導致 NAV 歸零或為負，資料異常")
    drifted = {}
    for k, w in weights.items():
        g = (1.0 + cash_rate_daily) if k == CASH else (1.0 + returns.get(k, 0.0))
        drifted[k] = w * g / growth
    return nav * growth, drifted


def trade_deltas(drifted: dict[str, float], target: dict[str, float]) -> dict[str, float]:
    """每檔風險資產的權重變動 target_i − drifted_i（**不含 CASH**）。

    turnover 的 per-ticker 分解：trade blotter 由此接出，結構上保證
    Σ|delta| ≡ turnover（現金為合成、無交易成本，計入會使單邊成本翻倍）。
    """
    keys = (set(drifted) | set(target)) - {CASH}
    return {k: target.get(k, 0.0) - drifted.get(k, 0.0) for k in keys}


def turnover(drifted: dict[str, float], target: dict[str, float]) -> float:
    """Σ_i |target_i − drifted_i|，**i 只跑風險資產**（§1.8、設計文件 §2.2）。

    現金為合成、無交易成本；計入 CASH 腿會使單邊成本變兩倍。
    """
    return sum(abs(dw) for dw in trade_deltas(drifted, target).values())


def apply_costs(
    nav: float, drifted: dict[str, float], target: dict[str, float], per_side_bps: float
) -> tuple[float, float]:
    """執行日扣成本，回傳 (扣後 NAV, 換手率)。"""
    to = turnover(drifted, target)
    return nav - nav * to * per_side_bps / _BPS, to
