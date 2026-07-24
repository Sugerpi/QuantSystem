# Phase 4c — Block Bootstrap + 七策略消融 + AC 量測 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收割 Phase 4 剩餘 AC——抽 `momentum_select` 共用（消融地基）、`metrics.py` 加 stationary block bootstrap（CI + 配對差異檢定）與平均曝險、子期間分析、σ*±2% 條件式量測、七策略 × §7.3 參數格消融全表（真實快照，本機閘門）。

**Architecture:** bootstrap/子期間/AC 量測皆純函數或讀 run 產物的模組（不重跑回測）；消融沿用既有 `run_ablation` 通用引擎、baseline 格外加 `full` vs 各消融版的配對差異 CI。所有隨機性走 `cfg.seed` 單一 RNG（INV-6）。

**Tech Stack:** Python 3.11、numpy、pandas、pytest。

**規格/設計來源：** `DEVELOPMENT_GUIDE v1.2.md` §6.3/§6.4/§7.3/§9；設計文件 `docs/superpowers/specs/2026-07-22-phase4c-bootstrap-ablation-design.md`。

**重要背景（給零脈絡的實作者）：**
- 依賴方向（CLAUDE.md）：`config ← data ← models ← signals/portfolio ← backtest ← experiments`。
- 既有：
  - `backtest/metrics.py`：`annualized_return/sharpe(ret,rf)/sortino/max_drawdown(nav)/calmar(nav)/annualized_turnover/compute_metrics(nav, rate_daily, total_turnover, total_cost)`。`_DAYS_PER_YEAR=252`。sharpe 收 pd.Series。無 bootstrap、無 average_exposure。
  - `backtest/accounting.py`：`CASH`（現金鍵字串）。
  - `experiments/ablation.py`：`run_ablation(base_cfg, snapshot, strategy_ids, param_grid, out_root, label, now=None)`；`_build_cells(base_raw, param_grid)`（baseline + 每 (key,value)，**不去重**）；`_evaluate(cfg, snapshot, strategy_ids) -> {sid: metrics}`（以全策略 warmup 最大值建單一 EventClock，跑 `run_strategy` 得 `(nav_df, w_df, d_df)`）；`_write_manifest`。`run_strategy` 回 `(nav[date,strategy_id,nav,turnover,cost], weights[date,strategy_id,ticker,weight], decisions)`。
  - `experiments/runner.py::run_experiment`：跑策略、`_flatten_decisions` 攤平、`write_artifacts` 落 nav/weights/decisions/metrics.json；`compute_metrics` 呼叫未傳 weights。
  - `backtest/strategies/momentum_base.py::MomentumStrategy.decide`：eligible→動量→取 K→absmom 序列（與 `Full._select_and_weight` 逐字重複，有交叉引用註解 + 等價回歸測試 `test_full_and_mom_ivol_share_selection_layer`）。
  - `backtest/strategies/full.py::Full._select_and_weight`、`vol_target_base.py`（`forecast_selected`/`ticker_returns`）。
  - `portfolio/selection.py::{eligible_assets, select_top_k}`、`signals/momentum.py::{cross_sectional_momentum, absolute_momentum}`。
  - `config/schema.py`：root `QuantConfig`（欄位 snapshot/seed/universe/signal/risk/schedule/costs/data_quality/backtest）。`ge/gt` 等 pydantic Field 慣例。
  - `tests/fixtures/synthetic.py`：`make_cfg/make_dates/make_snapshot`。快照本機閘門用 `requires_snapshot` marker（`tests/conftest.py`，以 `prices/rates.parquet` 齊全判定）。
- 硬性規則：參數只在 config；commit 訊息繁中、conventional-commit、附 Co-Authored-By trailer。TDD。每 task 後 `uv run pytest -q` 全綠、ruff 乾淨。
- 基線：全套 **272 passed**。

## 檔案結構

| 檔案 | 責任 | 動作 |
|------|------|------|
| `quantcore/backtest/strategies/momentum_selection.py` | `momentum_select` 共用選擇 | 新增 |
| `quantcore/backtest/strategies/momentum_base.py` | decide 改呼叫 momentum_select | 修改 |
| `quantcore/backtest/strategies/full.py` | `_select_and_weight` 改呼叫 momentum_select | 修改 |
| `quantcore/config/schema.py` | `StatsConfig` + root 掛載 | 修改 |
| `quantcore/config/default.yaml` | `stats:` 區塊 | 修改 |
| `quantcore/backtest/metrics.py` | bootstrap 索引/CI/配對差異、average_exposure、subperiods | 修改 |
| `quantcore/experiments/runner.py` | compute_metrics 接 weights | 修改 |
| `quantcore/experiments/ablation.py` | _evaluate 接 weights + baseline 配對 bootstrap 落盤 | 修改 |
| `quantcore/experiments/vol_target_ac.py` | σ*±2% 條件式量測（讀 run 產物） | 新增 |
| `tests/test_backtest/test_momentum_selection.py` | 選擇共用 | 新增 |
| `tests/test_backtest/test_metrics_bootstrap.py` | bootstrap/CI/配對/曝險/subperiod | 新增 |
| `tests/test_experiments/test_vol_target_ac.py` | AC 量測 | 新增 |
| `tests/test_config.py` | stats 驗證 | 修改 |

---

## Task 1: 抽 `momentum_select` 共用（還 4b-2 backlog）

**Files:**
- Create: `quantcore/backtest/strategies/momentum_selection.py`
- Modify: `quantcore/backtest/strategies/momentum_base.py`、`quantcore/backtest/strategies/full.py`
- Test: `tests/test_backtest/test_momentum_selection.py`

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_backtest/test_momentum_selection.py`：

```python
"""momentum_select 共用選擇：full/mom_only/mom_ivol 的唯一選標的實作。"""

from __future__ import annotations

import numpy as np

from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategies.momentum_selection import MomentumSelection, momentum_select
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def _snap(n=320):
    dates = make_dates(n)
    rng = np.random.default_rng(2)
    prices = {tk: list(100 * np.cumprod(1 + rng.normal(0.0003 * (i + 1), 0.01, n)))
              for i, tk in enumerate(["A", "B", "C", "D"])}
    return make_snapshot(prices, dates), dates


