# Phase 7a 計畫 1 — 引擎診斷落盤 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓引擎在既有 run artifact 之外，額外落盤 dashboard 頁 3/4/9 所需的診斷（相關矩陣、標準化殘差、`corr_fell_back`、trade blotter），並重跑 2 個 canonical run，為 Phase 7a 計畫 2（presentation）備妥真實資料。

**Architecture:** 「把已算的中間值接出來」——相關矩陣 `R`、`corr_fell_back`、per-ticker Δweight、標準化殘差在引擎內部都已算出，只是未落盤。相關矩陣與 `corr_fell_back` 走 `Diagnostics`（決策當下記錄，§6.2），run 結束時由 runner 攤平為 `model_details/correlation.parquet`；標準化殘差 run 結束時自 forecaster 狀態取出為 `model_details/residuals.parquet`；trade blotter 於引擎執行點組裝為一級 artifact `trades.parquet`。所有新輸出以對帳測試 + INV-3/5/6 閘門守護。

**Tech Stack:** Python 3.12、pandas、pytest、uv、ruff。既有 `tests/fixtures/synthetic.py`（`make_dates`/`make_snapshot`）。

---

## 設計依據（前置文件）

- 設計文件：[`docs/superpowers/specs/2026-07-29-phase7a-dashboard-design.md`](../specs/2026-07-29-phase7a-dashboard-design.md)，本計畫實作其 §3（引擎端診斷落盤）+ §4（canonical run）。
- 本計畫**不**碰 presentation 層（計畫 2）。

## 設計決定（實作時遵守）

- **INV-6 content_hashes 只納入 `trades.parquet`**（一級結果、與 nav 的 turnover/cost 對帳）；`model_details/*`（相關矩陣、殘差）為深掘診斷，**不**進 content_hashes，避免 DCC-QMLE 決定性邊緣情況動搖 identity 合約、且缺 `model_details/` 本就允許（設計 §0）。
- **相關矩陣只有算 R 的策略有**（`full`/`full_erc`）；`voltarget_only`（K=1、R=1×1）與非 vol-target 策略無——runner 在攤平時跳過 `shape[0] < 2` 的矩陣。
- **殘差粒度**：每檔最後一次 refit/filter 的標準化殘差序列（VolForecaster `_resid` 快取現值）；QQ/ACF 一份即足（設計 §3.4）。
- **`run_strategy` 改回 4-tuple** `(nav, weights, decisions, trades)`：5 個呼叫端全部更新（見 Task 5）。

## 檔案結構

| 檔案 | 職責 | 動作 |
|------|------|------|
| `quantcore/backtest/accounting.py` | `trade_deltas`（per-ticker Δw 分解）+ `turnover` 改用它 | 修改 |
| `quantcore/models/correlation/forecaster.py` | `last_fell_back()` | 修改 |
| `quantcore/models/volatility/forecaster.py` | `all_standardized_residuals()` | 修改 |
| `quantcore/backtest/strategy.py` | `Diagnostics` 加 `corr_matrix`/`corr_fell_back` | 修改 |
| `quantcore/backtest/strategies/vol_target_base.py` | `_build_cov` 回 `(cov, R)`；`_exposure_decision` 收 R 並填診斷；`standardized_residuals()` | 修改 |
| `quantcore/backtest/strategies/full_erc.py` | `decide` 兩 call site 配合新簽名 | 修改 |
| `quantcore/backtest/engine.py` | `_adj_close_wide`、blotter 組裝、回 4-tuple | 修改 |
| `quantcore/experiments/runner.py` | 攤平相關/殘差、`corr_fell_back` 欄、傳新表給 `write_artifacts` | 修改 |
| `quantcore/experiments/ablation.py` | `run_strategy` 解包 4-tuple | 修改 |
| `quantcore/experiments/tracking.py` | `write_artifacts` 寫 `trades.parquet` + `model_details/`；`_content_hashes` 加 trades | 修改 |
| `tests/test_backtest/test_engine_log_only.py` | 解包 4-tuple | 修改 |
| `tests/test_invariants/test_execution_lag.py` | 解包 4-tuple | 修改 |
| `tests/test_invariants/test_reproducibility.py` | `DATA_FRAMES` 加 `trades.parquet` | 修改 |
| `tests/test_backtest/test_accounting.py` | `trade_deltas`/turnover 一致性 | 修改（加測試） |
| `tests/test_models/test_forecaster_diagnostics.py` | `last_fell_back`/`all_standardized_residuals` | 新增 |
| `tests/test_backtest/test_diagnostics_corr.py` | `_exposure_decision` 帶 corr 診斷 | 新增 |
| `tests/test_backtest/test_blotter.py` | blotter 對帳（Σ\|Δw\|==turnover、Σcost==cost） | 新增 |
| `tests/test_experiments/test_model_details.py` | runner 落盤 trades/correlation/residuals | 新增 |

---

## Task 1: `accounting.trade_deltas` + `turnover` 改用它

**Files:**
- Modify: `quantcore/backtest/accounting.py:49-55`
- Test: `tests/test_backtest/test_accounting.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_backtest/test_accounting.py` 末尾加：

