# Phase 4b-2 — 波動目標策略 + engine 接線 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 4b-1 的 exposure/covariance/VolForecaster 組進 `voltarget_only`/`full` 策略、`mom_ivol` 遷移到 GARCH σ̂、engine 支援 log-only decision（band-blocked 落診斷不交易）、Diagnostics 決策當下記 `vol_fell_back`/`garch_params`、`vol_model` 預設翻 `garch_arch`。

**Architecture:** 新 `VolTargetStrategy` 基底封裝曝險機制（選擇日 refit、曝險檢查日 filter、build_covariance→portfolio_vol→target_exposure→最終權重），`full`/`voltarget_only` 各實作 `_select_and_weight`。engine `Decision` 加 `execute` 旗標把「落診斷」與「執行」分離。策略有狀態、引擎每 run 新建（不破 INV-6）。

**Tech Stack:** Python 3.11、numpy、pandas、pytest。

**規格/設計來源：** `DEVELOPMENT_GUIDE v1.2.md` §1.4/§1.6/§1.7/§5.2/§6.2/§6.3；設計文件 `docs/superpowers/specs/2026-07-22-phase4b2-strategies-wiring-design.md`。

**重要背景（給零脈絡的實作者）：**
- 依賴方向（CLAUDE.md）：`config ← data ← models ← signals/portfolio ← backtest ← experiments`。策略在 `backtest/`，可 import models/portfolio/signals。
- 既有（勿重寫）：
  - `backtest/strategy.py`：`Strategy`(ABC)、`Decision(target_weights, diagnostics)`、`Diagnostics`（欄位 eligible/selected/momentum_scores/absmom/sigma_hat/w_risky/sigma_p/exposure_raw/exposure_applied/band_blocked，皆 Optional）、`DecisionEvent.{SELECTION,EXPOSURE_CHECK}`。
  - `backtest/strategies/momentum_base.py`：`MomentumStrategy`（`decide` 做選標的+absmom+相對權重，`warmup_days=momentum_lookback+1`，抽象 `_risky_weights(selected, view)->(w_risky, sigma_hat)`）。
  - `backtest/strategies/bh_spy.py`：有狀態 Strategy 範例。
  - `backtest/ptview.py`：`view.history(ticker)`→該檔 ≤t 價格 DataFrame（欄 date/adj_close）；`view.prices`→long-format ≤t 切片。
  - `backtest/engine.py::run_strategy`：決策日呼叫 `strategy.decide(view, event)`，回非 None → 建 pending → 執行日 rebalance。
  - `portfolio/exposure.py::target_exposure(sigma_p, sigma_star, e_min, band, e_current)->ExposureResult(exposure_raw, exposure_applied, band_blocked)`。
  - `models/covariance.py::rolling_correlation(returns_window_df)->R_df`（label-aligned DataFrame）、`build_covariance(sigma_hat, R_df)->Σ_df`、`portfolio_vol(w_risky, cov_df)->float`。
  - `models/volatility/forecaster.py::VolForecaster(spec, ewma_lambda, horizon, garch_window)`：`refit(ticker, returns)->σ̂`、`filter(ticker, returns)->σ̂`、`last_fell_back(ticker)->bool`。快取為 `_CacheEntry(kind, arch_params, fell_back)`。
  - `portfolio/weighting.py::{inverse_vol, equal_weight}`；`portfolio/selection.py::{eligible_assets, select_top_k}`；`signals/momentum.py::{cross_sectional_momentum, absolute_momentum}`。
  - `experiments/runner.py::_diagnostics_row`：以 `j()`（JSON sort_keys）攤平 per-asset dict。
  - `backtest/accounting.py::CASH`（現金鍵）。
- **VolForecaster 只支援 garch_arch/ewma**（fit_volatility）。rolling_std（Phase 3 placeholder）退役為策略 vol 來源。
- 硬性規則：參數只在 config；commit 訊息繁中、conventional-commit、附 Co-Authored-By trailer。TDD：failing test → 確認失敗 → 實作 → 確認通過 → commit。每 task 後 `uv run pytest -q` 全綠、ruff 乾淨。
- 基線：全套 **244 passed**。

## 檔案結構

| 檔案 | 責任 | 動作 |
|------|------|------|
| `quantcore/backtest/strategy.py` | `Decision.execute` + `Diagnostics.{vol_fell_back,garch_params}` | 修改 |
| `quantcore/backtest/engine.py` | log-only decision（落診斷 / execute 才執行） | 修改 |
| `quantcore/experiments/runner.py` | `_diagnostics_row` 加兩欄 | 修改 |
| `quantcore/models/volatility/forecaster.py` | `last_params` | 修改 |
| `quantcore/config/schema.py` | `RiskConfig.corr_window` | 修改 |
| `quantcore/config/default.yaml` | `corr_window` + `vol_model→garch_arch` | 修改 |
| `quantcore/backtest/strategies/vol_target_base.py` | `VolTargetStrategy` + `RiskyState` + helpers | 新增 |
| `quantcore/backtest/strategies/voltarget_only.py` | `VoltargetOnly` | 新增 |
| `quantcore/backtest/strategies/full.py` | `Full` | 新增 |
| `quantcore/backtest/strategies/mom_ivol.py` | 遷移到 VolForecaster | 修改 |
| `quantcore/backtest/strategies/momentum_base.py` | `_vol_diagnostics` hook | 修改 |
| `quantcore/backtest/strategies/__init__.py` | 註冊 full/voltarget_only | 修改 |
| `tests/test_backtest/`、`tests/test_experiments/` | 端到端 + 各單元測試 | 新增/修改 |

---

## Task 1: `Decision.execute` + Diagnostics 兩欄

**Files:**
- Modify: `quantcore/backtest/strategy.py`
- Test: `tests/test_backtest/test_strategy_types.py`（新）

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_backtest/test_strategy_types.py`：

```python
"""Decision.execute 與 Diagnostics 新欄位的預設與可設定性。"""

from __future__ import annotations

from quantcore.backtest.strategy import Decision, Diagnostics


def test_decision_execute_defaults_true():
    d = Decision(target_weights={"CASH": 1.0}, diagnostics=Diagnostics(eligible=[], selected=[]))
    assert d.execute is True