def _cfg():
    return make_cfg(
        ["A", "B", "C", "D"],
        signal={"top_k": 2, "momentum_lookback": 120, "momentum_skip": 5},
        universe={"min_history_days": 130},
    )


def test_momentum_select_returns_expected_shape():
    snap, dates = _snap()
    sel = momentum_select(make_view(snap, dates[300]), _cfg())
    assert isinstance(sel, MomentumSelection)
    assert set(sel.selected) <= set(sel.eligible)
    assert len(sel.selected) == 2
    assert set(sel.absmom) == set(sel.selected)
    assert set(sel.scores) <= {"A", "B", "C", "D"}  # 全體合格資產分數


def test_momentum_select_none_when_no_eligible():
    # 資料不足 min_history_days → 無合格資產 → None
    dates = make_dates(50)
    snap = make_snapshot({"A": list(100 + np.arange(50.0))}, dates)
    cfg = make_cfg(["A"], signal={"top_k": 1, "momentum_lookback": 40}, universe={"min_history_days": 200})
    assert momentum_select(make_view(snap, dates[49]), cfg) is None
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_backtest/test_momentum_selection.py -v`
Expected: FAIL（ModuleNotFoundError）。

- [ ] **Step 3: 實作 momentum_selection.py**

Create `quantcore/backtest/strategies/momentum_selection.py`：

```python
"""共用選標的序列（規格 §1.3/§1.4/§6.2）。full/mom_only/mom_ivol 的唯一實作。

抽出前為 MomentumStrategy.decide 與 Full._select_and_weight 兩份逐字複本；
消融是 Phase 4 的科學交付物，選擇一致性應由結構保證（apples-to-apples）。
"""

from __future__ import annotations

from dataclasses import dataclass

from quantcore.backtest.ptview import PointInTimeView
from quantcore.config import QuantConfig
from quantcore.portfolio.selection import eligible_assets, select_top_k
from quantcore.signals.momentum import absolute_momentum, cross_sectional_momentum


@dataclass(frozen=True)
class MomentumSelection:
    eligible: list[str]
    scores: dict[str, float]      # 全體合格資產的 12-1 分數（不只前 K）
    selected: list[str]
    absmom: dict[str, bool]       # 入選資產的絕對動量 pass/fail


def momentum_select(view: PointInTimeView, cfg: QuantConfig) -> MomentumSelection | None:
    """eligible→動量→取 K→absmom。無合格資產回 None。"""
    elig = eligible_assets(view.prices, cfg.universe.menu, cfg.universe.min_history_days)
    scores = cross_sectional_momentum(
        view.prices, cfg.signal.momentum_lookback, cfg.signal.momentum_skip
    )
    scores = {t: v for t, v in scores.items() if t in elig}
    if not scores:
        return None
    selected = select_top_k(scores, cfg.signal.top_k)
    absmom_all = absolute_momentum(view.prices, view.rates, cfg.signal.momentum_lookback)
    absmom = {t: bool(absmom_all.get(t, False)) for t in selected}
    return MomentumSelection(eligible=elig, scores=scores, selected=selected, absmom=absmom)
```

- [ ] **Step 4: 改 `momentum_base.py` 用 momentum_select**

在 `MomentumStrategy.decide`：把 eligible→動量→取 K→absmom 那段（含交叉引用註解）替換為：

```python
        sel = momentum_select(view, self._cfg)
        if sel is None:
            return None
        elig, scores, selected, absmom = sel.eligible, sel.scores, sel.selected, sel.absmom
        w_risky, sigma_hat = self._risky_weights(selected, view)
        garch_params, fell_back = self._vol_diagnostics(selected)
        weights, cash = route_absmom_to_cash(w_risky, absmom)
```

（保留其後 `target`/`Decision`/`Diagnostics` 組裝不變；移除原本的 `eligible_assets`/`cross_sectional_momentum`/`select_top_k`/`absolute_momentum` import 若已不再使用，並 import `momentum_select`。）

- [ ] **Step 5: 改 `full.py` 用 momentum_select**

在 `Full._select_and_weight`：把選標的段替換為：

```python
        sel = momentum_select(view, self._cfg)
        if sel is None:
            return None
        sigma_hat, garch_params, fell_back = forecast_selected(
            self._forecaster, view, sel.selected
        )
        w_risky = inverse_vol(sigma_hat)
        return RiskyState(
            eligible=sel.eligible,
            selected=sel.selected,
            momentum_scores=sel.scores,
            w_risky=w_risky,
            sigma_hat=sigma_hat,
            absmom=sel.absmom,
            garch_params=garch_params,
            fell_back=fell_back,
        )
```

（移除 full.py 不再使用的 `eligible_assets`/`select_top_k`/`cross_sectional_momentum`/`absolute_momentum` import 與交叉引用註解；import `momentum_select`。）

- [ ] **Step 6: 執行確認通過**

Run: `uv run pytest tests/test_backtest/test_momentum_selection.py tests/test_backtest/test_full.py tests/test_backtest/test_mom_strategies.py -v`
Expected: 全 PASS（含既有等價測試 `test_full_and_mom_ivol_share_selection_layer` 仍綠——此後為結構性事實的防呆守護）。

- [ ] **Step 7: 全測試綠 + lint**

Run: `uv run pytest -q` 與 `uv run ruff check quantcore/backtest tests/test_backtest` + `uv run ruff format --check quantcore/backtest tests/test_backtest`
Expected: 綠、乾淨。

- [ ] **Step 8: Commit**

```bash
git add quantcore/backtest/strategies/momentum_selection.py quantcore/backtest/strategies/momentum_base.py quantcore/backtest/strategies/full.py tests/test_backtest/test_momentum_selection.py
git commit -m "refactor(strategies): 抽 momentum_select 共用（消融選擇由結構保證一致）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `StatsConfig`（config）

**Files:**
- Modify: `quantcore/config/schema.py`
- Modify: `quantcore/config/default.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_config.py` 末尾加：

