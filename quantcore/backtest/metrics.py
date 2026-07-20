"""績效統計（規格 §6.4）。純函式，不碰檔案。

Phase 2 不含 block bootstrap CI（§9 明講「先不含 bootstrap」），Phase 4 加入。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_DAYS_PER_YEAR = 252
_BPS = 10_000.0
# 「零變異」判斷用的容忍值：對重複的常數浮點數陣列取 mean 再相減，
# sum/除法無法精確還原原值，std 會落在 ~1e-19 量級而非精確 0.0。
# 用絕對值比較 exact ==0.0 會誤判為「有變異」，故以此容忍值取代。
_ZERO_VAR_TOL = 1e-12


def annualized_return(nav: pd.Series) -> float:
    """CAGR。以交易日數 / 252 為年數。"""
    n = len(nav) - 1
    if n <= 0:
        return float("nan")
    return float((nav.iloc[-1] / nav.iloc[0]) ** (_DAYS_PER_YEAR / n) - 1.0)


def sharpe(ret: pd.Series, rf_daily: pd.Series) -> float:
    """年化 Sharpe，超額於 DTB3（§6.4）。超額報酬無變異時回 nan。"""
    e = ret.to_numpy() - rf_daily.to_numpy()
    sd = e.std(ddof=1)
    if sd < _ZERO_VAR_TOL:
        return 0.0 if abs(e.mean()) < _ZERO_VAR_TOL else float("nan")
    return float(e.mean() / sd * np.sqrt(_DAYS_PER_YEAR))


def sortino(ret: pd.Series, rf_daily: pd.Series) -> float:
    """年化 Sortino：分母只算下檔波動。無下檔時回 nan。"""
    e = ret.to_numpy() - rf_daily.to_numpy()
    downside = e[e < 0]
    if len(downside) < 2:
        # ddof=1 樣本標準差在 n<2 時無定義（分母為 0），提早回 nan
        # 避免 numpy 對單一元素陣列做 std 產生除以零警告。
        return float("nan")
    sd = downside.std(ddof=1)
    if sd < _ZERO_VAR_TOL:
        return float("nan")
    return float(e.mean() / sd * np.sqrt(_DAYS_PER_YEAR))


def max_drawdown(nav: pd.Series) -> float:
    """最大回撤（負值或 0）。"""
    dd = nav / nav.cummax() - 1.0
    return float(dd.min())


def calmar(nav: pd.Series) -> float:
    """CAGR / |MaxDD|。無回撤時回 nan。"""
    mdd = max_drawdown(nav)
    if mdd == 0.0:
        return float("nan")
    return float(annualized_return(nav) / abs(mdd))


def annualized_turnover(total_turnover: float, n_days: int) -> float:
    if n_days <= 0:
        return float("nan")
    return float(total_turnover * _DAYS_PER_YEAR / n_days)


def compute_metrics(
    nav: pd.Series, rate_daily: pd.Series, total_turnover: float, total_cost: float
) -> dict[str, float]:
    """§6.4 的彙總統計。nav 與 rate_daily 須等長且同序。"""
    ret = nav.pct_change().fillna(0.0)
    n = len(nav)
    years = n / _DAYS_PER_YEAR
    return {
        "annualized_return": annualized_return(nav),
        "sharpe": sharpe(ret, rate_daily),
        "sortino": sortino(ret, rate_daily),
        "max_drawdown": max_drawdown(nav),
        "calmar": calmar(nav),
        "annualized_turnover": annualized_turnover(total_turnover, n),
        "cost_drag_bps_per_year": float(total_cost / nav.iloc[0] * _BPS / years)
        if years > 0
        else float("nan"),
        "n_days": n,
    }
