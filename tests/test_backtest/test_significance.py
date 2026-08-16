"""significance 純函式測試（規格 §3）。"""

import numpy as np
from scipy.stats import norm

from quantcore.backtest.significance import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    pbo_cscv,
    psr,
)


def test_psr_reduces_to_phi_when_denominator_is_one():
    # skew=0, kurt=1 → 分母 = √(1 - 0 + 0·sr²) = 1，PSR = Φ(sr·√(n-1))
    sr, n = 0.1, 250
    got = psr(sr, n, skew=0.0, kurt=1.0, sr_benchmark=0.0)
    expected = float(norm.cdf(sr * np.sqrt(n - 1)))
    assert abs(got - expected) < 1e-12


def test_psr_normal_kurtosis_uses_half_sr_squared_term():
    # 常態 kurt=3 → 分母 = √(1 + 0.5·sr²)
    sr, n = 0.2, 500
    got = psr(sr, n, skew=0.0, kurt=3.0, sr_benchmark=0.0)
    denom = np.sqrt(1.0 + 0.5 * sr**2)
    expected = float(norm.cdf(sr * np.sqrt(n - 1) / denom))
    assert abs(got - expected) < 1e-12


def test_psr_nan_when_n_below_2():
    assert np.isnan(psr(0.1, 1, skew=0.0, kurt=3.0))


def test_expected_max_sharpe_n2_v1():
    # N=2: q1=Φ⁻¹(0.5)=0；e_max = √V·γ·Φ⁻¹(1-1/(2e))
    got = expected_max_sharpe(sr_variance=1.0, n_trials=2)
    gamma = 0.5772156649015329
    q2 = norm.ppf(1.0 - 1.0 / (2.0 * np.e))
    expected = gamma * q2
    assert abs(got - expected) < 1e-12


def test_expected_max_sharpe_grows_with_n_trials():
    a = expected_max_sharpe(1.0, 10)
    b = expected_max_sharpe(1.0, 100)
    assert b > a > 0


def test_expected_max_sharpe_nan_guards():
    assert np.isnan(expected_max_sharpe(0.0, 10))  # V=0
    assert np.isnan(expected_max_sharpe(1.0, 1))  # N<2


def test_dsr_below_psr_because_benchmark_deflated():
    # DSR benchmark = expected_max_sharpe > 0，故 DSR < PSR(benchmark=0)
    sr, n = 0.15, 500
    base = psr(sr, n, skew=0.0, kurt=3.0, sr_benchmark=0.0)
    d = deflated_sharpe_ratio(sr, n, skew=0.0, kurt=3.0, sr_variance=0.01, n_trials=10)
    assert d < base


def _sharpe_col(x: np.ndarray) -> float:
    sd = x.std(ddof=1)
    return float(x.mean() / sd) if sd > 0 else float("nan")


def test_pbo_pure_noise_averages_near_half():
    # 純噪音（候選可交換）下 PBO 期望為 0.5；單次抽樣會抖，故對多組獨立矩陣取平均。
    vals = []
    for seed in range(50):
        m = np.random.default_rng(seed).standard_normal((2000, 12))
        vals.append(pbo_cscv(m, n_splits=8, sharpe_fn=_sharpe_col)["value"])
    assert 0.4 < float(np.mean(vals)) < 0.6


def test_pbo_one_dominant_near_zero():
    rng = np.random.default_rng(1)
    m = rng.standard_normal((2000, 8)) * 0.01
    m[:, 0] += 0.02  # 第 0 欄真實壓倒（穩定高均值）
    res = pbo_cscv(m, n_splits=8, sharpe_fn=_sharpe_col)
    assert res["value"] < 0.1  # 真實優勢 → 幾乎不過擬合


def test_pbo_nan_guards():
    m = np.random.default_rng(2).standard_normal((100, 1))
    assert np.isnan(pbo_cscv(m, n_splits=8, sharpe_fn=_sharpe_col)["value"])  # N<2
    m2 = np.random.default_rng(3).standard_normal((100, 4))
    assert np.isnan(pbo_cscv(m2, n_splits=7, sharpe_fn=_sharpe_col)["value"])  # 奇數 S