def test_decision_execute_can_be_false():
    d = Decision(
        target_weights={"CASH": 1.0},
        diagnostics=Diagnostics(eligible=[], selected=[]),
        execute=False,
    )
    assert d.execute is False


def test_diagnostics_vol_fields_default_none():
    diag = Diagnostics(eligible=[], selected=[])
    assert diag.vol_fell_back is None
    assert diag.garch_params is None


def test_diagnostics_vol_fields_settable():
    diag = Diagnostics(
        eligible=["A"],
        selected=["A"],
        vol_fell_back={"A": True},
        garch_params={"A": {"omega": 0.1, "alpha": 0.08, "beta": 0.9, "nu": 7.0}},
    )
    assert diag.vol_fell_back == {"A": True}
    assert diag.garch_params["A"]["beta"] == 0.9
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_backtest/test_strategy_types.py -v`
Expected: FAIL（`Decision` 無 `execute` / `Diagnostics` 無新欄位）。

- [ ] **Step 3: 加欄位**

在 `quantcore/backtest/strategy.py`：`Diagnostics` 末尾（`band_blocked` 之後）加：

```python
    vol_fell_back: dict[str, bool] | None = None  # 每檔 GARCH 是否退回 EWMA（決策當下記，§6.2）
    garch_params: dict[str, dict[str, float] | None] | None = None  # 每檔 {omega,alpha,beta,nu}；EWMA/None
```

`Decision` 加欄位（`diagnostics` 之後）：

```python
    execute: bool = True  # False = 只落診斷、不 rebalance（band-blocked 曝險檢查，§1.7）
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_backtest/test_strategy_types.py -v`
Expected: 4 PASS。

- [ ] **Step 5: 全測試綠 + lint**

Run: `uv run pytest -q` 與 `uv run ruff check quantcore/backtest tests/test_backtest` + `uv run ruff format --check quantcore/backtest tests/test_backtest`
Expected: 綠、乾淨（既有策略 Decision 未帶 execute → 走預設 True，不受影響）。

- [ ] **Step 6: Commit**

```bash
git add quantcore/backtest/strategy.py tests/test_backtest/test_strategy_types.py
git commit -m "feat(backtest): Decision.execute + Diagnostics vol_fell_back/garch_params（§1.7/§6.2）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Engine log-only decision

**Files:**
- Modify: `quantcore/backtest/engine.py`（決策日區塊，約 74-99 行）
- Test: `tests/test_backtest/test_engine_log_only.py`（新）

**設計要點：** 回非 None 的 decision **一律落 decision_row**；只有 `decision.execute` 才建 pending、在執行日 rebalance。log-only 的 `execution_date` 記 None。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_backtest/test_engine_log_only.py`：

```python
"""engine 對 execute=False decision：落診斷但不執行、不換手（§1.7 log-only）。"""

from __future__ import annotations

import pandas as pd

from quantcore.backtest.clock import EventClock
from quantcore.backtest.engine import run_strategy
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


class _LogOnlyOnce(Strategy):
    """第一個決策日回 execute=False 的 log-only decision，其後不動作。"""

    strategy_id = "log_only_probe"

    def __init__(self, cfg):
        super().__init__(cfg)
        self._fired = False

    @property
    def warmup_days(self):
        return 2

    def decide(self, view, event):
        if self._fired:
            return None
        self._fired = True
        return Decision(
            target_weights={"SPY": 1.0, "CASH": 0.0},
            diagnostics=Diagnostics(eligible=["SPY"], selected=["SPY"], band_blocked=True),
            execute=False,
        )


def test_log_only_decision_records_row_but_no_turnover():
    dates = make_dates(12)
    snap = make_snapshot({"SPY": [100.0 + i for i in range(12)]}, dates)
    cfg = make_cfg(["SPY"], schedule={"selection_interval": 3, "exposure_check_interval": 3})
    clock = EventClock(dates, warmup=2, selection_interval=3, exposure_check_interval=3)
    nav, weights, decisions = run_strategy(snap, clock, _LogOnlyOnce(cfg), cfg)

    # 診斷有落盤（band_blocked=True 的那筆）
    assert len(decisions) == 1
    assert bool(decisions.iloc[0]["diagnostics"].band_blocked) is True
    assert decisions.iloc[0]["execution_date"] is None  # 未執行
    # 全程無換手（execute=False 不 rebalance；權重恆為初始全現金）
    assert float(nav["turnover"].sum()) == 0.0
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_backtest/test_engine_log_only.py -v`
Expected: FAIL —— 目前 engine 對非 None decision 一律建 pending、rebalance（會產生 turnover / execution_date 非 None）。

- [ ] **Step 3: 改 engine**

在 `quantcore/backtest/engine.py` 的決策日區塊，把 pending 建立與 decision_row 落盤改為：

```python
        if clock.is_decision_day(t):
            event = (
                DecisionEvent.SELECTION
                if clock.is_selection_day(t)
                else DecisionEvent.EXPOSURE_CHECK
            )
            decision = strategy.decide(make_view(snapshot, t), event)
            if decision is not None:
                exec_day = clock.execution_day(t)
                if exec_day is not None:
                    decision_rows.append(
                        {
                            "decision_date": t,
                            "execution_date": exec_day if decision.execute else None,
                            "strategy_id": strategy.strategy_id,
                            "event": str(event),
                            "diagnostics": decision.diagnostics,
                            "target_weights": dict(decision.target_weights),
                        }
                    )
                    if decision.execute:
                        if pending is not None:
                            raise RuntimeError(
                                f"{t:%Y-%m-%d} 產生新決策，但前次決策尚未執行——"
                                "時程間隔設定有誤（見 EventClock 的間隔 ≥ 2 檢查）"
                            )
                        pending = _Pending(
                            target=dict(decision.target_weights), execution_day=exec_day
                        )
```

（即：decision_row 移出 `if pending...` 之外、對所有非 None decision 落盤；pending 建立包在 `if decision.execute` 內。）

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_backtest/test_engine_log_only.py -v`
Expected: PASS。

- [ ] **Step 5: 全測試綠 + lint**

Run: `uv run pytest -q`（既有策略 execute 恆 True，行為不變）與 `uv run ruff check quantcore/backtest tests/test_backtest` + `uv run ruff format --check quantcore/backtest tests/test_backtest`
Expected: 綠、乾淨。

