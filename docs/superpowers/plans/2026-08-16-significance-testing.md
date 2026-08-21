# 統計嚴謹性補洞（DSR/PBO/置換檢定）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 為消融結論補多重檢定校正——Deflated Sharpe Ratio、PBO/CSCV、蒙地卡羅區塊置換檢定，讓「full 勝出」在搜尋次數校正後仍站得住。

**Architecture:** 純統計函式放 `backtest/significance.py`（與 `metrics.py` 同層，無 IO，RNG 由呼叫端傳入）；編排/落盤/CLI 放 `experiments/significance_report.py`（讀消融 run 目錄→產 `significance.json`）；`ablation.py` 多落 `cell_returns.parquet` 供 PBO。所有隨機性走 `cfg.seed`（INV-6）。

**Tech Stack:** Python、numpy、pandas、scipy.stats（norm）、pytest、uv、ruff format。

**規格對照：** `docs/superpowers/specs/2026-08-16-significance-testing-design.md`

---

## 檔案結構

| 檔案 | 建立/修改 | 職責 |
|------|-----------|------|
| `quantcore/config/schema.py` | 修改 | `StatsConfig` 新增 4 參數 + 偶數/存在性驗證 |
| `quantcore/config/default.yaml` / `canonical_ewma.yaml` / `canonical_dcc.yaml` | 修改 | 同步新參數 |
| `quantcore/backtest/significance.py` | 建立 | `psr` / `expected_max_sharpe` / `deflated_sharpe_ratio` / `pbo_cscv` / `permutation_test_paired` |
| `quantcore/experiments/ablation.py` | 修改 | 落 `cell_returns.parquet` |
| `quantcore/experiments/significance_report.py` | 建立 | 編排 + CLI，產 `significance.json` |
| `tests/test_config.py` | 修改 | config 新欄位 + 驗證 |
| `tests/test_backtest/test_significance.py` | 建立 | 純函式測試 |
| `tests/test_experiments/test_ablation.py` | 修改 | `cell_returns.parquet` schema/對齊 |
| `tests/test_experiments/test_significance_report.py` | 建立 | CLI 產物 + INV-6 |

---

## Task 1: Config 新增四參數

**Files:**
- Modify: `quantcore/config/schema.py:123-137`
- Modify: `quantcore/config/default.yaml:53-61`、`quantcore/config/canonical_ewma.yaml`、`quantcore/config/canonical_dcc.yaml`（各自 `stats:` 區塊）
- Test: `tests/test_config.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_config.py` 末尾加：

```python
def test_stats_significance_fields_load():
    from quantcore.config import load_config

    cfg = load_config("quantcore/config/default.yaml")
    assert cfg.stats.significance_strategy == "full"
    assert cfg.stats.psr_benchmark_sr == 0.0
    assert cfg.stats.pbo_n_splits == 16
    assert cfg.stats.mc_permutations == 1000


def test_pbo_n_splits_must_be_even():
    import pytest
    from pydantic import ValidationError

    from quantcore.config.schema import StatsConfig

    with pytest.raises(ValidationError):
        StatsConfig(
            bootstrap_mean_block=21,
            bootstrap_reps=1000,
            bootstrap_alpha=0.05,
            absmom_cash_threshold=0.10,
            subperiods=[(2005, 2009)],
            significance_strategy="full",
            psr_benchmark_sr=0.0,
            pbo_n_splits=15,  # 奇數 → 應拒絕
            mc_permutations=1000,
        )
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_config.py::test_stats_significance_fields_load tests/test_config.py::test_pbo_n_splits_must_be_even -v`
Expected: FAIL（欄位不存在 / 未拒絕奇數）

- [ ] **Step 3: 改 schema**

`quantcore/config/schema.py` 的 `StatsConfig`（在 `subperiods` 欄位後、`_subperiods_valid` 前）新增欄位：

```python
    significance_strategy: str = Field(min_length=1)  # DSR/PBO 鎖定的策略
    psr_benchmark_sr: float  # PSR 資訊性 benchmark（每期，非年化）
    pbo_n_splits: int = Field(ge=2)  # CSCV 塊數 S（偶數）
    mc_permutations: int = Field(ge=1)  # 置換次數
```