```python
from quantcore.backtest.accounting import trade_deltas


def test_trade_deltas_excludes_cash_and_gives_signed_changes():
    drifted = {"A": 0.5, "B": 0.3, "CASH": 0.2}
    target = {"A": 0.2, "B": 0.3, "CASH": 0.5}
    d = trade_deltas(drifted, target)
    assert "CASH" not in d
    assert d["A"] == -0.3  # 賣
    assert d["B"] == 0.0  # 不動
    assert set(d) == {"A", "B"}


def test_turnover_equals_sum_abs_trade_deltas():
    """turnover 是 trade_deltas 的 |·| 總和——blotter 對帳的結構保證。"""
    from quantcore.backtest.accounting import turnover

    drifted = {"A": 0.5, "B": 0.1, "CASH": 0.4}
    target = {"A": 0.2, "C": 0.3, "CASH": 0.5}
    d = trade_deltas(drifted, target)
    assert turnover(drifted, target) == sum(abs(v) for v in d.values())
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_accounting.py::test_trade_deltas_excludes_cash_and_gives_signed_changes -v`
Expected: FAIL（`ImportError: cannot import name 'trade_deltas'`）

- [ ] **Step 3: 實作**

把 `quantcore/backtest/accounting.py:49-55` 的 `turnover` 換成下面兩個函數（`trade_deltas` 在前）：

```python
def trade_deltas(drifted: dict[str, float], target: dict[str, float]) -> dict[str, float]:
    """每檔風險資產的權重變動 target_i − drifted_i（**不含 CASH**）。

    turnover 的 per-ticker 分解：trade blotter 由此接出，結構上保證
    Σ|delta| ≡ turnover（現金為合成、無交易成本，計入會使單邊成本翻倍）。
    """
    keys = (set(drifted) | set(target)) - {CASH}
    return {k: target.get(k, 0.0) - drifted.get(k, 0.0) for k in keys}


def turnover(drifted: dict[str, float], target: dict[str, float]) -> float:
    """Σ_i |target_i − drifted_i|，**i 只跑風險資產**（§1.8、設計文件 §2.2）。"""
    return sum(abs(dw) for dw in trade_deltas(drifted, target).values())
```

- [ ] **Step 4: 跑測試確認通過（含既有 accounting/INV-5 測試不回歸）**

Run: `uv run pytest tests/test_backtest/test_accounting.py tests/test_invariants/test_accounting.py -v`
Expected: PASS（新測試 + 既有全綠——`turnover` 對相同 key 集以相同順序加總，數值與改前逐位元相同）

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/accounting.py tests/test_backtest/test_accounting.py
git commit -m "feat(phase7a): accounting.trade_deltas + turnover 改用它（blotter 分解來源）"
```

---

## Task 2: `CorrelationForecaster.last_fell_back()`

**Files:**
- Modify: `quantcore/models/correlation/forecaster.py:64-66`
- Test: `tests/test_models/test_forecaster_diagnostics.py`（新增）

- [ ] **Step 1: 寫失敗測試**

新增 `tests/test_models/test_forecaster_diagnostics.py`：

```python
"""forecaster 診斷 accessor（Phase 7a 落盤 model_details 用）。"""

import numpy as np
import pandas as pd

from quantcore.models.correlation.forecaster import CorrelationForecaster