```python
def test_stats_config_loaded():
    cfg = load_config("quantcore/config/default.yaml")
    assert cfg.stats.bootstrap_mean_block == 21
    assert cfg.stats.bootstrap_reps == 1000
    assert cfg.stats.bootstrap_alpha == 0.05
    assert cfg.stats.absmom_cash_threshold == 0.10
    assert [tuple(p) for p in cfg.stats.subperiods] == [(2005, 2009), (2010, 2019), (2020, 9999)]


def test_stats_subperiod_start_le_end():
    import pytest
    from tests.fixtures.synthetic import make_cfg

    with pytest.raises(Exception):
        make_cfg(["SPY"], stats={"subperiods": [[2020, 2010]]})  # start > end
```

（`make_cfg` 只支援已存在的區塊淺合併；若 `stats` 區塊需覆寫，確認 `make_cfg` 能處理——它對 `raw[section].update(values)`，`stats` 為 dict 區塊可用。）

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_config.py::test_stats_config_loaded -v`
Expected: FAIL。

- [ ] **Step 3: 加 schema**

在 `quantcore/config/schema.py` 加入 `StatsConfig` 類別（置於其他 config 類別附近）：

```python
class StatsConfig(_Strict):
    """績效統計參數（規格 §6.4）。"""

    bootstrap_mean_block: int = Field(ge=1)   # stationary bootstrap 平均塊長（交易日）
    bootstrap_reps: int = Field(ge=1)         # 重抽次數
    bootstrap_alpha: float = Field(gt=0, lt=1)  # 百分位 CI 雙尾水準
    absmom_cash_threshold: float = Field(ge=0, le=1)  # full 的 σ* 量測納入閾值
    subperiods: list[tuple[int, int]] = Field(min_length=1)  # (start_year, end_year) 含

    @model_validator(mode="after")
    def _subperiods_valid(self) -> StatsConfig:
        for start, end in self.subperiods:
            if start > end:
                raise ValueError(f"子期間 start({start}) > end({end})")
        return self
```

在 `QuantConfig` 加欄位 `stats: StatsConfig`（置於 `backtest` 之後）。

- [ ] **Step 4: 加 default.yaml**

在 `quantcore/config/default.yaml` 末尾加：

```yaml
stats:                               # §6.4 績效統計參數
  bootstrap_mean_block: 21           # stationary bootstrap 平均塊長（交易日）
  bootstrap_reps: 1000               # 重抽次數
  bootstrap_alpha: 0.05              # 百分位 CI 雙尾水準
  absmom_cash_threshold: 0.10        # full 的 σ* 量測納入閾值（absmom 轉現金比例上限）
  subperiods:                        # 子期間切點（起始年，含）
    - [2005, 2009]
    - [2010, 2019]
    - [2020, 9999]
```

- [ ] **Step 5: 執行確認通過 + 全測試綠 + lint**

Run: `uv run pytest tests/test_config.py -v`、`uv run pytest -q`、`uv run ruff check quantcore/config tests` + `uv run ruff format --check quantcore/config tests`
Expected: 綠、乾淨。

- [ ] **Step 6: Commit**

```bash
git add quantcore/config/schema.py quantcore/config/default.yaml tests/test_config.py
git commit -m "feat(config): 新增 stats 區塊（bootstrap/子期間/absmom 閾值，§6.4）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Stationary bootstrap 索引

**Files:**
- Modify: `quantcore/backtest/metrics.py`
- Test: `tests/test_backtest/test_metrics_bootstrap.py`

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_backtest/test_metrics_bootstrap.py`：

```python
"""Stationary block bootstrap 索引：形狀、界限、決定性、塊結構。"""

from __future__ import annotations

import numpy as np

from quantcore.backtest.metrics import stationary_bootstrap_indices


def test_indices_shape_and_bounds():
    rng = np.random.default_rng(42)
    idx = stationary_bootstrap_indices(n=200, mean_block=21, n_reps=50, rng=rng)
    assert idx.shape == (50, 200)
    assert idx.min() >= 0 and idx.max() < 200


def test_indices_deterministic_given_seed():
    a = stationary_bootstrap_indices(200, 21, 50, np.random.default_rng(7))
    b = stationary_bootstrap_indices(200, 21, 50, np.random.default_rng(7))
    assert np.array_equal(a, b)


def test_block_structure_continuation_ratio():
    # 連續（idx[t] == idx[t-1]+1 mod n）的比例應約 1 − 1/mean_block
    rng = np.random.default_rng(1)
    n, mb = 5000, 21
    idx = stationary_bootstrap_indices(n, mb, 20, rng)
    cont = 0
    total = 0
    for r in range(idx.shape[0]):
        for t in range(1, n):
            total += 1
            if idx[r, t] == (idx[r, t - 1] + 1) % n:
                cont += 1
    ratio = cont / total
    assert abs(ratio - (1 - 1 / mb)) < 0.03
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_backtest/test_metrics_bootstrap.py -v`
Expected: FAIL（無 `stationary_bootstrap_indices`）。

- [ ] **Step 3: 實作**

在 `quantcore/backtest/metrics.py` 加（檔頭已 import numpy as np）：

```python
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
            if rng.random() < p:
                i = int(rng.integers(0, n))
            else:
                i = (i + 1) % n
            idx[r, t] = i
    return idx
```

- [ ] **Step 4: 執行確認通過 + 全測試綠 + lint**

Run: `uv run pytest tests/test_backtest/test_metrics_bootstrap.py -v`、`uv run pytest -q`、`uv run ruff check quantcore/backtest tests/test_backtest` + format check
Expected: 綠、乾淨。

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/metrics.py tests/test_backtest/test_metrics_bootstrap.py
git commit -m "feat(metrics): stationary block bootstrap 索引（§6.4，INV-6 seeded）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Bootstrap CI + 配對差異檢定

**Files:**
- Modify: `quantcore/backtest/metrics.py`
- Test: `tests/test_backtest/test_metrics_bootstrap.py`（續加）

**設計要點：** metric adapters 收 numpy 報酬陣列。Sharpe 用報酬 + rf；Calmar 由報酬重建 NAV（`nav = [1, cumprod(1+r)...]`）。配對差異對**同一組索引**重抽兩序列取差。

- [ ] **Step 1: 續寫失敗測試**

在 `tests/test_backtest/test_metrics_bootstrap.py` 加：

```python
from quantcore.backtest.metrics import (
    bootstrap_metric_ci,
    metric_calmar,
    metric_sharpe,
    paired_metric_diff_ci,
)