在既有 `_subperiods_valid` validator 之後新增：

```python
    @model_validator(mode="after")
    def _pbo_splits_even(self) -> StatsConfig:
        if self.pbo_n_splits % 2 != 0:
            raise ValueError(f"pbo_n_splits 須為偶數，得到 {self.pbo_n_splits}")
        return self
```

- [ ] **Step 4: 改三份 yaml**

三份檔的 `stats:` 區塊各加入（縮排對齊既有欄位）：

```yaml
  significance_strategy: full        # DSR/PBO 鎖定的策略
  psr_benchmark_sr: 0.0              # PSR 資訊性 benchmark（每期，非年化）
  pbo_n_splits: 16                   # CSCV 塊數 S（偶數）
  mc_permutations: 1000             # 蒙地卡羅置換次數
```

- [ ] **Step 5: 跑測試確認通過**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS（全部）

- [ ] **Step 6: Commit**

```bash
git add quantcore/config/schema.py quantcore/config/default.yaml quantcore/config/canonical_ewma.yaml quantcore/config/canonical_dcc.yaml tests/test_config.py
git commit -m "feat(config): StatsConfig 新增 significance/psr/pbo/mc 參數"
```

---

## Task 2: PSR / expected_max_sharpe / DSR 純函式

**Files:**
- Create: `quantcore/backtest/significance.py`
- Test: `tests/test_backtest/test_significance.py`

- [ ] **Step 1: 寫失敗測試**

建 `tests/test_backtest/test_significance.py`：

```python
"""significance 純函式測試（規格 §3）。"""

import numpy as np
from scipy.stats import norm

from quantcore.backtest.significance import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_significance.py -v`
Expected: FAIL（模組不存在）

- [ ] **Step 3: 實作**

建 `quantcore/backtest/significance.py`：

```python
"""穩健性顯著性檢定純函式（規格 §3；設計 2026-08-16）。

無檔案 IO；隨機性由呼叫端以 cfg.seed 建 Generator 傳入（INV-6）。
所有 Sharpe 一律以每期（非年化）值進入公式（Bailey & López de Prado 慣例）。
"""

from __future__ import annotations

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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/test_significance.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/significance.py tests/test_backtest/test_significance.py
git commit -m "feat(backtest): PSR/expected_max_sharpe/DSR 純函式"
```

---

## Task 3: PBO via CSCV 純函式

**Files:**
- Modify: `quantcore/backtest/significance.py`
- Test: `tests/test_backtest/test_significance.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_backtest/test_significance.py` 加：

```python
from quantcore.backtest.significance import pbo_cscv


def _sharpe_col(x: np.ndarray) -> float:
    sd = x.std(ddof=1)
    return float(x.mean() / sd) if sd > 0 else float("nan")


def test_pbo_pure_noise_near_half():
    rng = np.random.default_rng(0)
    m = rng.standard_normal((2000, 12))  # 12 個等價噪音候選
    res = pbo_cscv(m, n_splits=8, sharpe_fn=_sharpe_col)
    assert 0.3 < res["value"] < 0.7  # 無真實優勢 → PBO ≈ 0.5


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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_significance.py::test_pbo_pure_noise_near_half -v`
Expected: FAIL（`pbo_cscv` 不存在）

- [ ] **Step 3: 實作**

在 `significance.py` 頂部 import 補：

```python
from itertools import combinations
from math import log
```

於檔末新增：

```python
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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/test_significance.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/significance.py tests/test_backtest/test_significance.py
git commit -m "feat(backtest): PBO/CSCV 純函式"
```

---

## Task 4: 蒙地卡羅區塊置換檢定純函式

**Files:**
- Modify: `quantcore/backtest/significance.py`
- Test: `tests/test_backtest/test_significance.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_backtest/test_significance.py` 加：

