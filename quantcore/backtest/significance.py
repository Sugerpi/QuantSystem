"""穩健性顯著性檢定純函式（規格 §3；設計 2026-08-16）。

無檔案 IO；隨機性由呼叫端以 cfg.seed 建 Generator 傳入（INV-6）。
所有 Sharpe 一律以每期（非年化）值進入公式（Bailey & López de Prado 慣例）。
"""

from __future__ import annotations

from itertools import combinations
from math import log

import numpy as np
from scipy.stats import norm

# Euler-Mascheroni 常數（expected max Sharpe 用）
_EULER = 0.5772156649015329


def psr(sr: float, n: int, skew: float, kurt: float, sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio。sr 為每期值，kurt 為非超額峰態（常態=3）。

    PSR = Φ( (sr − sr_benchmark)·√(n−1) / √(1 − skew·sr + ((kurt−1)/4)·sr²) )。
    n<2 或分母非正 → nan。
    """
    if n < 2:
        return float("nan")
    var = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr**2
    if not np.isfinite(var) or var <= 0.0:
        return float("nan")
    z = (sr - sr_benchmark) * np.sqrt(n - 1) / np.sqrt(var)
    return float(norm.cdf(z))


def expected_max_sharpe(sr_variance: float, n_trials: int) -> float:
    """N 次獨立試驗下的期望最大 Sharpe（Bailey & López de Prado 2014）。

    √V·[ (1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e)) ]。V≤0 或 N<2 → nan。
    """
    if n_trials < 2 or sr_variance <= 0.0:
        return float("nan")
    q1 = norm.ppf(1.0 - 1.0 / n_trials)
    q2 = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    return float(np.sqrt(sr_variance) * ((1.0 - _EULER) * q1 + _EULER * q2))


def deflated_sharpe_ratio(
    sr: float, n: int, skew: float, kurt: float, sr_variance: float, n_trials: int
) -> float:
    """Deflated Sharpe Ratio：以 expected_max_sharpe 為 benchmark 的 PSR。

    sr_variance = N 個試驗 Sharpe 的橫斷面變異；n_trials = 消融格數。
    benchmark 無法計算（nan）時回 nan。
    """
    sr_star = expected_max_sharpe(sr_variance, n_trials)
    if not np.isfinite(sr_star):
        return float("nan")
    return psr(sr, n, skew, kurt, sr_benchmark=sr_star)


def pbo_cscv(returns_matrix, n_splits: int, sharpe_fn) -> dict:
    """Probability of Backtest Overfitting via CSCV（Bailey et al. 2017）。

    returns_matrix：T×N（N 個候選配置的日報酬）。
    T 切 S 塊（S 偶數），列舉 C(S,S/2) 種 IS/OOS 對半組合；每組取 IS 最佳候選，
    算其 OOS 相對排名 ω 的 logit λ；PBO = λ≤0 的組合比例（越低越不過擬合）。
    N<2 或 S 為奇數或 S<2 → value=nan。T 不整除 S 時尾端餘列丟棄。
    """
    m = np.asarray(returns_matrix, dtype="float64")
    t, n = m.shape
    base = {"value": float("nan"), "n_splits": int(n_splits), "n_candidates": int(n)}
    if n < 2 or n_splits < 2 or n_splits % 2 != 0:
        return {**base, "n_combinations": 0}
    block = t // n_splits
    if block < 1:
        return {**base, "n_combinations": 0}
    blocks = [m[i * block : (i + 1) * block] for i in range(n_splits)]  # 尾端餘列丟棄
    half = n_splits // 2
    lam_le0 = 0
    total = 0
    for is_idx in combinations(range(n_splits), half):
        oos_idx = [j for j in range(n_splits) if j not in is_idx]
        is_mat = np.vstack([blocks[j] for j in is_idx])
        oos_mat = np.vstack([blocks[j] for j in oos_idx])
        is_perf = np.array([sharpe_fn(is_mat[:, c]) for c in range(n)])
        oos_perf = np.array([sharpe_fn(oos_mat[:, c]) for c in range(n)])
        # nan 視為最差，避免 argmax/排名被污染
        is_perf = np.where(np.isfinite(is_perf), is_perf, -np.inf)
        oos_perf = np.where(np.isfinite(oos_perf), oos_perf, -np.inf)
        n_star = int(np.argmax(is_perf))
        rank = 1 + int((oos_perf < oos_perf[n_star]).sum())  # 1..N
        omega = rank / (n + 1)  # ∈ (0,1)
        lam = log(omega / (1.0 - omega))
        lam_le0 += int(lam <= 0.0)
        total += 1
    return {**base, "value": lam_le0 / total, "n_combinations": total}


def _block_swap_mask(n: int, mean_block: int, rng) -> np.ndarray:
    """長度 n 的布林遮罩：以平均塊長 mean_block 分塊，每塊獨立擲幣決定是否對調。

    尊重自相關（與 stationary bootstrap 一致的塊長概念）；塊起點以機率
    1/mean_block 開新塊，開塊時重擲該塊的 swap 決定。
    """
    if n < 1 or mean_block < 1:
        raise ValueError("n/mean_block 皆須 ≥ 1")
    p = 1.0 / mean_block
    mask = np.empty(n, dtype=bool)
    cur = bool(rng.random() < 0.5)
    mask[0] = cur
    for t in range(1, n):
        if rng.random() < p:
            cur = bool(rng.random() < 0.5)
        mask[t] = cur
    return mask


def permutation_test_paired(a, b, rf, metric_fn, n_perms: int, mean_block: int, rng) -> dict:
    """配對區塊符號置換檢定。回 {observed, p_value}。

    H0：兩序列可交換。每次置換以 _block_swap_mask 對調配對，重算 metric 差異建 null；
    雙尾 p = (#{|null|≥|observed|}+1)/(n_perms+1)。rng 由呼叫端以 cfg.seed 建（INV-6）。
    """
    a = np.asarray(a, dtype="float64")
    b = np.asarray(b, dtype="float64")
    f = np.asarray(rf, dtype="float64")
    observed = float(metric_fn(a, f) - metric_fn(b, f))
    if not np.isfinite(observed):
        return {"observed": observed, "p_value": float("nan")}
    n = len(a)
    count = 0
    for _ in range(n_perms):
        mask = _block_swap_mask(n, mean_block, rng)
        pa = np.where(mask, b, a)
        pb = np.where(mask, a, b)
        diff = metric_fn(pa, f) - metric_fn(pb, f)
        if np.isfinite(diff) and abs(diff) >= abs(observed):
            count += 1
    return {"observed": observed, "p_value": (count + 1) / (n_perms + 1)}