- [ ] **Step 6: Commit**

```bash
git add quantcore/backtest/engine.py tests/test_backtest/test_engine_log_only.py
git commit -m "feat(backtest): engine log-only decision（execute=False 落診斷不執行，§1.7）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: runner 落盤兩新診斷欄

**Files:**
- Modify: `quantcore/experiments/runner.py`（`_diagnostics_row`）
- Test: `tests/test_experiments/test_decisions_diagnostics.py`（既有，續加）

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_experiments/test_decisions_diagnostics.py` 加入（檔頭已 import runner 的攤平函式或 Diagnostics；若無則補 `from quantcore.experiments.runner import _diagnostics_row` 與 `from quantcore.backtest.strategy import Diagnostics`）：

```python
def test_diagnostics_row_includes_vol_fell_back_and_garch_params():
    diag = Diagnostics(
        eligible=["A"],
        selected=["A"],
        vol_fell_back={"A": False},
        garch_params={"A": {"omega": 0.1, "alpha": 0.08, "beta": 0.9, "nu": 7.0}},
    )
    row = _diagnostics_row(diag)
    assert "vol_fell_back" in row and "garch_params" in row
    import json

    assert json.loads(row["vol_fell_back"]) == {"A": False}
    assert json.loads(row["garch_params"])["A"]["beta"] == 0.9


def test_diagnostics_row_vol_fields_none_when_absent():
    row = _diagnostics_row(Diagnostics(eligible=[], selected=[]))
    assert row["vol_fell_back"] is None
    assert row["garch_params"] is None
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_experiments/test_decisions_diagnostics.py -k vol_fell_back -v`
Expected: FAIL（`_diagnostics_row` 無這兩欄）。

- [ ] **Step 3: 改 runner**

在 `quantcore/experiments/runner.py::_diagnostics_row` 的回傳 dict 末尾（`band_blocked` 之後）加：

```python
        "vol_fell_back": j(diag.vol_fell_back),
        "garch_params": j(diag.garch_params),
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_experiments/test_decisions_diagnostics.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 全測試綠**

Run: `uv run pytest -q`
Expected: 綠。

- [ ] **Step 6: Commit**

```bash
git add quantcore/experiments/runner.py tests/test_experiments/test_decisions_diagnostics.py
git commit -m "feat(experiments): decisions.parquet 落 vol_fell_back/garch_params（§6.2）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `VolForecaster.last_params`

**Files:**
- Modify: `quantcore/models/volatility/forecaster.py`
- Test: `tests/test_models/test_forecaster.py`（續加）

**設計要點：** GARCH ticker 回可讀 `{omega,alpha,beta,nu}`（自快取 arch 向量取 index 1-4，順序為 [mu,omega,alpha,beta,nu]）；EWMA/fallback（`_CacheEntry.kind=="ewma"` / `arch_params is None`）回 None。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_models/test_forecaster.py` 加入：

```python
def test_last_params_returns_readable_dict_for_garch():
    f = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    f.refit("AAA", _returns())
    p = f.last_params("AAA")
    assert set(p) == {"omega", "alpha", "beta", "nu"}
    assert p["alpha"] + p["beta"] < 1.0  # 平穩


def test_last_params_none_for_ewma_spec():
    f = VolForecaster("ewma", ewma_lambda=0.94, horizon=21, garch_window=1000)
    f.refit("AAA", _returns())
    assert f.last_params("AAA") is None
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_models/test_forecaster.py -k last_params -v`
Expected: FAIL（無 `last_params`）。

- [ ] **Step 3: 實作**

在 `quantcore/models/volatility/forecaster.py` 的 `VolForecaster` 加方法（置於 `last_fell_back` 附近）：

```python
    def last_params(self, ticker: str) -> dict[str, float] | None:
        """GARCH ticker 回可讀 {omega,alpha,beta,nu}；EWMA/fallback 回 None（供診斷落盤）。"""
        entry = self._cache[ticker]
        if entry.kind != "garch" or entry.arch_params is None:
            return None
        p = entry.arch_params  # [mu, omega, alpha[1], beta[1], nu]
        return {
            "omega": float(p[1]),
            "alpha": float(p[2]),
            "beta": float(p[3]),
            "nu": float(p[4]),
        }
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_models/test_forecaster.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 全測試綠 + lint**

Run: `uv run pytest -q` 與 `uv run ruff check quantcore/models tests/test_models` + `uv run ruff format --check quantcore/models tests/test_models`
Expected: 綠、乾淨。

- [ ] **Step 6: Commit**

```bash
git add quantcore/models/volatility/forecaster.py tests/test_models/test_forecaster.py
git commit -m "feat(models): VolForecaster.last_params 供 GARCH 參數落盤（§6.2）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: config `corr_window`

**Files:**
- Modify: `quantcore/config/schema.py`（`RiskConfig`）
- Modify: `quantcore/config/default.yaml`
- Test: `tests/test_config.py`

（本 task **不**翻 `vol_model`，留 Task 11。）

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_config.py` 末尾加：

```python
def test_risk_corr_window_loaded():
    cfg = load_config("quantcore/config/default.yaml")
    assert cfg.risk.corr_window == 252
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_config.py::test_risk_corr_window_loaded -v`
Expected: FAIL。

- [ ] **Step 3: 加 schema 欄位**

在 `quantcore/config/schema.py` 的 `RiskConfig`（`garch_window` 之後）加：

```python
    corr_window: int = Field(ge=2)  # 滾動樣本相關窗（交易日）；實務 ≫ top_k 保 R 滿秩
```

- [ ] **Step 4: 加 default.yaml**

在 `quantcore/config/default.yaml` 的 `risk:` 區塊（`garch_window` 之後）加：

```yaml
  corr_window: 252                  # §1.6 滾動樣本相關窗（交易日）；≫ top_k 保 R 滿秩，可消融 {126,252}
```

- [ ] **Step 5: 執行確認通過 + 全測試綠**

Run: `uv run pytest tests/test_config.py -v` 與 `uv run pytest -q`
Expected: 綠。

- [ ] **Step 6: Commit**