```python
from quantcore.backtest.metrics import metric_sharpe
from quantcore.backtest.significance import permutation_test_paired


def test_permutation_identical_series_high_pvalue():
    r = np.random.default_rng(0).standard_normal(500) * 0.01
    rf = np.zeros(500)
    rng = np.random.default_rng(42)
    res = permutation_test_paired(r, r, rf, metric_sharpe, n_perms=200, mean_block=21, rng=rng)
    assert abs(res["observed"]) < 1e-12  # 同序列差異為 0
    assert res["p_value"] > 0.5


def test_permutation_strong_diff_low_pvalue():
    base = np.random.default_rng(1).standard_normal(1000) * 0.01
    a = base + 0.003  # a 明顯優
    b = base
    rf = np.zeros(1000)
    rng = np.random.default_rng(7)
    res = permutation_test_paired(a, b, rf, metric_sharpe, n_perms=500, mean_block=21, rng=rng)
    assert res["observed"] > 0
    assert res["p_value"] < 0.05


def test_permutation_deterministic_under_seed():
    a = np.random.default_rng(2).standard_normal(300) * 0.01
    b = np.random.default_rng(3).standard_normal(300) * 0.01
    rf = np.zeros(300)
    r1 = permutation_test_paired(
        a, b, rf, metric_sharpe, 100, 21, np.random.default_rng(99)
    )
    r2 = permutation_test_paired(
        a, b, rf, metric_sharpe, 100, 21, np.random.default_rng(99)
    )
    assert r1 == r2
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_significance.py::test_permutation_identical_series_high_pvalue -v`
Expected: FAIL（`permutation_test_paired` 不存在）

- [ ] **Step 3: 實作**

於 `significance.py` 檔末新增：

```python
def _block_swap_mask(n: int, mean_block: int, rng) -> np.ndarray:
    """長度 n 的布林遮罩：以平均塊長 mean_block 分塊，每塊獨立擲幣決定是否對調。

    尊重自相關（與 stationary bootstrap 一致的塊長概念）；塊起點以機率
    1/mean_block 開新塊，開塊時重擲該塊的 swap 決定。
    """
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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/test_significance.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/significance.py tests/test_backtest/test_significance.py
git commit -m "feat(backtest): 蒙地卡羅區塊置換檢定純函式"
```

---

## Task 5: ablation 落 `cell_returns.parquet`

**Files:**
- Modify: `quantcore/experiments/ablation.py`（`_evaluate` 與 `run_ablation`）
- Test: `tests/test_experiments/test_ablation.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_experiments/test_ablation.py` 末尾加（沿用該檔既有 `cfg`/`snap` fixture 慣例；若該檔用區域建構，仿最近一個測試的建法）：

```python
def test_cell_returns_parquet_written_and_aligned(tmp_path):
    from quantcore.experiments.ablation import run_ablation
    from tests.test_experiments.test_ablation import _cfg, _snap  # 若已有 helper；否則仿現有測試就地建 cfg/snap

    cfg = _cfg()
    snap = _snap()
    run_dir = run_ablation(
        cfg, snap, ["full", "mom_ivol"], {"signal.top_k": [3, 5]}, tmp_path, "test"
    )
    cr = pd.read_parquet(run_dir / "cell_returns.parquet")
    assert set(cr.columns) == {"cell_label", "strategy_id", "date", "ret"}
    # 各 (cell_label, strategy_id) 等長（同 clock 對齊）
    lengths = cr.groupby(["cell_label", "strategy_id"]).size().unique()
    assert len(lengths) == 1
```

> 註：實作前先讀 `tests/test_experiments/test_ablation.py` 現有 fixture 建法，用同一套建 `cfg`/`snap`，不要引入新 fixture。上面的 import 只是佔位示意。

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_experiments/test_ablation.py::test_cell_returns_parquet_written_and_aligned -v`
Expected: FAIL（無 `cell_returns.parquet`）

- [ ] **Step 3: 改 `_evaluate` 回傳報酬，`run_ablation` 落盤**

把 `ablation.py` 的 `_evaluate` 改為同時回傳每策略日報酬（不重跑策略，共用同一次 `run_strategy`）：

```python
def _evaluate(
    cfg: QuantConfig, snapshot: dict, strategy_ids: list[str]
) -> tuple[dict[str, dict], dict[str, pd.DataFrame]]:
    """跑指定策略，回 ({sid: metrics}, {sid: DataFrame[date, ret]})。in-memory。"""
    clock, strategies = _build_clock(cfg, snapshot, strategy_ids)
    metrics_out: dict[str, dict] = {}
    returns_out: dict[str, pd.DataFrame] = {}
    for s in strategies:
        nav_df, _w, _dec, _tr = run_strategy(snapshot, clock, s, cfg)
        rate = _daily_rate(snapshot, nav_df["date"])
        metrics_out[s.strategy_id] = compute_metrics(
            nav=nav_df["nav"].reset_index(drop=True),
            rate_daily=rate.reset_index(drop=True),
            total_turnover=float(nav_df["turnover"].sum()),
            total_cost=float(nav_df["cost"].sum()),
            weights=_w,
        )
        ret = nav_df["nav"].pct_change().fillna(0.0)
        returns_out[s.strategy_id] = pd.DataFrame(
            {"date": nav_df["date"].to_numpy(), "ret": ret.to_numpy()}
        )
    return metrics_out, returns_out