def _rf(n):
    return np.full(n, 0.0001)


def test_metric_adapters_finite():
    rng = np.random.default_rng(0)
    r = rng.normal(0.0005, 0.01, 500)
    assert np.isfinite(metric_sharpe(r, _rf(500)))
    assert np.isfinite(metric_calmar(r, _rf(500)))


def test_ci_brackets_point_for_noisy_series():
    rng = np.random.default_rng(3)
    r = rng.normal(0.0005, 0.01, 500)
    idx = stationary_bootstrap_indices(500, 21, 500, np.random.default_rng(9))
    point, lo, hi = bootstrap_metric_ci(r, _rf(500), metric_sharpe, idx)
    assert lo <= point <= hi
    assert lo < hi


def test_paired_diff_identical_series_ci_contains_zero():
    rng = np.random.default_rng(5)
    r = rng.normal(0.0005, 0.01, 500)
    idx = stationary_bootstrap_indices(500, 21, 500, np.random.default_rng(11))
    res = paired_metric_diff_ci(r, r.copy(), _rf(500), metric_sharpe, idx)
    # 配對性守護：相同序列 → 逐次差異恆為 0（若誤用獨立抽樣，差異會有雜訊、CI 不退化）
    assert res["point"] == 0.0
    assert res["lo"] == 0.0 and res["hi"] == 0.0
    assert res["excludes_zero"] is False


def test_paired_diff_shifted_series_excludes_zero():
    rng = np.random.default_rng(6)
    ra = rng.normal(0.001, 0.01, 800)   # 較高報酬
    rb = ra - 0.0008                     # 逐項下移 → Sharpe 較低
    idx = stationary_bootstrap_indices(800, 21, 800, np.random.default_rng(13))
    res = paired_metric_diff_ci(ra, rb, _rf(800), metric_sharpe, idx)
    assert res["point"] > 0
    assert res["excludes_zero"] is True


def test_bootstrap_ci_deterministic():
    rng = np.random.default_rng(2)
    r = rng.normal(0.0005, 0.01, 300)
    i1 = stationary_bootstrap_indices(300, 21, 300, np.random.default_rng(1))
    i2 = stationary_bootstrap_indices(300, 21, 300, np.random.default_rng(1))
    assert bootstrap_metric_ci(r, _rf(300), metric_sharpe, i1) == bootstrap_metric_ci(
        r, _rf(300), metric_sharpe, i2
    )
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_backtest/test_metrics_bootstrap.py -k "adapter or ci or paired" -v`
Expected: FAIL。

- [ ] **Step 3: 實作**

在 `quantcore/backtest/metrics.py` 加：

```python
def _nav_from_returns(r: np.ndarray) -> pd.Series:
    """由日報酬重建 NAV（起始 1.0）。供 Calmar/MaxDD 的 bootstrap 一致計算。"""
    return pd.Series(np.concatenate([[1.0], np.cumprod(1.0 + np.asarray(r, dtype="float64"))]))


def metric_sharpe(r: np.ndarray, rf: np.ndarray) -> float:
    """報酬陣列版 Sharpe（供 bootstrap）。"""
    return sharpe(pd.Series(r), pd.Series(rf))


def metric_calmar(r: np.ndarray, rf: np.ndarray) -> float:
    """報酬陣列版 Calmar（供 bootstrap；rf 未用）。"""
    return calmar(_nav_from_returns(r))


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
    stats = stats[np.isfinite(stats)]
    lo = float(np.percentile(stats, 100 * alpha / 2))
    hi = float(np.percentile(stats, 100 * (1 - alpha / 2)))
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
    diffs = diffs[np.isfinite(diffs)]
    lo = float(np.percentile(diffs, 100 * alpha / 2))
    hi = float(np.percentile(diffs, 100 * (1 - alpha / 2)))
    point = float(metric_fn(a, f) - metric_fn(b, f))
    return {"point": point, "lo": lo, "hi": hi, "excludes_zero": lo > 0 or hi < 0}
```

- [ ] **Step 4: 執行確認通過 + 全測試綠 + lint**

Run: `uv run pytest tests/test_backtest/test_metrics_bootstrap.py -v`、`uv run pytest -q`、ruff。
Expected: 綠、乾淨。

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/metrics.py tests/test_backtest/test_metrics_bootstrap.py
git commit -m "feat(metrics): bootstrap CI + 配對差異檢定（full vs 消融版，§6.3）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 平均曝險 + 接進 compute_metrics / runner / ablation

**Files:**
- Modify: `quantcore/backtest/metrics.py`、`quantcore/experiments/runner.py`、`quantcore/experiments/ablation.py`
- Test: `tests/test_backtest/test_metrics_bootstrap.py`（續加）

- [ ] **Step 1: 續寫失敗測試**

在 `tests/test_backtest/test_metrics_bootstrap.py` 加：

```python
import pandas as pd

from quantcore.backtest.accounting import CASH
from quantcore.backtest.metrics import average_exposure, compute_metrics


def test_average_exposure_hand_computation():
    # 兩天：day1 風險 0.6（cash 0.4），day2 風險 1.0（cash 0）→ 平均 0.8
    w = pd.DataFrame(
        [
            {"date": "d1", "ticker": "A", "weight": 0.6},
            {"date": "d1", "ticker": CASH, "weight": 0.4},
            {"date": "d2", "ticker": "A", "weight": 1.0},
            {"date": "d2", "ticker": CASH, "weight": 0.0},
        ]
    )
    assert average_exposure(w) == pytest.approx(0.8)


def test_compute_metrics_average_exposure_none_without_weights():
    nav = pd.Series([1.0, 1.01, 1.02])
    rate = pd.Series([0.0001, 0.0001, 0.0001])
    m = compute_metrics(nav, rate, total_turnover=0.0, total_cost=0.0)
    assert m["average_exposure"] is None
```

（`import pytest` 置檔頭。）

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_backtest/test_metrics_bootstrap.py -k exposure -v`
Expected: FAIL。