```bash
git add quantcore/config/schema.py quantcore/config/default.yaml tests/test_config.py
git commit -m "feat(config): risk 加 corr_window（滾動相關窗，§1.6）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `VolTargetStrategy` 基底 + helpers

**Files:**
- Create: `quantcore/backtest/strategies/vol_target_base.py`
- Test: `tests/test_backtest/test_vol_target_base.py`

**設計要點：** 有狀態基底。SELECTION → `_select_and_weight`（子類，內部 refit）；EXPOSURE_CHECK → 用快取 + `filter` 更新 σ̂。共用尾段：build_covariance → portfolio_vol → target_exposure → 最終權重（passing 檔 E×w_risky、failing 轉現金）。band-blocked（曝險檢查）→ `execute=False`、`_e_current` 不變。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_backtest/test_vol_target_base.py`：

```python
"""VolTargetStrategy 基底：選擇/曝險檢查流程、權重守恆、band log-only。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategy import DecisionEvent
from quantcore.backtest.strategies.vol_target_base import RiskyState, VolTargetStrategy
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


class _FixedRisky(VolTargetStrategy):
    """測試用：固定選 A、B，σ̂ 由 forecaster（ewma）決定；absmom 可注入。"""

    strategy_id = "fixed_risky_probe"

    def __init__(self, cfg, absmom):
        super().__init__(cfg)
        self._absmom = absmom

    @property
    def warmup_days(self):
        return 2

    def _select_and_weight(self, view):
        from quantcore.portfolio.weighting import inverse_vol
        from quantcore.backtest.strategies.vol_target_base import ticker_returns

        selected = ["A", "B"]
        sigma_hat = {t: self._forecaster.refit(t, ticker_returns(view, t)) for t in selected}
        return RiskyState(
            eligible=selected,
            selected=selected,
            momentum_scores=None,
            w_risky=inverse_vol(sigma_hat),
            sigma_hat=sigma_hat,
            absmom={t: self._absmom.get(t, True) for t in selected},
            garch_params={t: self._forecaster.last_params(t) for t in selected},
            fell_back={t: self._forecaster.last_fell_back(t) for t in selected},
        )


def _snap(n=60):
    dates = make_dates(n)
    rng = np.random.default_rng(0)
    a = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    b = 100 * np.cumprod(1 + rng.normal(0, 0.02, n))
    return make_snapshot({"A": list(a), "B": list(b)}, dates), dates


def _cfg():
    # ewma vol（短序列可跑）、小 corr_window
    return make_cfg(
        ["A", "B"],
        risk={"vol_model": "ewma", "corr_window": 30, "garch_window": 100},
        signal={"top_k": 2},
    )


def test_selection_produces_valid_weights_summing_to_one():
    snap, dates = _snap()
    strat = _FixedRisky(_cfg(), absmom={"A": True, "B": True})
    dec = strat.decide(make_view(snap, dates[50]), DecisionEvent.SELECTION)
    assert dec is not None and dec.execute is True
    total = sum(dec.target_weights.values())
    assert total == pytest.approx(1.0)
    E = dec.diagnostics.exposure_applied
    assert 0.0 < E <= 1.0
    # 風險權重和 = E（absmom 全過），cash = 1-E
    assert dec.target_weights[CASH] == pytest.approx(1.0 - E)


def test_absmom_fail_routes_to_cash():
    snap, dates = _snap()
    strat = _FixedRisky(_cfg(), absmom={"A": True, "B": False})  # B fail
    dec = strat.decide(make_view(snap, dates[50]), DecisionEvent.SELECTION)
    assert "B" not in dec.target_weights or dec.target_weights.get("B", 0.0) == 0.0
    assert sum(dec.target_weights.values()) == pytest.approx(1.0)


def test_exposure_check_before_selection_returns_none():
    snap, dates = _snap()
    strat = _FixedRisky(_cfg(), absmom={"A": True, "B": True})
    assert strat.decide(make_view(snap, dates[50]), DecisionEvent.EXPOSURE_CHECK) is None


def test_band_block_yields_log_only_decision():
    snap, dates = _snap()
    strat = _FixedRisky(_cfg(), absmom={"A": True, "B": True})
    strat.decide(make_view(snap, dates[50]), DecisionEvent.SELECTION)  # 設 e_current
    e0 = strat._e_current
    # 曝險檢查：σ̂ 幾乎不變 → |ΔE| 極可能 ≤ band → block → execute=False
    dec = strat.decide(make_view(snap, dates[55]), DecisionEvent.EXPOSURE_CHECK)
    if dec.diagnostics.band_blocked:
        assert dec.execute is False
        assert strat._e_current == e0  # 未更新


import pytest  # noqa: E402
```