```

在 `run_ablation` 的 cell 迴圈裡改用新回傳並收集報酬列：

```python
    table_rows: list[dict] = []
    return_rows: list[pd.DataFrame] = []
    failed_cells: list[dict] = []
    for cell_label, cfg_dict in _build_cells(base_raw, param_grid):
        try:
            cfg = QuantConfig.model_validate(cfg_dict)
        except ValidationError as e:
            failed_cells.append({"cell_label": cell_label, "error": f"{type(e).__name__}: {e}"})
            print(f"[消融] 略過無效格 {cell_label!r}：{type(e).__name__}")
            continue
        metrics_map, returns_map = _evaluate(cfg, snapshot, strategy_ids)
        for sid, metrics in metrics_map.items():
            table_rows.append({"cell_label": cell_label, "strategy_id": sid, **metrics})
        for sid, rdf in returns_map.items():
            rdf = rdf.assign(cell_label=cell_label, strategy_id=sid)
            return_rows.append(rdf[["cell_label", "strategy_id", "date", "ret"]])
```

> 注意：原本迴圈用的變數名為 `rows`，改名為 `table_rows`；下方 `table = pd.DataFrame(rows)` 同步改為 `table = pd.DataFrame(table_rows)`。

在寫 `comparison.parquet` 之後、`_baseline_bootstrap` 之前落新檔：

```python
    if return_rows:
        pd.concat(return_rows, ignore_index=True).to_parquet(
            run_dir / "cell_returns.parquet", index=False
        )
```

- [ ] **Step 4: 跑測試確認通過（含既有 ablation 測試不回歸）**

Run: `uv run pytest tests/test_experiments/test_ablation.py -v`
Expected: PASS（全部，含既有）

- [ ] **Step 5: Commit**

```bash
git add quantcore/experiments/ablation.py tests/test_experiments/test_ablation.py
git commit -m "feat(experiments): ablation 落 cell_returns.parquet 供 PBO"
```

---

## Task 6: `significance_report.py` 編排 + CLI

**Files:**
- Create: `quantcore/experiments/significance_report.py`
- Test: `tests/test_experiments/test_significance_report.py`

- [ ] **Step 1: 寫失敗測試**

建 `tests/test_experiments/test_significance_report.py`：

```python
"""significance_report CLI 產物 + INV-6 測試。"""

import json

import pandas as pd

from quantcore.config import load_config
from quantcore.data.snapshot import load_snapshot
from quantcore.experiments.ablation import run_ablation
from quantcore.experiments.significance_report import build_significance_report


def _make_ablation_run(tmp_path):
    cfg = load_config("quantcore/config/default.yaml")
    snap = load_snapshot(cfg.snapshot)
    run_dir = run_ablation(
        cfg, snap, ["full", "mom_ivol"], {"signal.top_k": [3, 5]}, tmp_path, "sig"
    )
    return cfg, snap, run_dir


def test_significance_json_schema(tmp_path):
    cfg, snap, run_dir = _make_ablation_run(tmp_path)
    out = build_significance_report(cfg, snap, run_dir)
    data = json.loads((run_dir / "significance.json").read_text(encoding="utf-8"))
    assert data == out
    assert set(data) == {"provenance", "dsr", "pbo", "permutation"}
    assert data["provenance"]["N"] >= 2
    assert data["dsr"]["strategy"] == "full"
    assert set(data["dsr"]) >= {"sr", "psr", "expected_max_sr", "dsr", "n_days", "skew", "kurt"}
    assert data["pbo"]["n_candidates"] == data["provenance"]["N"]
    assert isinstance(data["permutation"], list) and len(data["permutation"]) >= 1