- [ ] **Step 3: 實作 average_exposure + compute_metrics 接線**

在 `quantcore/backtest/metrics.py` 加（檔頭 import `from quantcore.backtest.accounting import CASH`）：

```python
def average_exposure(weights: pd.DataFrame) -> float:
    """平均風險曝險 = mean over days of (1 − CASH 權重)。weights 為單一策略的長格式。"""
    non_cash = weights[weights["ticker"] != CASH]
    daily = non_cash.groupby("date")["weight"].sum()
    return float(daily.mean())
```

`compute_metrics` 加選填參數與欄位：

```python
def compute_metrics(
    nav: pd.Series,
    rate_daily: pd.Series,
    total_turnover: float,
    total_cost: float,
    weights: pd.DataFrame | None = None,
) -> dict[str, float]:
    ...
    result = {
        ...既有欄位...,
        "average_exposure": average_exposure(weights) if weights is not None else None,
    }
    return result
```

- [ ] **Step 4: runner 與 ablation 接 weights**

- `quantcore/experiments/runner.py::run_experiment` 的 `compute_metrics(...)` 呼叫加 `weights=w_df`。
- `quantcore/experiments/ablation.py::_evaluate` 的 `compute_metrics(...)` 呼叫加 `weights=_w`（該迴圈已有 `nav_df, _w, _dec = run_strategy(...)`，把 `_w` 傳入）。

- [ ] **Step 5: 執行確認通過 + 全測試綠 + lint**

Run: `uv run pytest tests/test_backtest/test_metrics_bootstrap.py tests/test_experiments -v`、`uv run pytest -q`、ruff。
Expected: 綠（既有 runner/ablation 測試若斷言 metrics 欄位集合，需一併加 `average_exposure`——若有，調整之）。

- [ ] **Step 6: Commit**

```bash
git add quantcore/backtest/metrics.py quantcore/experiments/runner.py quantcore/experiments/ablation.py tests/test_backtest/test_metrics_bootstrap.py
git commit -m "feat(metrics): average_exposure + 接進 runner/ablation（§6.4）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 子期間分析

**Files:**
- Modify: `quantcore/backtest/metrics.py`
- Test: `tests/test_backtest/test_metrics_bootstrap.py`（續加）

- [ ] **Step 1: 續寫失敗測試**

在 `tests/test_backtest/test_metrics_bootstrap.py` 加：

```python
from quantcore.backtest.metrics import subperiod_metrics


def test_subperiod_metrics_splits_by_year():
    dates = pd.to_datetime(
        ["2008-06-01", "2009-06-01", "2015-06-01", "2021-06-01", "2022-06-01"]
    )
    nav = pd.Series([1.0, 0.9, 1.2, 1.3, 1.4], index=dates)
    rate = pd.Series([0.0001] * 5, index=dates)
    out = subperiod_metrics(nav, rate, [(2005, 2009), (2010, 2019), (2020, 9999)])
    assert set(out) == {"2005-2009", "2010-2019", "2020-9999"}
    assert out["2005-2009"]["n_days"] == 2   # 2008,2009
    assert out["2010-2019"]["n_days"] == 1   # 2015
    assert out["2020-9999"]["n_days"] == 2   # 2021,2022
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_backtest/test_metrics_bootstrap.py -k subperiod -v`
Expected: FAIL。

- [ ] **Step 3: 實作**

在 `quantcore/backtest/metrics.py` 加：

```python
def subperiod_metrics(
    nav: pd.Series,
    rate_daily: pd.Series,
    subperiods: list[tuple[int, int]],
) -> dict[str, dict[str, float]]:
    """對每個 (start_year, end_year) 子期間跑 compute_metrics（§6.4）。

    nav/rate_daily 須以 DatetimeIndex 索引。回 {"start-end": metrics}。
    """
    years = nav.index.year
    out: dict[str, dict[str, float]] = {}
    for start, end in subperiods:
        mask = (years >= start) & (years <= end)
        key = f"{start}-{end}"
        if not mask.any():
            out[key] = {"n_days": 0}
            continue
        sub_nav = nav[mask].reset_index(drop=True)
        sub_rate = rate_daily[mask].reset_index(drop=True)
        out[key] = compute_metrics(
            sub_nav, sub_rate, total_turnover=float("nan"), total_cost=float("nan")
        )
    return out
```

（子期間的 turnover/cost 不切分，故傳 nan；子期間分析看的是報酬類指標。）

- [ ] **Step 4: 執行確認通過 + 全測試綠 + lint**

Run: `uv run pytest tests/test_backtest/test_metrics_bootstrap.py -v`、`uv run pytest -q`、ruff。
Expected: 綠、乾淨。

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/metrics.py tests/test_backtest/test_metrics_bootstrap.py
git commit -m "feat(metrics): 子期間分析 subperiod_metrics（§6.4）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: σ*±2% AC 量測（`vol_target_ac.py`，讀 run 產物）

**Files:**
- Create: `quantcore/experiments/vol_target_ac.py`
- Test: `tests/test_experiments/test_vol_target_ac.py`

**設計要點：** 純讀 run 產物（decisions/nav/weights parquet），不重跑回測。`voltarget_only` 全期實現波動；`full` 日層級閾值子集（管轄日的 absmom 轉現金比例 ≤ 閾值）。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_experiments/test_vol_target_ac.py`：