（`import pytest` 置檔頭；此處示意，實作時放頂部。）

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_backtest/test_vol_target_base.py -v`
Expected: FAIL（`ModuleNotFoundError: vol_target_base`）。

- [ ] **Step 3: 實作 vol_target_base.py**

Create `quantcore/backtest/strategies/vol_target_base.py`：

```python
"""波動目標曝險機制基底（規格 §1.6/§1.7）。full/voltarget_only 共用。

有狀態（forecaster + e_current + 上次選擇快取），引擎每 run 新建（比照 bh_spy，不破 INV-6）。
子類實作 _select_and_weight（選擇日：選標的、相對權重、refit σ̂）。
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, replace

import pandas as pd

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.models.covariance import build_covariance, portfolio_vol, rolling_correlation
from quantcore.models.volatility.forecaster import VolForecaster
from quantcore.portfolio.exposure import target_exposure


@dataclass(frozen=True)
class RiskyState:
    eligible: list[str]
    selected: list[str]
    momentum_scores: dict[str, float] | None
    w_risky: dict[str, float]              # Σ=1 over selected
    sigma_hat: dict[str, float]
    absmom: dict[str, bool]
    garch_params: dict[str, dict[str, float] | None]
    fell_back: dict[str, bool]


def ticker_returns(view: PointInTimeView, ticker: str) -> pd.Series:
    """該檔 ≤t 的日報酬（自 adj_close）。"""
    return view.history(ticker)["adj_close"].astype("float64").pct_change().dropna()


def _selected_returns_window(view: PointInTimeView, selected: list[str], window: int) -> pd.DataFrame:
    """date×ticker 報酬窗（選定資產尾端 window 根），供 rolling_correlation。"""
    wide = view.prices.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    return wide[selected].pct_change().tail(window)


class VolTargetStrategy(Strategy):
    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self._forecaster = VolForecaster(
            cfg.risk.vol_model,
            cfg.risk.ewma_lambda,
            cfg.risk.forecast_horizon,
            cfg.risk.garch_window,
        )
        self._e_current: float | None = None
        self._cache: RiskyState | None = None

    @abstractmethod
    def _select_and_weight(self, view: PointInTimeView) -> RiskyState | None:
        """選擇日：回 RiskyState（內部 refit σ̂）；無合格資產回 None。"""

    def _refilter(self, view: PointInTimeView, cached: RiskyState) -> RiskyState:
        """曝險檢查日：以 filter 更新 σ̂，其餘沿用快取。"""
        sigma_hat = {t: self._forecaster.filter(t, ticker_returns(view, t)) for t in cached.selected}
        return replace(cached, sigma_hat=sigma_hat)

    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        cfg = self._cfg
        if event is DecisionEvent.SELECTION:
            state = self._select_and_weight(view)
            if state is None:
                return None
            self._cache = state
            e_current = None
        else:  # EXPOSURE_CHECK
            if self._cache is None:
                return None
            state = self._refilter(view, self._cache)
            e_current = self._e_current

        window = _selected_returns_window(view, state.selected, cfg.risk.corr_window)
        R = rolling_correlation(window)
        cov = build_covariance(state.sigma_hat, R)
        sigma_p = portfolio_vol(state.w_risky, cov)
        exp = target_exposure(
            sigma_p,
            cfg.risk.vol_target_annual,
            cfg.risk.exposure_min,
            cfg.risk.exposure_band,
            e_current,
        )

        weights = {
            t: exp.exposure_applied * state.w_risky[t]
            for t in state.selected
            if state.absmom.get(t, False)
        }
        cash = 1.0 - sum(weights.values())

        diag = Diagnostics(
            eligible=state.eligible,
            selected=state.selected,
            momentum_scores=state.momentum_scores,
            absmom=state.absmom,
            sigma_hat=state.sigma_hat,
            w_risky=state.w_risky,
            sigma_p=sigma_p,
            exposure_raw=exp.exposure_raw,
            exposure_applied=exp.exposure_applied,
            band_blocked=exp.band_blocked,
            vol_fell_back=state.fell_back,
            garch_params=state.garch_params,
        )
        if not exp.band_blocked:
            self._e_current = exp.exposure_applied
        return Decision(
            target_weights={**weights, CASH: cash},
            diagnostics=diag,
            execute=not exp.band_blocked,
        )
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_backtest/test_vol_target_base.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 全測試綠 + lint**

Run: `uv run pytest -q` 與 `uv run ruff check quantcore/backtest tests/test_backtest` + `uv run ruff format --check quantcore/backtest tests/test_backtest`
Expected: 綠、乾淨。

- [ ] **Step 6: Commit**

```bash
git add quantcore/backtest/strategies/vol_target_base.py tests/test_backtest/test_vol_target_base.py
git commit -m "feat(strategies): VolTargetStrategy 曝險機制基底（§1.6/§1.7）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: `voltarget_only` 策略

**Files:**
- Create: `quantcore/backtest/strategies/voltarget_only.py`
- Test: `tests/test_backtest/test_voltarget_only.py`

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_backtest/test_voltarget_only.py`：

```python
"""voltarget_only：SPY + 波動目標（單資產 σ̂_p=σ̂_SPY）。"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategy import DecisionEvent
from quantcore.backtest.strategies.voltarget_only import VoltargetOnly
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def _snap(n=60):
    dates = make_dates(n)
    rng = np.random.default_rng(1)
    spy = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    return make_snapshot({"SPY": list(spy)}, dates), dates


def _cfg():
    return make_cfg(["SPY"], risk={"vol_model": "ewma", "corr_window": 30, "garch_window": 100})


def test_voltarget_only_holds_spy_with_exposure():
    snap, dates = _snap()
    strat = VoltargetOnly(_cfg())
    dec = strat.decide(make_view(snap, dates[50]), DecisionEvent.SELECTION)
    E = dec.diagnostics.exposure_applied
    assert dec.target_weights["SPY"] == pytest.approx(E)
    assert dec.target_weights[CASH] == pytest.approx(1.0 - E)
    # 單資產：σ̂_p == σ̂_SPY
    assert dec.diagnostics.sigma_p == pytest.approx(dec.diagnostics.sigma_hat["SPY"])


def test_voltarget_only_strategy_id():
    assert VoltargetOnly.strategy_id == "voltarget_only"
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_backtest/test_voltarget_only.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 實作**

Create `quantcore/backtest/strategies/voltarget_only.py`：

```python
"""voltarget_only —— 持有 SPY + GARCH 波動目標（規格 §6.3）。

存在理由：消融——只有倉位（曝險）層，無動量選擇、無 absmom。
單資產 → R=[[1]]、σ̂_p=σ̂_SPY，走 VolTargetStrategy 同一路徑不特判。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategies.vol_target_base import RiskyState, VolTargetStrategy, ticker_returns


class VoltargetOnly(VolTargetStrategy):
    strategy_id = "voltarget_only"

    @property
    def warmup_days(self) -> int:
        return self._cfg.universe.min_history_days

    def _select_and_weight(self, view: PointInTimeView) -> RiskyState | None:
        sigma = self._forecaster.refit("SPY", ticker_returns(view, "SPY"))
        return RiskyState(
            eligible=["SPY"],
            selected=["SPY"],
            momentum_scores=None,
            w_risky={"SPY": 1.0},
            sigma_hat={"SPY": sigma},
            absmom={"SPY": True},
            garch_params={"SPY": self._forecaster.last_params("SPY")},
            fell_back={"SPY": self._forecaster.last_fell_back("SPY")},
        )
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_backtest/test_voltarget_only.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 全測試綠 + lint**

Run: `uv run pytest -q` 與 `uv run ruff check quantcore/backtest tests/test_backtest` + `uv run ruff format --check quantcore/backtest tests/test_backtest`
Expected: 綠、乾淨。

- [ ] **Step 6: Commit**

```bash
git add quantcore/backtest/strategies/voltarget_only.py tests/test_backtest/test_voltarget_only.py
git commit -m "feat(strategies): voltarget_only（SPY + 波動目標，§6.3）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: `full` 策略