def _resid(n=400, k=3, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame(rng.standard_normal((n, k)), index=idx, columns=["A", "B", "C"])


def test_last_fell_back_none_before_refit_and_for_ewma():
    ew = CorrelationForecaster("ewma", 0.94, 0, (0.02, 0.97), 21, 0.0)
    assert ew.last_fell_back() is None  # ewma 無 fallback 概念
    ew.refit(_resid())
    assert ew.last_fell_back() is None


def test_last_fell_back_is_bool_after_dcc_refit():
    dcc = CorrelationForecaster("dcc", 0.94, 63, (0.02, 0.97), 21, 0.0)
    dcc.refit(_resid())
    assert isinstance(dcc.last_fell_back(), bool)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_models/test_forecaster_diagnostics.py -v`
Expected: FAIL（`AttributeError: 'CorrelationForecaster' object has no attribute 'last_fell_back'`）

- [ ] **Step 3: 實作**

在 `quantcore/models/correlation/forecaster.py` 的 `last_params` 之後（檔尾）加：

```python
    def last_fell_back(self) -> bool | None:
        """dcc 回當前 DccParams.fell_back（(a,b) 是否退回 fixed_ab）；ewma 無 fallback 概念回 None。

        鏡射 VolForecaster.last_fell_back，供決策當下落盤 corr_fell_back（了結 Phase 5a I-1）。
        """
        return None if self._params is None else self._params.fell_back
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_models/test_forecaster_diagnostics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/models/correlation/forecaster.py tests/test_models/test_forecaster_diagnostics.py
git commit -m "feat(phase7a): CorrelationForecaster.last_fell_back（corr_fell_back 落盤來源，了結 5a I-1）"
```

---

## Task 3: `VolForecaster.all_standardized_residuals()` + 策略 `standardized_residuals()`

**Files:**
- Modify: `quantcore/models/volatility/forecaster.py:90-92`
- Modify: `quantcore/backtest/strategies/vol_target_base.py`（`VolTargetStrategy` 加方法）
- Test: `tests/test_models/test_forecaster_diagnostics.py`（沿用 Task 2 檔）

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_models/test_forecaster_diagnostics.py` 末尾加：

```python
def test_all_standardized_residuals_returns_every_fit_ticker():
    from quantcore.models.volatility.forecaster import VolForecaster

    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2019-01-01", periods=500)
    f = VolForecaster("ewma", 0.94, 21, 1000)
    for t in ("A", "B"):
        r = pd.Series(rng.normal(0, 0.01, 500), index=idx)
        f.refit(t, r)
    allr = f.all_standardized_residuals()
    assert set(allr) == {"A", "B"}
    assert isinstance(allr["A"], pd.Series)
    # 回傳是拷貝，改它不影響內部快取
    allr.pop("A")
    assert set(f.all_standardized_residuals()) == {"A", "B"}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_models/test_forecaster_diagnostics.py::test_all_standardized_residuals_returns_every_fit_ticker -v`
Expected: FAIL（`AttributeError: ... 'all_standardized_residuals'`）

- [ ] **Step 3: 實作**

在 `quantcore/models/volatility/forecaster.py` 的 `last_standardized_residuals` 之後（檔尾）加：

```python
    def all_standardized_residuals(self) -> dict[str, pd.Series]:
        """所有曾 refit/filter 過的 ticker → 最後一次標準化殘差序列。

        供 run 結束時落盤 model_details/residuals.parquet（頁 3 QQ/ACF）。回淺拷貝。
        """
        return dict(self._resid)
```

在 `quantcore/backtest/strategies/vol_target_base.py` 的 `VolTargetStrategy` 類別內（`_exposure_decision` 之後）加：

```python
    def standardized_residuals(self) -> dict[str, pd.Series]:
        """各檔最後一次 refit/filter 的標準化殘差（runner 於 run 結束落盤 residuals.parquet）。"""
        return self._forecaster.all_standardized_residuals()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_models/test_forecaster_diagnostics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/models/volatility/forecaster.py quantcore/backtest/strategies/vol_target_base.py tests/test_models/test_forecaster_diagnostics.py
git commit -m "feat(phase7a): VolForecaster.all_standardized_residuals + 策略暴露介面（residuals 落盤）"
```

---

## Task 4: `Diagnostics` 加 corr 欄位並 thread through 決策路徑

**Files:**
- Modify: `quantcore/backtest/strategy.py`（import pandas + `Diagnostics` 加兩欄）
- Modify: `quantcore/backtest/strategies/vol_target_base.py`（`_build_cov`、`_exposure_decision`、`decide`）
- Modify: `quantcore/backtest/strategies/full_erc.py`（`decide` 兩 call site）
- Test: `tests/test_backtest/test_diagnostics_corr.py`（新增）

- [ ] **Step 1: 寫失敗測試**

新增 `tests/test_backtest/test_diagnostics_corr.py`：

```python
"""Diagnostics 帶相關矩陣 + corr_fell_back（決策當下記錄，§6.2）。"""

import pandas as pd

from quantcore.backtest.strategies.full import Full
from quantcore.backtest.strategies.vol_target_base import RiskyState
from quantcore.config import load_config
from quantcore.models.covariance import build_covariance


def _cfg():
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.risk.corr_model = "ewma"  # 預設；ewma 無 fallback → corr_fell_back None
    return cfg


def test_exposure_decision_carries_corr_matrix_and_fell_back():
    strat = Full(_cfg())
    selected = ["SPY", "QQQ"]
    state = RiskyState(
        eligible=selected,
        selected=selected,
        momentum_scores=None,
        w_risky={"SPY": 0.5, "QQQ": 0.5},
        sigma_hat={"SPY": 0.20, "QQQ": 0.25},
        absmom={"SPY": True, "QQQ": True},
        garch_params={"SPY": None, "QQQ": None},
        fell_back={"SPY": False, "QQQ": False},
    )
    R = pd.DataFrame([[1.0, 0.3], [0.3, 1.0]], index=selected, columns=selected)
    cov = build_covariance(state.sigma_hat, R)

    dec = strat._exposure_decision(state, cov, R, None)

    assert dec.diagnostics.corr_matrix is R
    assert dec.diagnostics.corr_fell_back is None  # ewma、且未 refit
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_diagnostics_corr.py -v`
Expected: FAIL（`TypeError: _exposure_decision() takes 4 positional arguments but 5 were given`）

- [ ] **Step 3: 實作**

**(a)** `quantcore/backtest/strategy.py`：把 `from dataclasses import dataclass` 改為 `from dataclasses import dataclass, field`，並在 `from enum import StrEnum` 之後加 `import pandas as pd`。在 `Diagnostics` 的 `garch_params` 欄位之後加兩欄：

```python
    # corr_matrix 為 pd.DataFrame：compare=False 讓 frozen dataclass 的 __eq__/__hash__ 不碰它
    # （DataFrame 真值歧義 + unhashable，比照 Phase 5a DccParams 的 eq=False 處置）。
    corr_matrix: pd.DataFrame | None = field(default=None, compare=False, repr=False)
    corr_fell_back: bool | None = None  # DCC (a,b) 是否退回 fixed_ab（鏡射 vol_fell_back）
```

**(b)** `quantcore/backtest/strategies/vol_target_base.py`：把 `_build_cov` 改為回 `(cov, R)`：

```python
    def _build_cov(
        self,
        view: PointInTimeView,
        selected: list[str],
        sigma_hat: dict[str, float],
        event: DecisionEvent,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """殘差 → corr.refit(選擇日)/filter(曝險檢查日) → build_covariance。回 (Σ, R)。"""
        std_resid = self._collect_std_residuals(view, selected)
        R = (
            self._corr.refit(std_resid)
            if event is DecisionEvent.SELECTION
            else self._corr.filter(std_resid)
        )
        return build_covariance(sigma_hat, R), R
```

把 `decide` 內 SELECTION 分支的 `self._cache = state`（原 129）**刪除**（M-1：不在可 raise 的 `_build_cov` 之前就污染快取），並把結尾 `cov = self._build_cov(...)`（原 137-138）改為：

```python
        cov, R = self._build_cov(view, state.selected, state.sigma_hat, event)
        if event is DecisionEvent.SELECTION:
            self._cache = state  # M-1：相關步驟成功後才寫快取（例外時不留半套狀態）
        return self._exposure_decision(state, cov, R, e_current)
```

> M-1（Phase 5a holistic review）：原 `self._cache=state` 設於 `_build_cov`（可因殘差非新鮮 raise）之前，例外續跑時下個曝險檢查會踩 `filter` 的 assert。移到 `_build_cov` 之後修掉。EXPOSURE_CHECK 分支不重寫快取（`state` 為 refilter 副本），故 `if SELECTION` 守。

把 `_exposure_decision` 簽名加 `R` 參數並在 `Diagnostics(...)` 補兩欄：

```python
    def _exposure_decision(
        self, state: RiskyState, cov: pd.DataFrame, R: pd.DataFrame, e_current: float | None
    ) -> Decision:
```

在 `diag = Diagnostics(...)` 的 `garch_params=state.garch_params,` 之後加：

```python
            corr_matrix=R,
            corr_fell_back=self._corr.last_fell_back(),
```

**(c)** `quantcore/backtest/strategies/full_erc.py`：`decide` 內兩處。SELECTION 分支的 `cov = self._build_cov(...)`（原 41）改為：

```python
            cov, R = self._build_cov(view, sel.selected, sigma_hat, event)
```

EXPOSURE_CHECK 分支的 `cov = self._build_cov(...)`（原 60）改為：

```python
            cov, R = self._build_cov(view, state.selected, state.sigma_hat, event)
```

結尾 `return self._exposure_decision(state, cov, e_current)`（原 62）改為：

```python
        return self._exposure_decision(state, cov, R, e_current)
```

- [ ] **Step 4: 跑測試確認通過（含 full/full_erc 既有測試不回歸）**

Run: `uv run pytest tests/test_backtest/test_diagnostics_corr.py tests/test_backtest/ -v`
Expected: PASS（新測試 + 既有全綠）

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/strategy.py quantcore/backtest/strategies/vol_target_base.py quantcore/backtest/strategies/full_erc.py tests/test_backtest/test_diagnostics_corr.py
git commit -m "feat(phase7a): Diagnostics 帶 corr_matrix/corr_fell_back，thread through 決策路徑"
```

---

## Task 5: engine trade blotter + `run_strategy` 回 4-tuple + 更新呼叫端

**Files:**
- Modify: `quantcore/backtest/engine.py`
- Modify: `quantcore/experiments/runner.py:109`（暫接第 4 回傳為 `_tr`，Task 6 才用）
- Modify: `quantcore/experiments/ablation.py:92,111`
- Modify: `tests/test_backtest/test_engine_log_only.py:42,88`
- Modify: `tests/test_invariants/test_execution_lag.py:135`
- Test: `tests/test_backtest/test_blotter.py`（新增）

- [ ] **Step 1: 寫失敗測試**

新增 `tests/test_backtest/test_blotter.py`：

```python
"""trade blotter 對帳：Σ|Δw| == nav.turnover、Σ cost == nav.cost（逐再平衡）。"""

import numpy as np

from quantcore.backtest.accounting import CASH
from quantcore.backtest.clock import EventClock
from quantcore.backtest.engine import run_strategy
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.config import load_config
from tests.fixtures.synthetic import make_dates, make_snapshot


class _FixedTarget(Strategy):
    strategy_id = "fixed"

    def __init__(self, cfg, target):
        super().__init__(cfg)
        self._target = target
        self._done = False

    @property
    def warmup_days(self) -> int:
        return 0

    def decide(self, view, event):
        if self._done or event is not DecisionEvent.SELECTION:
            return None
        self._done = True
        return Decision(
            target_weights=dict(self._target),
            diagnostics=Diagnostics(eligible=sorted(self._target), selected=sorted(self._target)),
        )


def _run(target):
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["A", "B"]
    cfg.universe.min_history_days = 1
    cfg.signal.top_k = 2
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    cfg.costs.per_side_bps = 10.0  # 確保 cost > 0
    dates = make_dates(20)
    rng = np.random.default_rng(7)
    snap = make_snapshot(
        {
            "A": list(100.0 * np.cumprod(1 + rng.normal(0.001, 0.01, 20))),
            "B": list(50.0 * np.cumprod(1 + rng.normal(0.001, 0.01, 20))),
        },
        dates,
    )
    clock = EventClock(
        trading_days=dates,
        warmup=2,
        selection_interval=cfg.schedule.selection_interval,
        exposure_check_interval=cfg.schedule.exposure_check_interval,
    )
    return run_strategy(snap, clock, _FixedTarget(cfg, target), cfg)


def test_blotter_reconciles_turnover_and_cost():
    nav, weights, decisions, trades = _run({"A": 0.6, "B": 0.4, CASH: 0.0})
    x_day = decisions["execution_date"].iloc[0]
    tr = trades[trades["execution_date"] == x_day]
    nav_row = nav[nav["date"] == x_day].iloc[0]

    assert abs(tr["delta_weight"].abs().sum() - nav_row["turnover"]) < 1e-12
    assert abs(tr["cost"].sum() - nav_row["cost"]) < 1e-9


def test_blotter_fields_are_consistent():
    _, _, _, trades = _run({"A": 1.0, "B": 0.0, CASH: 0.0})
    row = trades[trades["ticker"] == "A"].iloc[0]
    assert row["side"] == "buy"  # 全現金 → 建 A 倉
    assert row["delta_weight"] > 0
    assert abs(row["shares"] * row["fill_price"] - row["notional"]) < 1e-6
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_blotter.py -v`
Expected: FAIL（`ValueError: not enough values to unpack (expected 4, got 3)`）

- [ ] **Step 3: 實作 engine**

`quantcore/backtest/engine.py`：

import 區把 `from quantcore.backtest.accounting import CASH, apply_costs, apply_returns` 改為：

```python
from quantcore.backtest.accounting import CASH, apply_costs, apply_returns, trade_deltas
```

在 `_returns_wide` 之後加：

```python
def _adj_close_wide(prices: pd.DataFrame) -> pd.DataFrame:
    """date × ticker 的 adj_close 面板（blotter 的成交價來源）。"""
    return prices.pivot(index="date", columns="ticker", values="adj_close").sort_index()
```

在 `run_strategy` 內 `rets = _returns_wide(...)` 之後加一行：

```python
    adj = _adj_close_wide(snapshot["prices"])
```

把 `nav_rows, weight_rows, decision_rows = [], [], []` 改為：

```python
    nav_rows, weight_rows, decision_rows, trade_rows = [], [], [], []
```

把執行區塊（原 65-70）：

```python
        if pending is not None and pending.execution_day == t:
            nav_before = nav
            nav, turnover_today = apply_costs(nav, drifted, pending.target, cfg.costs.per_side_bps)
            cost_today = nav_before - nav
            weights = dict(pending.target)
            pending = None
```

改為（在 `weights = dict(pending.target)` 之前插入 blotter 組裝）：

```python
        if pending is not None and pending.execution_day == t:
            nav_before = nav
            nav, turnover_today = apply_costs(nav, drifted, pending.target, cfg.costs.per_side_bps)
            cost_today = nav_before - nav
            bps = cfg.costs.per_side_bps
            for ticker, dw in trade_deltas(drifted, pending.target).items():
                if dw == 0.0:
                    continue
                price = float(adj.at[t, ticker])
                notional = dw * nav_before
                trade_rows.append(
                    {
                        "execution_date": t,
                        "strategy_id": strategy.strategy_id,
                        "ticker": ticker,
                        "drifted_weight": drifted.get(ticker, 0.0),
                        "target_weight": pending.target.get(ticker, 0.0),
                        "delta_weight": dw,
                        "side": "buy" if dw > 0 else "sell",
                        "notional": notional,
                        "fill_price": price,
                        "shares": notional / price,
                        "cost": abs(dw) * nav_before * bps / 10_000.0,
                    }
                )
            weights = dict(pending.target)
            pending = None
```

把 `return (...)`（原 118-122）改為回 4-tuple：

```python
    return (
        pd.DataFrame(nav_rows),
        pd.DataFrame(weight_rows),
        pd.DataFrame(decision_rows),
        pd.DataFrame(trade_rows),
    )
```

- [ ] **Step 4: 更新所有 `run_strategy` 呼叫端解包**

- `quantcore/experiments/runner.py:109`：`nav_df, w_df, d_df = run_strategy(...)` → `nav_df, w_df, d_df, t_df = run_strategy(snapshot, clock, s, cfg)`（`t_df` 暫不用，Task 6 才接）。
- `quantcore/experiments/ablation.py:92`：`nav_df, _w, _dec = run_strategy(...)` → `nav_df, _w, _dec, _tr = run_strategy(snapshot, clock, s, cfg)`。
- `quantcore/experiments/ablation.py:111`：同上 → `nav_df, _w, _dec, _tr = run_strategy(snapshot, clock, s, base_cfg)`。
- `tests/test_backtest/test_engine_log_only.py:42`：`nav, weights, decisions = run_strategy(...)` → `nav, weights, decisions, _tr = run_strategy(snap, clock, _LogOnlyOnce(cfg), cfg)`。
- `tests/test_backtest/test_engine_log_only.py:88`：→ `nav, weights, decisions, _tr = run_strategy(snap, clock, _LogOnlyThenExecute(cfg), cfg)`。
- `tests/test_invariants/test_execution_lag.py:135`：`nav, weights, decisions = run_strategy(...)` → `nav, weights, decisions, _tr = run_strategy(snap, clock, _FixedTarget(cfg, target), cfg)`。

- [ ] **Step 5: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/test_blotter.py tests/test_backtest/test_engine_log_only.py tests/test_invariants/test_execution_lag.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add quantcore/backtest/engine.py quantcore/experiments/runner.py quantcore/experiments/ablation.py tests/test_backtest/test_blotter.py tests/test_backtest/test_engine_log_only.py tests/test_invariants/test_execution_lag.py
git commit -m "feat(phase7a): engine trade blotter + run_strategy 回 4-tuple（對帳測試守）"
```

---

## Task 6: runner 攤平相關/殘差/trades + `corr_fell_back` 欄

**Files:**
- Modify: `quantcore/experiments/runner.py`
- Test: `tests/test_experiments/test_model_details.py`（新增，Task 7 一起驗落盤）

- [ ] **Step 1: 實作 runner（本 task 純接線，落盤驗證在 Task 7）**

`quantcore/experiments/runner.py`：

import 區加：

```python
from quantcore.backtest.strategies.vol_target_base import VolTargetStrategy
```

在 `_diagnostics_row` 的回傳 dict 內 `"garch_params": j(diag.garch_params),` 之後加一行：

```python
        "corr_fell_back": diag.corr_fell_back,
```

在 `_flatten_decisions` 的型別轉換區（`out["band_blocked"] = ...` 之後）加：

```python
    out["corr_fell_back"] = out["corr_fell_back"].astype("boolean")
```

在 `_flatten_decisions` 之後加兩個攤平函數：

```python
def _flatten_correlations(raw: pd.DataFrame) -> pd.DataFrame:
    """每決策的 corr_matrix → 長格式（decision_date, strategy_id, ticker_i, ticker_j, corr）。

    只有算 R 的策略（full/full_erc）有；K=1（voltarget_only）或無矩陣者跳過。
    """
    if raw.empty:
        return pd.DataFrame()
    rows = []
    for r in raw.to_dict("records"):
        rmat = r["diagnostics"].corr_matrix
        if rmat is None or rmat.shape[0] < 2:
            continue
        tickers = list(rmat.index)
        for ti in tickers:
            for tj in tickers:
                rows.append(
                    {
                        "decision_date": r["decision_date"],
                        "strategy_id": r["strategy_id"],
                        "ticker_i": ti,
                        "ticker_j": tj,
                        "corr": float(rmat.at[ti, tj]),
                    }
                )
    return pd.DataFrame(rows)


def _residuals_frame(strategy_id: str, resid: dict) -> pd.DataFrame:
    """各檔最後一次標準化殘差 → 長格式（strategy_id, ticker, date, std_resid）。"""
    rows = []
    for ticker, s in resid.items():
        for date, val in s.items():
            rows.append(
                {"strategy_id": strategy_id, "ticker": ticker, "date": date, "std_resid": float(val)}
            )
    return pd.DataFrame(rows)
```

在 `run_experiment` 內，把 `navs, weights, decisions, metrics = [], [], [], {}` 改為：

```python
    navs, weights, decisions, trades, correlations, residuals, metrics = [], [], [], [], [], [], {}
```

把迴圈內 `nav_df, w_df, d_df = run_strategy(...)`（Task 5 已改成 `..., t_df`）之後的三行 append 區塊：

```python
        nav_df, w_df, d_df, t_df = run_strategy(snapshot, clock, s, cfg)
        navs.append(nav_df)
        weights.append(w_df)
        decisions.append(_flatten_decisions(d_df))
```

改為：

```python
        nav_df, w_df, d_df, t_df = run_strategy(snapshot, clock, s, cfg)
        navs.append(nav_df)
        weights.append(w_df)
        decisions.append(_flatten_decisions(d_df))
        trades.append(t_df)
        correlations.append(_flatten_correlations(d_df))
        if isinstance(s, VolTargetStrategy):
            residuals.append(_residuals_frame(s.strategy_id, s.standardized_residuals()))
```

把 `write_artifacts(...)` 呼叫（原 135-151）在 `metrics=metrics,` 之前加三個具名參數：

```python
        trades=pd.concat(trades, ignore_index=True) if any(len(t) for t in trades) else pd.DataFrame(),
        correlations=pd.concat(correlations, ignore_index=True)
        if any(len(c) for c in correlations)
        else pd.DataFrame(),
        residuals=pd.concat(residuals, ignore_index=True)
        if any(len(x) for x in residuals)
        else pd.DataFrame(),
```

> 注意：此 task 引入對 `write_artifacts` 尚不存在的參數呼叫；Task 7 才加簽名。故本 task 的驗證延到 Task 7（兩 task 一起綠）。**不要在此 task 單獨跑 runner。**

- [ ] **Step 2: 靜態檢查（不執行 runner）**

Run: `uv run ruff check quantcore/experiments/runner.py`
Expected: PASS（無語法/lint 錯；未使用 import 為 0）

- [ ] **Step 3: Commit（與 Task 7 相鄰，暫不跑 runner 測試）**

```bash
git add quantcore/experiments/runner.py
git commit -m "feat(phase7a): runner 攤平 correlation/residuals/trades + corr_fell_back 欄（待 Task 7 落盤）"
```

---

## Task 7: `write_artifacts` 落盤 `trades.parquet` + `model_details/` + INV-6 涵蓋 trades

**Files:**
- Modify: `quantcore/experiments/tracking.py`
- Modify: `tests/test_invariants/test_reproducibility.py:23`
- Test: `tests/test_experiments/test_model_details.py`（新增）

- [ ] **Step 1: 寫失敗測試**

新增 `tests/test_experiments/test_model_details.py`：

```python
"""runner 落盤 trades.parquet + model_details/（Phase 7a）。"""

import numpy as np
import pandas as pd

from quantcore.config import load_config
from quantcore.experiments.runner import run_experiment
from tests.fixtures.synthetic import make_dates, make_snapshot


def _cfg():
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["SPY", "QQQ", "IWM"]
    cfg.universe.min_history_days = 5
    cfg.signal.top_k = 2
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    cfg.risk.corr_model = "ewma"
    return cfg


def _snap(n=80):
    dates = make_dates(n)
    rng = np.random.default_rng(3)
    return make_snapshot(
        {
            "SPY": list(100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))),
            "QQQ": list(200.0 * np.cumprod(1 + rng.normal(0.0005, 0.012, n))),
            "IWM": list(150.0 * np.cumprod(1 + rng.normal(0.0005, 0.013, n))),
        },
        dates,
    )


def test_run_emits_trades_and_model_details(tmp_path):
    d = run_experiment(
        cfg=_cfg(),
        snapshot=_snap(),
        out_root=tmp_path,
        label="md",
        strategy_ids=["bh_spy", "full"],
        now=pd.Timestamp("2026-07-29T10:00:00"),
    )
    # trades.parquet 一級 artifact
    trades = pd.read_parquet(d / "trades.parquet")
    assert {"execution_date", "strategy_id", "ticker", "delta_weight", "fill_price", "cost"} <= set(
        trades.columns
    )
    assert (trades["strategy_id"] == "bh_spy").any()  # 非 vol 策略也有交易

    # model_details/correlation.parquet：只有 full（算 R）
    corr = pd.read_parquet(d / "model_details" / "correlation.parquet")
    assert set(corr["strategy_id"].unique()) == {"full"}
    assert {"ticker_i", "ticker_j", "corr"} <= set(corr.columns)

    # model_details/residuals.parquet：full 的殘差
    resid = pd.read_parquet(d / "model_details" / "residuals.parquet")
    assert {"strategy_id", "ticker", "date", "std_resid"} <= set(resid.columns)

    # corr_fell_back 欄進 decisions（ewma → 全 None/NA）
    dec = pd.read_parquet(d / "decisions.parquet")
    assert "corr_fell_back" in dec.columns
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_experiments/test_model_details.py -v`
Expected: FAIL（`TypeError: write_artifacts() got an unexpected keyword argument 'trades'`）

- [ ] **Step 3: 實作 tracking**

`quantcore/experiments/tracking.py`：

把 `_content_hashes` 改為多收 `trades` 並多一個 hash 條目：

```python
def _content_hashes(
    nav: pd.DataFrame,
    weights: pd.DataFrame,
    decisions: pd.DataFrame,
    trades: pd.DataFrame,
    metrics: dict,
) -> dict:
    """輸出檔的內容 hash，供 INV-6 以內容驗證可重現性。

    model_details/*（相關矩陣、殘差）為深掘診斷、不進 identity 合約（設計計畫 §設計決定）。
    """
    return {
        "nav.parquet": _frame_content_hash(nav, ["strategy_id", "date"]),
        "weights.parquet": _frame_content_hash(weights, ["strategy_id", "date", "ticker"]),
        "decisions.parquet": _frame_content_hash(decisions, ["strategy_id", "decision_date"])
        if not decisions.empty
        else hashlib.sha256(b"").hexdigest(),
        "trades.parquet": _frame_content_hash(trades, ["strategy_id", "execution_date", "ticker"])
        if not trades.empty
        else hashlib.sha256(b"").hexdigest(),
        "metrics.json": hashlib.sha256(
            json.dumps(_json_safe(metrics), sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }
```

把 `write_artifacts` 簽名加三個參數（在 `decisions` 之後、`metrics` 之前）：

```python
def write_artifacts(
    run_dir: Path,
    cfg_dict: dict,
    identity: dict,
    created_at: str,
    nav: pd.DataFrame,
    weights: pd.DataFrame,
    decisions: pd.DataFrame,
    trades: pd.DataFrame,
    correlations: pd.DataFrame,
    residuals: pd.DataFrame,
    metrics: dict,
) -> None:
```

把 `manifest.json` 內 `"content_hashes": _content_hashes(nav, weights, decisions, metrics),` 改為：

```python
                "content_hashes": _content_hashes(nav, weights, decisions, trades, metrics),
```

在 `_write_parquet(decisions, run_dir / "decisions.parquet")` 之後加 trades + model_details 落盤：

```python
    _write_parquet(trades, run_dir / "trades.parquet")
    if not correlations.empty or not residuals.empty:
        md = run_dir / "model_details"
        md.mkdir(exist_ok=True)
        if not correlations.empty:
            _write_parquet(correlations, md / "correlation.parquet")
        if not residuals.empty:
            _write_parquet(residuals, md / "residuals.parquet")
```

- [ ] **Step 4: 跑測試確認通過（Task 6 + 7 一起綠）**

Run: `uv run pytest tests/test_experiments/test_model_details.py tests/test_experiments/ -v`
Expected: PASS

- [ ] **Step 5: INV-6 涵蓋 trades**

`tests/test_invariants/test_reproducibility.py:23` 把：

```python
DATA_FRAMES = ("nav.parquet", "weights.parquet", "decisions.parquet")
```

改為：

```python
DATA_FRAMES = ("nav.parquet", "weights.parquet", "decisions.parquet", "trades.parquet")
```

Run: `uv run pytest tests/test_invariants/test_reproducibility.py -v`
Expected: PASS（兩次跑 trades 內容 + content_hash 逐格相同——bh_spy/ew_menu 皆有交易，涵蓋非空 trades）

- [ ] **Step 6: Commit**

```bash
git add quantcore/experiments/tracking.py tests/test_experiments/test_model_details.py tests/test_invariants/test_reproducibility.py
git commit -m "feat(phase7a): write_artifacts 落盤 trades.parquet + model_details/；INV-6 涵蓋 trades"
```

---

## Task 8: 全套件閘門（INV-3/5/6 + ruff）

**Files:** 無（驗證）

- [ ] **Step 1: 跑全部不變量測試**

Run: `uv run pytest tests/test_invariants/ -v`
Expected: PASS（INV-1~6 全綠；重點 INV-3 共變異數合法、INV-5 會計恆等式、INV-6 可重現）

- [ ] **Step 2: 跑全套件**

Run: `uv run pytest`
Expected: PASS（`requires_snapshot` 標記的本機 AC 閘門若本機有快照則一起跑；CI 環境自動 skip）

- [ ] **Step 3: lint/format**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: PASS

- [ ] **Step 4: Commit（若 format 有改動）**

```bash
git add -A
git commit -m "chore(phase7a): ruff format" || echo "無 format 改動"
```

---

## Task 9: 重跑 2 個 canonical run（dcc/ewma）+ 落盤驗證

**Files:**
- Create: `config/canonical_ewma.yaml`、`config/canonical_dcc.yaml`（copy default，改 `risk.corr_model`）

> 本 task 為引擎輸出的真實資料驗證（非 TDD）。需本機快照 `2026-07-16_20ed09`。

- [ ] **Step 1: 確認 default 指向真實快照**

Run: `uv run python -c "from quantcore.config import load_config; c=load_config('quantcore/config/default.yaml'); print('snapshot=', c.snapshot, 'corr_model=', c.risk.corr_model)"`
Expected: 印出 `snapshot= 2026-07-16_20ed09`（若不同，記下實際值，下面兩份 config 沿用同一 snapshot）。

- [ ] **Step 2: 建兩份 canonical config**

以 `quantcore/config/default.yaml` 為底，複製兩份到 `config/`，唯一差異為 `risk.corr_model`：

```bash
cp quantcore/config/default.yaml config/canonical_ewma.yaml
cp quantcore/config/default.yaml config/canonical_dcc.yaml
```

編輯 `config/canonical_ewma.yaml`：把 `risk:` 區塊的 `corr_model:` 設為 `ewma`。
編輯 `config/canonical_dcc.yaml`：把 `risk:` 區塊的 `corr_model:` 設為 `dcc`。
（其餘欄位與 default 一致；不改任何其他參數，確保消融只差相關模型。）

- [ ] **Step 3: 跑 ewma canonical run（全 7 策略）**

Run:
```bash
uv run python -m quantcore.experiments.runner --config config/canonical_ewma.yaml --label canonical_ewma
```
Expected: 印出 `run 已完成：runs/<日期>_<時間>_canonical_ewma`。記下該路徑為 `$EWMA`。

- [ ] **Step 4: 跑 dcc canonical run（全 7 策略，較慢 ~167s/full）**

Run:
```bash
uv run python -m quantcore.experiments.runner --config config/canonical_dcc.yaml --label canonical_dcc
```
Expected: 印出 `run 已完成：runs/<日期>_<時間>_canonical_dcc`。記下該路徑為 `$DCC`。

- [ ] **Step 5: 真實資料落盤 + 對帳驗證**

Run（把 `RUN` 換成 `$DCC` 的實際路徑）：
```bash
uv run python - <<'PY'
import pandas as pd, glob, os
RUN = sorted(glob.glob("runs/*_canonical_dcc"))[-1]
print("驗證", RUN)
nav = pd.read_parquet(f"{RUN}/nav.parquet")
trades = pd.read_parquet(f"{RUN}/trades.parquet")
corr = pd.read_parquet(f"{RUN}/model_details/correlation.parquet")
resid = pd.read_parquet(f"{RUN}/model_details/residuals.parquet")
dec = pd.read_parquet(f"{RUN}/decisions.parquet")

# 對帳：full 策略逐執行日 Σ|Δw| == turnover、Σcost == cost
for sid in ("full", "bh_spy"):
    n = nav[nav.strategy_id == sid].set_index("date")
    tr = trades[trades.strategy_id == sid]
    bad_to = bad_c = 0
    for x_day, g in tr.groupby("execution_date"):
        if abs(g.delta_weight.abs().sum() - n.loc[x_day, "turnover"]) > 1e-9: bad_to += 1
        if abs(g.cost.sum() - n.loc[x_day, "cost"]) > 1e-6: bad_c += 1
    print(f"[{sid}] 交易日={tr.execution_date.nunique()} turnover 不符={bad_to} cost 不符={bad_c}")

# 相關矩陣只有 full/full_erc
print("correlation strategies:", sorted(corr.strategy_id.unique()))
# corr_fell_back：dcc 應有 True/False（非全 NA）
print("corr_fell_back 非空:", dec.corr_fell_back.notna().any(), "fallback 佔比:",
      dec[dec.strategy_id.isin(["full","full_erc"])].corr_fell_back.mean())
print("residuals tickers:", sorted(resid.ticker.unique())[:5], "…")
PY
```
Expected: 每策略 `turnover 不符=0 cost 不符=0`；`correlation strategies: ['full', 'full_erc']`（若 config 含 full_erc；預設 7 策略不含 full_erc，則為 `['full']`）；`corr_fell_back 非空: True`。

> 若對帳出現不符，**停下**進 systematic-debugging：blotter 與 accounting 的分解必為結構恆等，任何不符代表 Task 1/5 的接出有誤。

- [ ] **Step 6: Commit canonical config（run 目錄 gitignore，不進版控）**

```bash
git add config/canonical_ewma.yaml config/canonical_dcc.yaml
git commit -m "chore(phase7a): canonical run config（ewma/dcc，頁 4 疊圖用）"
```

---

## 完成後

計畫 1 完成 → 引擎已落盤 `trades.parquet` + `model_details/{correlation,residuals}.parquet` + `decisions.corr_fell_back`，且 2 個 canonical run（ewma/dcc）在本機 `runs/`。

**下一步**：進 Phase 7a **計畫 2（presentation）**——以本計畫產出的真實 artifact schema 為 ground truth，展開 `readers.py`（含 Decision Explorer 六層 golden = AC①）、`app.py`、9 頁、架構守護測試。屆時再開一份 writing-plans。

---

*Phase 7a 計畫 1 — 2026-07-29。實作設計文件 §3+§4。計畫 2（presentation）待本計畫執行完後展開。*
