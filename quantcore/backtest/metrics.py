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


def stationary_bootstrap_indices(
    n: int, mean_block: int, n_reps: int, rng: np.random.Generator
) -> np.ndarray:
    """Politis-Romano stationary bootstrap 索引矩陣 (n_reps, n)。

    每步以機率 1/mean_block 跳到新隨機起點，否則沿用前一索引 +1（circular wrap）。
    日報酬有自相關，iid 重抽的 CI 系統性偏窄（§6.4），故用 stationary bootstrap。
    RNG 由呼叫端以 cfg.seed 建立（INV-6）。
    """
    if n < 1 or mean_block < 1 or n_reps < 1:
        raise ValueError("n/mean_block/n_reps 皆須 ≥ 1")
    p = 1.0 / mean_block
    idx = np.empty((n_reps, n), dtype=np.int64)
    for r in range(n_reps):
        i = int(rng.integers(0, n))
        idx[r, 0] = i
        for t in range(1, n):
            i = int(rng.integers(0, n)) if rng.random() < p else (i + 1) % n
            idx[r, t] = i
    return idx


def _nav_from_returns(r: np.ndarray) -> pd.Series:
    """由日報酬重建 NAV（起始 1.0）。供 Calmar/MaxDD 的 bootstrap 一致計算。"""
    return pd.Series(np.concatenate([[1.0], np.cumprod(1.0 + np.asarray(r, dtype="float64"))]))


def metric_sharpe(r: np.ndarray, rf: np.ndarray) -> float:
    """報酬陣列版 Sharpe（供 bootstrap）。"""
    return sharpe(pd.Series(r), pd.Series(rf))


def metric_calmar(r: np.ndarray, rf: np.ndarray) -> float:
    """報酬陣列版 Calmar（供 bootstrap；rf 未用）。"""
    return calmar(_nav_from_returns(r))


def _percentile_ci(samples: np.ndarray, alpha: float) -> tuple[float, float]:
    """雙尾百分位 CI (lo, hi)。剔除非有限後若無樣本則回 (nan, nan)——避免 np.percentile 崩潰。"""
    finite = samples[np.isfinite(samples)]
    if finite.size == 0:
        return float("nan"), float("nan")
    lo = float(np.percentile(finite, 100 * alpha / 2))
    hi = float(np.percentile(finite, 100 * (1 - alpha / 2)))
    return lo, hi


def bootstrap_metric_ci(
    returns: np.ndarray,
    rf: np.ndarray,
    metric_fn,
    indices: np.ndarray,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """單一策略指標的百分位 CI。回 (point, lo, hi)。非有限重抽值剔除。"""
    r = np.asarray(returns, dtype="float64")
    f = np.asarray(rf, dtype="float64")
    stats = np.array([metric_fn(r[ix], f[ix]) for ix in indices])
    # 非有限重抽（如 Calmar 對零回撤 resample 回 nan）被剔除：
    # CI 為「條件於有定義的 resample」的覆蓋。
    lo, hi = _percentile_ci(stats, alpha)
    return float(metric_fn(r, f)), lo, hi


def paired_metric_diff_ci(
    returns_a: np.ndarray,
    returns_b: np.ndarray,
    rf: np.ndarray,
    metric_fn,
    indices: np.ndarray,
    alpha: float = 0.05,
) -> dict[str, float | bool]:
    """配對差異 CI：對兩序列抽**同一組**索引，逐次算 metric(a)−metric(b)（§6.3）。

    回 {point, lo, hi, excludes_zero}。CI 不含 0 才算「優勢站得住」。
    """
    a = np.asarray(returns_a, dtype="float64")
    b = np.asarray(returns_b, dtype="float64")
    f = np.asarray(rf, dtype="float64")
    diffs = np.array([metric_fn(a[ix], f[ix]) - metric_fn(b[ix], f[ix]) for ix in indices])
    # 非有限重抽（如 Calmar 對零回撤 resample 回 nan）被剔除：
    # CI 為「條件於有定義的 resample」的覆蓋。
    lo, hi = _percentile_ci(diffs, alpha)
    point = float(metric_fn(a, f) - metric_fn(b, f))
    return {"point": point, "lo": lo, "hi": hi, "excludes_zero": bool(lo > 0 or hi < 0)}


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