**Files:**
- Create: `quantcore/backtest/strategies/full.py`
- Test: `tests/test_backtest/test_full.py`

**設計要點：** 動量選 K + inverse-vol（GARCH σ̂）+ absmom + 波動目標。σ̂_p 用全 selected 的 w_risky（Σ=1）算 E；passing 檔 E×w_risky、failing 轉現金（§1.6 Step 3）。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_backtest/test_full.py`：

```python
"""full：動量 + inverse-vol + absmom + 波動目標（主策略，§6.3）。"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategy import DecisionEvent
from quantcore.backtest.strategies.full import Full
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def _snap(n=320):
    dates = make_dates(n)
    rng = np.random.default_rng(2)
    prices = {}
    for i, tk in enumerate(["A", "B", "C", "D"]):
        drift = 0.0003 * (i + 1)  # 不同動量
        prices[tk] = list(100 * np.cumprod(1 + rng.normal(drift, 0.01, n)))
    return make_snapshot(prices, dates), dates


def _cfg():
    return make_cfg(
        ["A", "B", "C", "D"],
        risk={"vol_model": "ewma", "corr_window": 60, "garch_window": 120},
        signal={"top_k": 2, "momentum_lookback": 120, "momentum_skip": 5},
        universe={"min_history_days": 130},
    )


def test_full_selection_weights_sum_to_one_and_scaled_by_exposure():
    snap, dates = _snap()
    strat = Full(_cfg())
    dec = strat.decide(make_view(snap, dates[300]), DecisionEvent.SELECTION)
    assert dec is not None
    assert sum(dec.target_weights.values()) == pytest.approx(1.0)
    E = dec.diagnostics.exposure_applied
    risky_sum = sum(v for k, v in dec.target_weights.items() if k != CASH)
    # 全過情形下 risky_sum == E×Σw_risky == E（Σw_risky=1）
    assert risky_sum == pytest.approx(E, abs=1e-9)
    assert len(dec.diagnostics.selected) == 2
    assert dec.diagnostics.sigma_p > 0


def test_full_records_garch_diagnostics():
    snap, dates = _snap()
    dec = Full(_cfg()).decide(make_view(snap, dates[300]), DecisionEvent.SELECTION)
    # ewma spec → garch_params 皆 None、fell_back 皆 False（診斷欄仍落）
    assert set(dec.diagnostics.vol_fell_back) == set(dec.diagnostics.selected)
    assert set(dec.diagnostics.garch_params) == set(dec.diagnostics.selected)


def test_full_warmup_is_max_of_momentum_and_history():
    cfg = _cfg()
    strat = Full(cfg)
    assert strat.warmup_days == max(cfg.signal.momentum_lookback + 1, cfg.universe.min_history_days)
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_backtest/test_full.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 實作**

Create `quantcore/backtest/strategies/full.py`：

```python
"""full —— 動量 + inverse-vol + 絕對動量 + 波動目標（主策略，規格 §1、§6.3）。

σ̂_p 用全 selected 的 w_risky（Σ=1）算 E；passing 檔 w_i=E×w_risky_i、
absmom failing 檔的 E×w_risky_i 轉現金（§1.6 Step 3）。σ̂ 由 GARCH（VolForecaster）。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategies.vol_target_base import RiskyState, VolTargetStrategy, ticker_returns
from quantcore.portfolio.selection import eligible_assets, select_top_k
from quantcore.portfolio.weighting import inverse_vol
from quantcore.signals.momentum import absolute_momentum, cross_sectional_momentum


class Full(VolTargetStrategy):
    strategy_id = "full"

    @property
    def warmup_days(self) -> int:
        return max(self._cfg.signal.momentum_lookback + 1, self._cfg.universe.min_history_days)

    def _select_and_weight(self, view: PointInTimeView) -> RiskyState | None:
        cfg = self._cfg
        elig = eligible_assets(view.prices, cfg.universe.menu, cfg.universe.min_history_days)
        scores = cross_sectional_momentum(
            view.prices, cfg.signal.momentum_lookback, cfg.signal.momentum_skip
        )
        scores = {t: v for t, v in scores.items() if t in elig}
        if not scores:
            return None
        selected = select_top_k(scores, cfg.signal.top_k)

        sigma_hat: dict[str, float] = {}
        garch_params: dict[str, dict[str, float] | None] = {}
        fell_back: dict[str, bool] = {}
        for t in selected:
            sigma_hat[t] = self._forecaster.refit(t, ticker_returns(view, t))
            garch_params[t] = self._forecaster.last_params(t)
            fell_back[t] = self._forecaster.last_fell_back(t)

        w_risky = inverse_vol(sigma_hat)
        absmom_all = absolute_momentum(view.prices, view.rates, cfg.signal.momentum_lookback)
        absmom = {t: bool(absmom_all.get(t, False)) for t in selected}
        return RiskyState(
            eligible=elig,
            selected=selected,
            momentum_scores=scores,
            w_risky=w_risky,
            sigma_hat=sigma_hat,
            absmom=absmom,
            garch_params=garch_params,
            fell_back=fell_back,
        )
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_backtest/test_full.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 全測試綠 + lint**

Run: `uv run pytest -q` 與 `uv run ruff check quantcore/backtest tests/test_backtest` + `uv run ruff format --check quantcore/backtest tests/test_backtest`
Expected: 綠、乾淨。

- [ ] **Step 6: Commit**

```bash
git add quantcore/backtest/strategies/full.py tests/test_backtest/test_full.py
git commit -m "feat(strategies): full 動量+inverse-vol+absmom+波動目標（§1、§6.3）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: 註冊 full / voltarget_only

**Files:**
- Modify: `quantcore/backtest/strategies/__init__.py`
- Test: `tests/test_backtest/test_strategies.py`（既有，續加）

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_backtest/test_strategies.py` 加：