```python
"""σ*±2% AC 條件式量測：voltarget_only 全期、full 日層級閾值子集。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quantcore.experiments.vol_target_ac import (
    full_conditional_realized_vol,
    realized_annual_vol,
)


def test_realized_annual_vol_hand():
    nav = pd.Series([1.0, 1.01, 0.9999, 1.02])
    r = nav.pct_change().dropna().to_numpy()
    assert realized_annual_vol(nav) == pytest.approx(float(np.std(r, ddof=1) * np.sqrt(252)))


def _full_decisions(rows):
    # rows: list of (execution_date, cash_frac) → 造 selection 決策的 absmom/w_risky
    recs = []
    for ed, c in rows:
        # 兩檔各 0.5：讓其中 cash_frac 對應的檔 absmom=False
        absmom = {"A": True, "B": c < 0.5}  # c=0.5 → B fail（轉現金 0.5）；c=0 → 皆過
        w_risky = {"A": 0.5, "B": 0.5}
        recs.append(
            {
                "strategy_id": "full",
                "event": "selection",
                "execution_date": pd.Timestamp(ed),
                "absmom": json.dumps(absmom),
                "w_risky": json.dumps(w_risky),
            }
        )
    return pd.DataFrame(recs)


def test_full_conditional_excludes_high_cash_days():
    # 三次 selection：exec 於 d0(c=0)、d3(c=0.5)、d6(c=0)
    dec = _full_decisions([("2020-01-01", 0.0), ("2020-01-04", 0.5), ("2020-01-07", 0.0)])
    dates = pd.to_datetime([f"2020-01-0{i}" for i in range(1, 10)])
    nav = pd.Series(1.0 + 0.001 * np.arange(9), index=dates)  # full 的 nav
    res = full_conditional_realized_vol(dec, nav, threshold=0.10)
    # d1..d3 由 c=0 治（納入）、d4..d6 由 c=0.5 治（排除）、d7..d9 由 c=0 治（納入）
    assert res["n_included"] < res["n_total"]
    assert res["n_included"] > 0
    # 嚴格版（c==0）⊆ 閾值版
    strict = full_conditional_realized_vol(dec, nav, threshold=0.0)
    assert strict["n_included"] <= res["n_included"]
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_experiments/test_vol_target_ac.py -v`
Expected: FAIL（ModuleNotFoundError）。

- [ ] **Step 3: 實作 vol_target_ac.py**

Create `quantcore/experiments/vol_target_ac.py`：

```python
"""σ*±2% AC 條件式量測（設計文件 §4）。純讀 run 產物，不重跑回測。

voltarget_only（無 absmom）= 全期乾淨測；full = 日層級閾值子集（管轄日的
absmom 轉現金比例 ≤ 閾值）。另報嚴格版（比例=0）當敏感度。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


def realized_annual_vol(nav: pd.Series) -> float:
    """實現年化波動 = std(日報酬, ddof=1) × √252。"""
    r = nav.pct_change().dropna().to_numpy()
    if len(r) < 2:
        return float("nan")
    return float(np.std(r, ddof=1) * np.sqrt(252))


def _cash_fraction(absmom_json: str, w_risky_json: str) -> float:
    """該次 selection 的 absmom 轉現金比例 = Σ_{absmom False} w_risky。"""
    absmom = json.loads(absmom_json)
    w_risky = json.loads(w_risky_json)
    return float(sum(w for t, w in w_risky.items() if not absmom.get(t, False)))


def full_conditional_realized_vol(
    decisions: pd.DataFrame, nav: pd.Series, threshold: float
) -> dict:
    """full 的條件式實現波動：只納入「管轄日 absmom 轉現金比例 ≤ threshold」的日子。

    decisions：full 的決策表（含 event/execution_date/absmom/w_risky）。
    nav：full 的 nav，DatetimeIndex。
    """
    sel = decisions[
        (decisions["strategy_id"] == "full") & (decisions["event"] == "selection")
    ].copy()
    sel["exec"] = pd.to_datetime(sel["execution_date"])
    sel = sel.dropna(subset=["exec"]).sort_values("exec")
    sel["cash_frac"] = [
        _cash_fraction(a, w) for a, w in zip(sel["absmom"], sel["w_risky"], strict=True)
    ]
    exec_dates = sel["exec"].to_numpy()
    cash_fracs = sel["cash_frac"].to_numpy()

    days = nav.index.to_numpy()
    # 每日的管轄 selection = 最後一個 exec ≤ 該日
    pos = np.searchsorted(exec_dates, days, side="right") - 1
    ret = nav.pct_change().dropna()
    ret_days = ret.index.to_numpy()
    ret_pos = np.searchsorted(exec_dates, ret_days, side="right") - 1
    included = np.array(
        [p >= 0 and cash_fracs[p] <= threshold for p in ret_pos]
    )
    sub = ret[included]
    n_total = int(len(ret))
    n_included = int(included.sum())
    vol = float(np.std(sub.to_numpy(), ddof=1) * np.sqrt(252)) if n_included >= 2 else float("nan")
    return {"realized_vol": vol, "n_included": n_included, "n_total": n_total, "threshold": threshold}


def measure_vol_target_ac(run_dir: str | Path, threshold: float) -> dict:
    """讀 run 目錄，回 voltarget_only（全期）與 full（閾值+嚴格）的實現波動與 AC 判定。"""
    run = Path(run_dir)
    nav = pd.read_parquet(run / "nav.parquet")
    dec = pd.read_parquet(run / "decisions.parquet")

    def _nav_of(sid: str) -> pd.Series:
        n = nav[nav["strategy_id"] == sid].sort_values("date")
        return pd.Series(n["nav"].to_numpy(), index=pd.to_datetime(n["date"].to_numpy()))

    def _pass(v: float) -> bool:
        return 0.08 <= v <= 0.12 if np.isfinite(v) else False

    vt_vol = realized_annual_vol(_nav_of("voltarget_only"))
    full_nav = _nav_of("full")
    full_thr = full_conditional_realized_vol(dec, full_nav, threshold)
    full_strict = full_conditional_realized_vol(dec, full_nav, 0.0)
    return {
        "voltarget_only": {"realized_vol": vt_vol, "passes": _pass(vt_vol)},
        "full_threshold": {**full_thr, "passes": _pass(full_thr["realized_vol"])},
        "full_strict": {**full_strict, "passes": _pass(full_strict["realized_vol"])},
    }
```

- [ ] **Step 4: 執行確認通過 + 全測試綠 + lint**

Run: `uv run pytest tests/test_experiments/test_vol_target_ac.py -v`、`uv run pytest -q`、ruff。
Expected: 綠、乾淨。

- [ ] **Step 5: Commit**