def test_significance_reproducible(tmp_path):
    cfg, snap, run_dir = _make_ablation_run(tmp_path)
    build_significance_report(cfg, snap, run_dir)
    first = (run_dir / "significance.json").read_bytes()
    build_significance_report(cfg, snap, run_dir)
    second = (run_dir / "significance.json").read_bytes()
    assert first == second  # INV-6：同 seed 位元一致
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_experiments/test_significance_report.py -v`
Expected: FAIL（模組不存在）

- [ ] **Step 3: 實作**

建 `quantcore/experiments/significance_report.py`：

```python
"""消融顯著性檢定編排 + CLI（規格 §3、§5.2；設計 2026-08-16）。

讀一個消融 run 目錄（comparison.parquet + cell_returns.parquet + manifest.json），
自動數 N、算目標策略 DSR、PBO（鎖定該策略、以消融格為候選集）、full vs 各殘缺版
的置換 p-value，落 significance.json。隨機性走 cfg.seed（INV-6）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, skew

from quantcore.backtest.metrics import metric_calmar, metric_sharpe
from quantcore.backtest.significance import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    pbo_cscv,
    permutation_test_paired,
    psr,
)
from quantcore.config import QuantConfig, load_config
from quantcore.data.snapshot import load_snapshot

_DAYS_PER_YEAR = 252


def _per_period_sr(excess: np.ndarray) -> float:
    sd = excess.std(ddof=1)
    return float(excess.mean() / sd) if sd > 0 else float("nan")


def _sharpe_col(x: np.ndarray) -> float:
    sd = x.std(ddof=1)
    return float(x.mean() / sd) if sd > 0 else float("nan")


def _daily_rf(snapshot: dict, dates: pd.Series) -> np.ndarray:
    return (
        snapshot["rates"].set_index("date")["DTB3"].reindex(dates).ffill().bfill().to_numpy()
        / 100.0
        / _DAYS_PER_YEAR
    )


def build_significance_report(cfg: QuantConfig, snapshot: dict, run_dir: str | Path) -> dict:
    """算 DSR/PBO/置換並落 significance.json，回傳同一 dict。"""
    run_dir = Path(run_dir)
    target = cfg.stats.significance_strategy
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    comp = pd.read_parquet(run_dir / "comparison.parquet")
    cell_ret = pd.read_parquet(run_dir / "cell_returns.parquet")

    cells = list(comp["cell_label"].unique())
    n_trials = len(cells)

    # --- DSR：目標策略 baseline 格的每期 SR + 各格 SR 橫斷面變異 ---
    tgt = cell_ret[cell_ret["strategy_id"] == target]
    base = tgt[tgt["cell_label"] == "baseline"].sort_values("date")
    rf = _daily_rf(snapshot, base["date"])
    excess = base["ret"].to_numpy() - rf
    sr = _per_period_sr(excess)
    n_days = int(len(excess))
    sk = float(skew(excess))
    ku = float(kurtosis(excess, fisher=False))  # 非超額
    cell_srs = []
    for cl in cells:
        sub = tgt[tgt["cell_label"] == cl].sort_values("date")
        e = sub["ret"].to_numpy() - _daily_rf(snapshot, sub["date"])
        cell_srs.append(_per_period_sr(e))
    sr_var = float(np.nanvar(np.asarray(cell_srs), ddof=1)) if n_trials > 1 else 0.0
    dsr = {
        "strategy": target,
        "sr": sr,
        "psr": psr(sr, n_days, sk, ku, cfg.stats.psr_benchmark_sr),
        "expected_max_sr": expected_max_sharpe(sr_var, n_trials),
        "dsr": deflated_sharpe_ratio(sr, n_days, sk, ku, sr_var, n_trials),
        "n_days": n_days,
        "skew": sk,
        "kurt": ku,
        "sr_variance": sr_var,
    }

    # --- PBO：目標策略各格日報酬矩陣 T×N ---
    wide = (
        tgt.pivot_table(index="date", columns="cell_label", values="ret")
        .sort_index()
        .dropna()
    )
    pbo = pbo_cscv(wide.to_numpy(), cfg.stats.pbo_n_splits, _sharpe_col)

    # --- 置換：full vs baseline 格各其他策略 ---
    base_ret = cell_ret[cell_ret["cell_label"] == "baseline"]
    strategies = [s for s in base_ret["strategy_id"].unique() if s != target]
    tgt_base = base_ret[base_ret["strategy_id"] == target].sort_values("date")
    ra = tgt_base["ret"].to_numpy()
    rf_a = _daily_rf(snapshot, tgt_base["date"])
    rng = np.random.default_rng(cfg.seed)  # INV-6
    perm = []
    for sid in sorted(strategies):
        sub = base_ret[base_ret["strategy_id"] == sid].sort_values("date")
        rb = sub["ret"].to_numpy()
        for mname, mfn in (("sharpe", metric_sharpe), ("calmar", metric_calmar)):
            res = permutation_test_paired(
                ra, rb, rf_a, mfn, cfg.stats.mc_permutations, cfg.stats.bootstrap_mean_block, rng
            )
            perm.append({"vs": sid, "metric": mname, **res})

    report = {
        "provenance": {
            "git_commit": manifest.get("git_commit"),
            "config_hash": manifest.get("config_hash"),
            "snapshot_id": manifest.get("snapshot_id"),
            "N": n_trials,
        },
        "dsr": dsr,
        "pbo": pbo,
        "permutation": perm,
    }
    (run_dir / "significance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def _cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m quantcore.experiments.significance_report")
    p.add_argument("--config", required=True)
    p.add_argument("--run-dir", required=True, help="消融 run 目錄")
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    snapshot = load_snapshot(cfg.snapshot)
    report = build_significance_report(cfg, snapshot, args.run_dir)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"DSR={report['dsr']['dsr']:.4f}  PBO={report['pbo']['value']:.4f}")
    print(f"significance.json 已寫入：{args.run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_experiments/test_significance_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/experiments/significance_report.py tests/test_experiments/test_significance_report.py
git commit -m "feat(experiments): significance_report 編排+CLI，產 significance.json"
```

---

## Task 7: 全套回歸 + 不變量 + 格式

**Files:** 無新增；驗證關卡。

- [ ] **Step 1: 跑不變量（INV-1~6 不得回歸）**

Run: `uv run pytest tests/test_invariants/ -v`
Expected: PASS（全綠）

- [ ] **Step 2: 跑全測試**

Run: `uv run pytest -q`
Expected: PASS（全綠，無回歸）

- [ ] **Step 3: ruff format + lint**

Run: `uv run ruff format quantcore tests && uv run ruff check quantcore tests`
Expected: 無變更待提交 / 無 lint 錯誤

- [ ] **Step 4: 真快照冒煙（可選但建議）**

Run: `uv run python -m quantcore.experiments.ablation --config quantcore/config/default.yaml --label sig_smoke` 然後 `uv run python -m quantcore.experiments.significance_report --config quantcore/config/default.yaml --run-dir <上一步 run 目錄>`
Expected: 印出 `DSR=... PBO=...`，`significance.json` 產出且欄位完整

- [ ] **Step 5: Commit（若 format 有動）**

```bash
git add -A
git commit -m "chore: ruff format + 全測試綠（significance 補洞）"
```

---

## 自我檢查結論

- **Spec 覆蓋**：§3.1 DSR→Task 2；§3.2 PBO→Task 3；§3.3 置換→Task 4；§4 config→Task 1；§5.1 cell_returns→Task 5；§5.2 significance.json→Task 6；§6 測試分散於各 Task + Task 7 收斂。
- **型別一致**：`psr/expected_max_sharpe/deflated_sharpe_ratio/pbo_cscv/permutation_test_paired` 簽章跨 Task 一致；`_evaluate` 回傳改 tuple 後所有呼叫端（僅 `run_ablation`）同步更新。
- **無 placeholder**：所有程式步驟含完整程式碼；Task 5 fixture 建法標註「實作前讀既有測試對齊」為唯一需就地確認處（因該檔 fixture 慣例需現場核對，非可預先固定的內容）。