```python
def test_full_and_voltarget_only_registered():
    from quantcore.backtest.strategies import STRATEGIES

    assert "full" in STRATEGIES
    assert "voltarget_only" in STRATEGIES
    assert STRATEGIES["full"].strategy_id == "full"
    assert STRATEGIES["voltarget_only"].strategy_id == "voltarget_only"
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_backtest/test_strategies.py -k registered -v`
Expected: FAIL。

- [ ] **Step 3: 註冊**

改 `quantcore/backtest/strategies/__init__.py`：加 import 與註冊表項：

```python
from quantcore.backtest.strategies.full import Full
from quantcore.backtest.strategies.voltarget_only import VoltargetOnly
```

`STRATEGIES` dict 加：

```python
    Full.strategy_id: Full,
    VoltargetOnly.strategy_id: VoltargetOnly,
```

`__all__` 加 `"Full"`, `"VoltargetOnly"`。

- [ ] **Step 4: 執行確認通過 + 全測試綠 + lint**

Run: `uv run pytest tests/test_backtest/test_strategies.py -v`、`uv run pytest -q`、`uv run ruff check quantcore/backtest` + `uv run ruff format --check quantcore/backtest`
Expected: 綠、乾淨。

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/strategies/__init__.py tests/test_backtest/test_strategies.py
git commit -m "feat(strategies): 註冊 full / voltarget_only（§6.3）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: `mom_ivol` 遷移到 GARCH σ̂ + `_vol_diagnostics` hook

**Files:**
- Modify: `quantcore/backtest/strategies/momentum_base.py`（加 `_vol_diagnostics` hook + 填診斷）
- Modify: `quantcore/backtest/strategies/mom_ivol.py`
- Test: `tests/test_backtest/test_mom_strategies.py`（既有，續加/調整）

**設計要點：** `MomentumStrategy` 加可覆寫 `_vol_diagnostics(selected)->(garch_params, fell_back)`（預設 None,None），`decide` 填入 Diagnostics。`mom_ivol` 持 `VolForecaster`，`_risky_weights` 改 refit GARCH σ̂，`_vol_diagnostics` 回 forecaster 的 params/fell_back。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_backtest/test_mom_strategies.py` 加：

```python
def test_mom_ivol_uses_vol_forecaster_and_records_diagnostics():
    import numpy as np

    from quantcore.backtest.ptview import make_view
    from quantcore.backtest.strategy import DecisionEvent
    from quantcore.backtest.strategies.mom_ivol import MomentumInverseVol
    from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot

    n = 160
    dates = make_dates(n)
    rng = np.random.default_rng(3)
    prices = {tk: list(100 * np.cumprod(1 + rng.normal(0.0002 * (i + 1), 0.01, n)))
              for i, tk in enumerate(["A", "B", "C"])}
    snap = make_snapshot(prices, dates)
    cfg = make_cfg(
        ["A", "B", "C"],
        risk={"vol_model": "ewma", "garch_window": 100},
        signal={"top_k": 2, "momentum_lookback": 120, "momentum_skip": 5},
        universe={"min_history_days": 130},
    )
    strat = MomentumInverseVol(cfg)
    dec = strat.decide(make_view(snap, dates[150]), DecisionEvent.SELECTION)
    assert dec is not None
    # 診斷含 vol_fell_back（每檔入選）；ewma spec → garch_params 皆 None
    assert set(dec.diagnostics.vol_fell_back) == set(dec.diagnostics.selected)
    assert dec.diagnostics.sigma_hat is not None
    # 相對權重和 = 1（inverse-vol，E=1 無曝險層）
    risky = {k: v for k, v in dec.target_weights.items() if k != "CASH"}
    assert sum(risky.values()) == pytest.approx(1.0)
```

（若既有 mom_ivol 測試以 rolling_std/vol_window 斷言特定值，改為 `risk={"vol_model": "ewma"}` override 並改斷結構性關係。）

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_backtest/test_mom_strategies.py -k forecaster -v`
Expected: FAIL。

- [ ] **Step 3: 加 `_vol_diagnostics` hook 到 momentum_base**

在 `quantcore/backtest/strategies/momentum_base.py`：`MomentumStrategy` 加方法（`_risky_weights` 附近）：

```python
    def _vol_diagnostics(
        self, selected: list[str]
    ) -> tuple[dict[str, dict[str, float] | None] | None, dict[str, bool] | None]:
        """(garch_params, fell_back)；預設 None（無 GARCH，如 mom_only）。子類可覆寫。"""
        return None, None
```

在 `decide` 組 Diagnostics 前呼叫，並填入：

```python
        w_risky, sigma_hat = self._risky_weights(selected, view)
        garch_params, fell_back = self._vol_diagnostics(selected)
        absmom_all = absolute_momentum(view.prices, view.rates, cfg.signal.momentum_lookback)
        absmom = {t: bool(absmom_all.get(t, False)) for t in selected}
        weights, cash = route_absmom_to_cash(w_risky, absmom)
        target = {**weights, CASH: cash}
        return Decision(
            target_weights=target,
            diagnostics=Diagnostics(
                eligible=elig,
                selected=selected,
                momentum_scores=scores,
                absmom=absmom,
                sigma_hat=sigma_hat,
                w_risky=w_risky,
                vol_fell_back=fell_back,
                garch_params=garch_params,
            ),
        )
```

（即在既有 `Diagnostics(...)` 加 `vol_fell_back=fell_back, garch_params=garch_params` 兩參數，並在其上插入 `garch_params, fell_back = self._vol_diagnostics(selected)`。）

- [ ] **Step 4: 遷移 mom_ivol**

改 `quantcore/backtest/strategies/mom_ivol.py`：

```python
"""mom_ivol —— 動量 + inverse-vol（無波動目標）（規格 §6.3）。

存在理由：消融——有相對權重層但無總曝險控制（E=1）。σ̂ 由 GARCH（VolForecaster），
與 full 同估計器，使消融只差「曝險層」。無曝險檢查、不需 filter。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategies.momentum_base import MomentumStrategy
from quantcore.backtest.strategies.vol_target_base import ticker_returns
from quantcore.models.volatility.forecaster import VolForecaster
from quantcore.portfolio.weighting import inverse_vol


class MomentumInverseVol(MomentumStrategy):
    strategy_id = "mom_ivol"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self._forecaster = VolForecaster(
            cfg.risk.vol_model,
            cfg.risk.ewma_lambda,
            cfg.risk.forecast_horizon,
            cfg.risk.garch_window,
        )

    def _risky_weights(
        self, selected: list[str], view: PointInTimeView
    ) -> tuple[dict[str, float], dict[str, float]]:
        sigma_hat = {t: self._forecaster.refit(t, ticker_returns(view, t)) for t in selected}
        return inverse_vol(sigma_hat), sigma_hat

    def _vol_diagnostics(self, selected):
        return (
            {t: self._forecaster.last_params(t) for t in selected},
            {t: self._forecaster.last_fell_back(t) for t in selected},
        )
```