```bash
git add quantcore/experiments/vol_target_ac.py tests/test_experiments/test_vol_target_ac.py
git commit -m "feat(experiments): σ*±2% 條件式量測（full 日層級閾值子集，§4）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: `run_ablation` 加 baseline 配對 bootstrap 落盤

**Files:**
- Modify: `quantcore/experiments/ablation.py`
- Test: `tests/test_experiments/test_ablation.py`（續加）

**設計要點：** baseline 格額外落 `bootstrap.parquet`——`full` vs 每個其他策略的 Sharpe/Calmar 配對差異 CI（§2.2）。需 baseline 格各策略的**日報酬序列**（同一 clock 對齊）。若 `full` 不在 strategy_ids 則略過。

- [ ] **Step 1: 續寫失敗測試**

在 `tests/test_experiments/test_ablation.py` 加：

```python
def test_ablation_writes_bootstrap_table_when_full_present(tmp_path):
    import numpy as np

    from quantcore.experiments.ablation import run_ablation
    from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot

    n = 340
    dates = make_dates(n)
    rng = np.random.default_rng(4)
    prices = {tk: list(100 * np.cumprod(1 + rng.normal(0.0003 * (i + 1), 0.01, n)))
              for i, tk in enumerate(["A", "B", "C", "D"])}
    snap = make_snapshot(prices, dates)
    cfg = make_cfg(
        ["A", "B", "C", "D"],
        risk={"vol_model": "ewma", "corr_window": 60, "garch_window": 100},
        signal={"top_k": 2, "momentum_lookback": 120, "momentum_skip": 5},
        universe={"min_history_days": 130},
        stats={"bootstrap_reps": 50},  # 測試用小 reps
    )
    run_dir = run_ablation(
        cfg, snap, ["full", "mom_ivol", "voltarget_only"], {}, tmp_path, "test"
    )
    import pandas as pd

    bt = pd.read_parquet(run_dir / "bootstrap.parquet")
    # full vs mom_ivol / voltarget_only 的 Sharpe/Calmar 配對差異
    assert set(bt["vs"]) == {"mom_ivol", "voltarget_only"}
    assert set(bt["metric"]) == {"sharpe", "calmar"}
    assert {"point", "lo", "hi", "excludes_zero"} <= set(bt.columns)
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_experiments/test_ablation.py -k bootstrap -v`
Expected: FAIL（無 `bootstrap.parquet`）。

- [ ] **Step 3: 實作**

在 `quantcore/experiments/ablation.py` 加以下兩個函數。`_baseline_returns` 比照 `_evaluate` 建同一 clock 跑各策略，回各策略對齊的日報酬 + 日 rf：

```python
def _baseline_returns(
    base_cfg: QuantConfig, snapshot: dict, strategy_ids: list[str]
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """各策略在 baseline config 下的（日報酬, 日rf），同一 clock 對齊。"""
    d = snapshot["prices"]["date"]
    days = pd.DatetimeIndex(sorted(d.unique()))
    days = days[days >= pd.Timestamp(base_cfg.backtest.start)]
    strategies = [STRATEGIES[sid](base_cfg) for sid in strategy_ids]
    warmup = max(s.warmup_days for s in strategies)
    clock = EventClock(
        trading_days=days,
        warmup=warmup,
        selection_interval=base_cfg.schedule.selection_interval,
        exposure_check_interval=base_cfg.schedule.exposure_check_interval,
    )
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for s in strategies:
        nav_df, _w, _dec = run_strategy(snapshot, clock, s, base_cfg)
        rate = (
            snapshot["rates"].set_index("date")["DTB3"].reindex(nav_df["date"]).ffill().bfill()
            / 100.0
            / _DAYS_PER_YEAR
        )
        r = nav_df["nav"].pct_change().dropna().to_numpy()
        rf = rate.to_numpy()[1:]  # 對齊 pct_change 去掉的首日
        out[s.strategy_id] = (r, rf)
    lengths = {len(r) for r, _ in out.values()}
    if len(lengths) != 1:
        raise ValueError(f"baseline 各策略報酬長度不一致：{lengths}（clock 對齊有誤）")
    return out
```

（`_DAYS_PER_YEAR` 已於 ablation.py 定義；`np`/`pd`/`STRATEGIES`/`EventClock`/`run_strategy` 已 import。）然後：

```python
def _baseline_bootstrap(
    base_cfg: QuantConfig, snapshot: dict, strategy_ids: list[str]
) -> pd.DataFrame:
    """full vs 每個其他策略的 Sharpe/Calmar 配對差異 CI（§6.3）。full 不在則回空表。"""
    from quantcore.backtest.metrics import (
        metric_calmar,
        metric_sharpe,
        paired_metric_diff_ci,
        stationary_bootstrap_indices,
    )

    if "full" not in strategy_ids:
        return pd.DataFrame()
    series = _baseline_returns(base_cfg, snapshot, strategy_ids)  # {sid: (r, rf)}
    ra, rf = series["full"]
    n = len(ra)
    rng = np.random.default_rng(base_cfg.seed)  # INV-6
    idx = stationary_bootstrap_indices(
        n, base_cfg.stats.bootstrap_mean_block, base_cfg.stats.bootstrap_reps, rng
    )
    rows = []
    for sid, (rb, _rf) in series.items():
        if sid == "full":
            continue
        for mname, mfn in (("sharpe", metric_sharpe), ("calmar", metric_calmar)):
            res = paired_metric_diff_ci(ra, rb, rf, mfn, idx, base_cfg.stats.bootstrap_alpha)
            rows.append({"vs": sid, "metric": mname, **res})
    return pd.DataFrame(rows)
```

`_baseline_returns` 需保證各策略報酬同長對齊（同一 clock、同一 active days）——比照 `_evaluate`：所有策略共用 `warmup = max(...)` 的單一 clock，故 `nav_df` 逐日對齊；`pct_change().dropna()` 後長度一致。若某策略前期回 None（如 full 未選出）而 nav 起點不同——實務上所有策略 nav 從第一個 active day 起皆有值（全現金起步），故對齊。以斷言 `len` 一致守護。

在 `run_ablation` 寫出 comparison.parquet 後加：

```python
    bootstrap = _baseline_bootstrap(base_cfg, snapshot, strategy_ids)
    if not bootstrap.empty:
        bootstrap.to_parquet(run_dir / "bootstrap.parquet", index=False)
```

- [ ] **Step 4: 執行確認通過 + 全測試綠 + lint**

Run: `uv run pytest tests/test_experiments/test_ablation.py -v`、`uv run pytest -q`、ruff。
Expected: 綠、乾淨。

- [ ] **Step 5: Commit**

```bash
git add quantcore/experiments/ablation.py tests/test_experiments/test_ablation.py
git commit -m "feat(experiments): 消融 baseline 格加 full vs 消融版配對 bootstrap（§6.3）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: 真實快照跑消融全表 + AC 量測（本機閘門）

**Files:**
- Create: `tests/test_experiments/test_phase4_ac.py`（`requires_snapshot` 本機閘門）

**設計要點：** 本機（有快照）跑七策略 × §7.3 參數格全表 + AC 量測，斷言 AC 達成；CI 無快照乾淨 skip（比照 Phase 2 AC-3）。此 task 亦產出實際交付表。

- [ ] **Step 1: 寫本機閘門測試**

Create `tests/test_experiments/test_phase4_ac.py`：

```python
"""Phase 4 AC 本機閘門（需真實快照）：七策略消融全表 + σ*±2% 條件式量測。"""

from __future__ import annotations

import pandas as pd
import pytest

pytestmark = pytest.mark.requires_snapshot


PARAM_GRID = {
    "signal.top_k": [3, 5, 8],
    "risk.vol_target_annual": [0.08, 0.10, 0.12],
    "signal.momentum_lookback": [126, 252],
    "costs.per_side_bps": [0, 5, 10, 20],
}
SEVEN = ["bh_spy", "ew_menu", "sixty_forty", "mom_only", "voltarget_only", "mom_ivol", "full"]


def test_seven_strategy_ablation_and_vol_target_ac(tmp_path):
    from quantcore.config import load_config
    from quantcore.data.snapshot import load_snapshot
    from quantcore.experiments.ablation import run_ablation
    from quantcore.experiments.runner import run_experiment
    from quantcore.experiments.vol_target_ac import measure_vol_target_ac

    cfg = load_config("quantcore/config/default.yaml")
    snapshot = load_snapshot(cfg.snapshot)

    # 七策略消融全表（AC-1）
    run_dir = run_ablation(cfg, snapshot, SEVEN, PARAM_GRID, tmp_path, "phase4")
    table = pd.read_parquet(run_dir / "comparison.parquet")
    assert set(table["strategy_id"]) == set(SEVEN)
    bootstrap = pd.read_parquet(run_dir / "bootstrap.parquet")
    assert set(bootstrap["vs"]) == set(s for s in SEVEN if s != "full")

    # σ*±2% 條件式量測（AC-2）——需一個完整 run（有 decisions/nav）
    exp_dir = run_experiment(cfg, snapshot, tmp_path, "phase4_full", SEVEN)
    ac = measure_vol_target_ac(exp_dir, cfg.stats.absmom_cash_threshold)
    # voltarget_only 全期落 8-12%（波動目標乾淨測）
    assert ac["voltarget_only"]["passes"], ac["voltarget_only"]
    # full 在 absmom 大致全過期間落 8-12%（隔離波動目標層）
    assert ac["full_threshold"]["passes"], ac["full_threshold"]
```

- [ ] **Step 2: 本機執行（有快照）**

Run: `uv run pytest tests/test_experiments/test_phase4_ac.py -v -s`
Expected: **PASS**（本機有快照，~30-45 分鐘）。若 `full_threshold` 或 `voltarget_only` 未落 8-12%：**先不要調參數**。檢查——是否 bug（曝險機制/量測），或是誠實的 AC 未達成（記錄實際值、與 σ*=10% 的差距、可能原因如快照期間 GARCH 系統性偏誤）。若為真實未達成，STOP 回報，由人決定（可能鬆綁 AC 定義或修模型），不得靜默改測試容差硬湊。

- [ ] **Step 3: 確認 CI 乾淨 skip**

Run（模擬 CI 無快照）：暫時把快照 `prices.parquet` 移開或確認 `requires_snapshot` marker 生效 → 該測試 skip。還原。

- [ ] **Step 4: 全測試綠**

Run: `uv run pytest -q`（本機：含此閘門 pass；或 skip 若無快照）
Expected: 綠。

- [ ] **Step 5: Commit**

```bash
git add tests/test_experiments/test_phase4_ac.py
git commit -m "test(phase4): 七策略消融全表 + σ*±2% 條件式量測本機閘門（AC）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: PROGRESS + Phase 4 完成

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: 記錄 4c 完成 + Phase 4 AC 達成**

在 `PROGRESS.md`：
- Phase 4 剩餘任務打勾（block bootstrap）、三個 AC 打勾（七策略消融全表、σ*±2% 條件式、子期間）。
- 總覽表 Phase 4 狀態改 **✅ 完成**（若全 AC 達成）。
- 記本機閘門的**實際量測值**（voltarget_only 全期實現波動、full 閾值/嚴格版實現波動、full vs 各消融版的配對差異 CI 是否 excludes_zero——即哪些層「自證其值」、哪些「無顯著貢獻」）。**誠實記錄**：若某層無顯著貢獻，照 §6.3 記為合格結論。
- 「變更紀錄」加一行：momentum_select 抽取、bootstrap（配對差異）、average_exposure、子期間、σ*±2% 條件式量測、七策略全表。6 處規格偏離（見設計 §8）。

- [ ] **Step 2: 全測試綠 + 格式檢查**

Run: `uv run pytest -q && uv run ruff format --check quantcore tests && uv run ruff check quantcore tests`
Expected: 綠、乾淨。

- [ ] **Step 3: Commit**

```bash
git add PROGRESS.md
git commit -m "docs(phase4c): bootstrap + 消融全表 + AC 量測完成，Phase 4 全部 AC 達成

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 完成後

Phase 4 全部 AC 達成：七策略消融全表（含配對 bootstrap）、σ*±2% 條件式量測、子期間分析、QLIKE 比較表（4a）。消融結果即研究報告骨架。

下一步為 **Phase 5**（DCC 與 ERC）——`build_covariance` 的 R 來源由樣本相關換 DCC/EWMA-corr，消融證明 DCC 是否勝過 EWMA。另開 brainstorming。