- [ ] **Step 5: 執行確認通過**

Run: `uv run pytest tests/test_backtest/test_mom_strategies.py -v`
Expected: 全 PASS（調整既有斷言後）。若既有測試用 default（rolling_std）跑 mom_ivol，改 override `vol_model="ewma"`。

- [ ] **Step 6: 全測試綠 + lint**

Run: `uv run pytest -q`（此時 default 仍 rolling_std；mom_ivol 測試已改 override ewma。注意：若有測試用 default 建 mom_ivol，會因 VolForecaster 不支援 rolling_std 而失敗——一併改為 override ewma）與 ruff。
Expected: 綠、乾淨。

- [ ] **Step 7: Commit**

```bash
git add quantcore/backtest/strategies/momentum_base.py quantcore/backtest/strategies/mom_ivol.py tests/test_backtest/test_mom_strategies.py
git commit -m "refactor(strategies): mom_ivol 遷移到 GARCH σ̂（VolForecaster）+ 診斷 hook（§6.3）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: 翻 `vol_model` 預設為 `garch_arch` + 修受影響測試

**Files:**
- Modify: `quantcore/config/default.yaml`
- Modify: 任何因 default 翻 garch_arch 而受影響的既有測試
- Test: `tests/test_config.py`（斷言預設值）

**設計要點：** 翻 default 後，凡用 default 建 `mom_ivol`/`full`/`voltarget_only` 的測試會走 GARCH。GARCH 需 ≥100 obs——短合成資料的測試改 override `vol_model="ewma"` 或用足夠長序列。`ablation`/`runner` 的既有測試若跑 mom_ivol 也需檢查。

- [ ] **Step 1: 寫斷言測試**

在 `tests/test_config.py` 加：

```python
def test_default_vol_model_is_garch_arch():
    cfg = load_config("quantcore/config/default.yaml")
    assert cfg.risk.vol_model == "garch_arch"
```

- [ ] **Step 2: 翻 default.yaml**

改 `quantcore/config/default.yaml`：`vol_model: rolling_std` → `vol_model: garch_arch`（更新註解為「GARCH(1,1)-t 正式路徑」）。

- [ ] **Step 3: 跑全套、定位受影響測試**

Run: `uv run pytest -q`
Expected: 可能有失敗——凡用 default 建 vol-consuming 策略（`mom_ivol`/`full`/`voltarget_only`）者。**已知嫌疑檔**：`tests/test_experiments/test_ablation.py`（消融跑 STRATEGIES over default config）、`tests/test_experiments/test_decisions_diagnostics.py`（若以 default 建 mom_ivol）、`tests/test_backtest/test_mom_strategies.py`（Task 10 多半已改）、以及任何以 `load_config("quantcore/config/default.yaml")` 或 `make_cfg(...)` 未 override `vol_model` 就建這三個策略之一的測試。逐一修：把該測試的 config override `risk={"vol_model": "ewma", ...}`（EWMA 便宜、決定性、短序列可跑），或改斷結構性關係而非 rolling_std 特定值。用 `grep -rn "mom_ivol\|MomentumInverseVol\|\"full\"\|voltarget" tests/` 找全部呼叫點。**不要**改 production 程式碼遷就測試；只調整測試的 vol_model override。列出所有改動的測試檔於 commit 訊息。

- [ ] **Step 4: 確認全綠**

Run: `uv run pytest -q` 與 `uv run ruff check quantcore tests` + `uv run ruff format --check quantcore tests`
Expected: 綠、乾淨。

- [ ] **Step 5: Commit**

```bash
git add quantcore/config/default.yaml tests/test_config.py <受影響測試檔>
git commit -m "feat(config): vol_model 預設翻 garch_arch（GARCH 轉正）+ 受影響測試改 ewma override

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: PROGRESS + AC 重定義紀錄

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: 記錄 4b-2 完成 + AC 重定義**

在 `PROGRESS.md` 的 Phase 4 區塊：
- 4b-2 子項打勾（`voltarget_only`/`full` 策略、engine 接線、`mom_ivol` 遷移）。
- **改寫 Phase 4 AC「`full` 已實現波動率落在 σ*±2%」** 為條件化定義（設計 §7）：`voltarget_only` 全期落 8-12%（乾淨測）；`full` 僅在 absmom 大致全過期間量（隔離波動目標層）。標注實際量測於 4c。
- 「變更紀錄」加一行，記：engine log-only decision（Decision.execute）、VolTargetStrategy 基底 + voltarget_only/full、mom_ivol 遷移 GARCH、Diagnostics 決策當下記 vol_fell_back/garch_params、config corr_window(252) + vol_model 翻 garch_arch。6 處規格偏離（見設計 §9）。邊界：4c 做 bootstrap + 七策略消融全表 + σ*±2% 實際量測。

- [ ] **Step 2: 全測試綠 + 格式檢查**

Run: `uv run pytest -q && uv run ruff format --check quantcore tests && uv run ruff check quantcore tests`
Expected: 綠、ruff 乾淨。

- [ ] **Step 3: Commit**

```bash
git add PROGRESS.md
git commit -m "docs(phase4b2): 策略+engine 接線完成 + σ*±2% AC 條件化重定義

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 完成後

4b-2 完成後，`feature/phase4-volatility` 上七策略齊備（bh_spy/ew_menu/sixty_forty/mom_only/voltarget_only/mom_ivol/full），GARCH 為預設 vol 來源，曝險機制與 band 落盤完整。

下一步為 **4c**（block bootstrap + 七策略消融全表 + `full` σ*±2% 條件式量測 + 子期間分析），另開 brainstorming → spec → plan。屆時 Phase 4 全部 AC 達成。
