# 曝險更新帶 log 模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 為曝險更新帶新增 log（相對）判定模式，作為 config 選項，並以換手率–追蹤誤差前沿消融驗證是否翻 default。

**Architecture:** `target_exposure`（唯一曝險出口，純函數）加 `band_mode` 分支；config schema 加 `exposure_band_mode` enum（預設 `absolute`，向後相容）+ log 模式強制 `exposure_min>0`；`compute_metrics` 補 `annualized_vol` 使前沿消融能零改動重用現有 `run_ablation`；新增薄驅動跑 absolute/log 兩趟掃描並判支配。

**Tech Stack:** Python、pydantic v2、pandas、numpy、pytest、uv、ruff format。

**規格來源:** [2026-08-13-exposure-band-log-mode-design.md](../specs/2026-08-13-exposure-band-log-mode-design.md)

---

## File Structure

| 檔案 | 責任 | 動作 |
|------|------|------|
| `quantcore/portfolio/exposure.py` | 曝險出口純函數，加 log 分支 | Modify |
| `tests/test_portfolio/test_exposure.py` | log 模式行為測試 | Modify |
| `quantcore/config/schema.py` | `exposure_band_mode` 欄位 + log 需 e_min>0 驗證 | Modify |
| `tests/test_config.py` | schema 新規則測試 | Modify |
| `quantcore/config/default.yaml`、`canonical_ewma.yaml`、`canonical_dcc.yaml` | 顯式標註 `exposure_band_mode: absolute` | Modify |
| `quantcore/backtest/strategies/vol_target_base.py` | `_exposure_decision` 傳 band_mode | Modify |
| `tests/test_backtest/test_vol_target_base.py` | 接線測試 | Modify |
| `quantcore/backtest/metrics.py` | `annualized_vol` + 併入 `compute_metrics` | Modify |
| `tests/test_backtest/test_metrics.py` | keys 集合更新 + 值測試 | Modify |
| `quantcore/experiments/exposure_band_frontier.py` | 前沿純核心 + CLI 驅動 | Create |
| `tests/test_experiments/test_exposure_band_frontier.py` | pareto/支配純函數測試 | Create |

---

## Task 1: `target_exposure` 加 log 模式（純函數）

**Files:**
- Modify: `quantcore/portfolio/exposure.py`
- Test: `tests/test_portfolio/test_exposure.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_portfolio/test_exposure.py` 末尾附加（檔頭已 `import pytest` 與 `from quantcore.portfolio.exposure import ExposureResult, target_exposure`；新增 `import math`）：

```python
import math


def test_log_band_blocks_small_relative_change():
    # σ̂_p=0.20 → clipped=0.5；e_current=0.55；|ln0.5−ln0.55|=0.0953 < band 0.15 → 擋
    r = target_exposure(0.20, 0.10, 0.10, 0.15, 0.55, band_mode="log")
    assert r.band_blocked is True
    assert r.exposure_applied == pytest.approx(0.55)
    assert r.exposure_raw == pytest.approx(0.5)


def test_log_band_allows_large_relative_change():
    # clipped=0.5；e_current=0.70；|ln0.5−ln0.70|=0.3365 > 0.15 → 套新值
    r = target_exposure(0.20, 0.10, 0.10, 0.15, 0.70, band_mode="log")
    assert r.band_blocked is False
    assert r.exposure_applied == pytest.approx(0.5)


def test_log_band_boundary_equal_is_blocked():
    # |ln(clipped)−ln(e_current)| 恰 == band → 擋（嚴格 >）
    # e_current=1.0、clipped=0.5 → |ln0.5|=0.6931；band=ln(2)=0.6931
    r = target_exposure(0.20, 0.10, 0.10, math.log(2), 1.0, band_mode="log")
    assert r.band_blocked is True
    assert r.exposure_applied == pytest.approx(1.0)


def test_log_band_uniform_across_sigma_levels():
    # 同一相對 σ̂_p 變動(+20%)在高/低 σ̂_p 兩處產生相同 |Δln E|=0.1823，
    # 故 band=0.15 兩處皆穿、band=0.20 兩處皆擋——容忍度與水準無關。
    # 低波動側：e_current=0.90（σ̂_p≈0.111）→ σ̂_p=0.1333 → clipped=0.75
    # 高波動側：e_current=0.30（σ̂_p≈0.333）→ σ̂_p=0.40   → clipped=0.25
    low_cross = target_exposure(0.10 / 0.75, 0.10, 0.10, 0.15, 0.90, band_mode="log")
    high_cross = target_exposure(0.10 / 0.25, 0.10, 0.10, 0.15, 0.30, band_mode="log")
    assert low_cross.band_blocked is False and high_cross.band_blocked is False
    low_block = target_exposure(0.10 / 0.75, 0.10, 0.10, 0.20, 0.90, band_mode="log")
    high_block = target_exposure(0.10 / 0.25, 0.10, 0.10, 0.20, 0.30, band_mode="log")
    assert low_block.band_blocked is True and high_block.band_blocked is True


def test_log_band_first_application_no_band():
    # e_current=None → 直接套用，不受帶約束
    r = target_exposure(0.20, 0.10, 0.10, 0.15, None, band_mode="log")
    assert r.band_blocked is False
    assert r.exposure_applied == pytest.approx(0.5)


def test_unknown_band_mode_raises():
    with pytest.raises(ValueError):
        target_exposure(0.20, 0.10, 0.10, 0.10, 0.5, band_mode="relative")


def test_absolute_mode_is_default_and_unchanged():
    # 不給 band_mode → absolute；|0.5−0.55|=0.05 ≤ 0.10 → 擋
    r = target_exposure(0.20, 0.10, 0.10, 0.10, 0.55)
    assert r.band_blocked is True
    assert r.exposure_applied == pytest.approx(0.55)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_portfolio/test_exposure.py -q`
Expected: FAIL（`target_exposure() got an unexpected keyword argument 'band_mode'`）

- [ ] **Step 3: 實作 log 分支**

改寫 `quantcore/portfolio/exposure.py` 的 `target_exposure`（`import math` 已在檔頭）：

```python
def target_exposure(
    sigma_p: float,
    sigma_star: float,
    e_min: float,
    band: float,
    e_current: float | None,
    band_mode: str = "absolute",
) -> ExposureResult:
    """E(t) = clip(σ*/σ̂_p, e_min, 1)，含更新帶。

    band_mode:
      - "absolute"：|clipped − e_current| > band 才調整（現行）。
      - "log"：     |ln(clipped) − ln(e_current)| > band 才調整（相對/對數空間，
                    容忍度與 σ̂_p 水準無關）。需 clipped>0 且 e_current>0。
    e_current is None（首次 / 選擇日）→ 直接套用，不受帶約束。
    """
    if not math.isfinite(sigma_p) or sigma_p <= 0.0:
        raise ValueError(f"σ̂_p={sigma_p} 非正或非有限，曝險無定義")
    if band_mode not in ("absolute", "log"):
        raise ValueError(f"未知 band_mode={band_mode!r}（可用：absolute | log）")
    raw = sigma_star / sigma_p
    clipped = min(max(raw, e_min), 1.0)
    if e_current is None:
        return ExposureResult(raw, clipped, band_blocked=False)
    if band_mode == "absolute":
        moved = abs(clipped - e_current) > band
    else:  # log
        if clipped <= 0.0 or e_current <= 0.0:
            raise ValueError(
                f"band_mode='log' 需 clipped>0 且 e_current>0，"
                f"收到 clipped={clipped}, e_current={e_current}（e_min 應 >0）"
            )
        moved = abs(math.log(clipped) - math.log(e_current)) > band
    if moved:
        return ExposureResult(raw, clipped, band_blocked=False)
    return ExposureResult(raw, e_current, band_blocked=True)
```

同步更新 docstring 首行的 `（規格 §1.6 Step 3、§1.7）` 註解保留不動。

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_portfolio/test_exposure.py -q`
Expected: PASS（含原有 absolute 測試全綠）

- [ ] **Step 5: commit**

```bash
git add quantcore/portfolio/exposure.py tests/test_portfolio/test_exposure.py
git commit -m "feat(portfolio): target_exposure 加 log(相對)帶模式"
```

---

## Task 2: config schema 加 `exposure_band_mode`

**Files:**
- Modify: `quantcore/config/schema.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_config.py` 末尾附加（檔頭已 `import pytest`、`from pydantic import ValidationError`、`from quantcore.config import QuantConfig`、`_valid_dict`）：

```python
def test_exposure_band_mode_defaults_absolute():
    raw = _valid_dict()
    raw["risk"].pop("exposure_band_mode", None)  # 未給 → 預設 absolute
    cfg = QuantConfig.model_validate(raw)
    assert cfg.risk.exposure_band_mode == "absolute"


def test_exposure_band_mode_log_valid_with_positive_e_min():
    raw = _valid_dict()
    raw["risk"]["exposure_band_mode"] = "log"
    raw["risk"]["exposure_min"] = 0.10
    cfg = QuantConfig.model_validate(raw)
    assert cfg.risk.exposure_band_mode == "log"


def test_log_band_mode_requires_positive_e_min():
    raw = _valid_dict()
    raw["risk"]["exposure_band_mode"] = "log"
    raw["risk"]["exposure_min"] = 0.0
    with pytest.raises(ValidationError):
        QuantConfig.model_validate(raw)


def test_unknown_band_mode_rejected():
    raw = _valid_dict()
    raw["risk"]["exposure_band_mode"] = "relative"
    with pytest.raises(ValidationError):
        QuantConfig.model_validate(raw)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_config.py -q -k band_mode`
Expected: FAIL（`log` 目前不被拒、或欄位不存在造成 extra="forbid" 報錯路徑不符）

- [ ] **Step 3: 實作 schema 欄位 + 驗證**

在 `quantcore/config/schema.py`：第 18 行下方加型別別名：

```python
ExposureBandMode = Literal["absolute", "log"]
```

在 `RiskConfig`（class 內，`exposure_band` 欄位下方）加欄位：

```python
    exposure_band_mode: ExposureBandMode = "absolute"  # §1.7 帶判定空間：absolute | log(相對)
```

在 `RiskConfig` 內（`_dcc_fixed_ab_stationary` 之後）加跨欄位驗證：

```python
    @model_validator(mode="after")
    def _log_band_requires_positive_e_min(self) -> RiskConfig:
        if self.exposure_band_mode == "log" and self.exposure_min <= 0.0:
            raise ValueError(
                "risk.exposure_band_mode='log' 需 exposure_min>0（避免 ln(0)＝−∞）"
            )
        return self
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS（含既有 config 測試）

- [ ] **Step 5: commit**

```bash
git add quantcore/config/schema.py tests/test_config.py
git commit -m "feat(config): risk.exposure_band_mode 欄位 + log 需 e_min>0"
```

---

## Task 3: config YAML 顯式標註 `exposure_band_mode`

**Files:**
- Modify: `quantcore/config/default.yaml`、`quantcore/config/canonical_ewma.yaml`、`quantcore/config/canonical_dcc.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_config.py` 的 `test_default_yaml_loads_and_validates` 內加一行斷言：

```python
    assert cfg.risk.exposure_band_mode == "absolute"
```

- [ ] **Step 2: 跑測試確認通過或失敗**

Run: `uv run pytest tests/test_config.py::test_default_yaml_loads_and_validates -q`
Expected: PASS（schema 預設即 absolute，yaml 尚未寫也會過；本步驟先確認斷言存在）

- [ ] **Step 3: 三份 YAML 加顯式行**

在 `default.yaml`、`canonical_ewma.yaml`、`canonical_dcc.yaml` 的 `risk:` 區塊，`exposure_min` 那行下方各加：

```yaml
  exposure_band_mode: absolute      # §1.7 帶判定空間：absolute | log(相對)。default 維持 absolute
```

- [ ] **Step 4: 驗證三份都載入且不改變既有語義（INV-6）**

Run: `uv run python -c "from quantcore.config import load_config; [print(p, load_config('quantcore/config/'+p).risk.exposure_band_mode) for p in ('default.yaml','canonical_ewma.yaml','canonical_dcc.yaml')]"`
Expected: 三行皆印出 `... absolute`

- [ ] **Step 5: commit**

```bash
git add quantcore/config/default.yaml quantcore/config/canonical_ewma.yaml quantcore/config/canonical_dcc.yaml tests/test_config.py
git commit -m "chore(config): 三份 config 顯式標註 exposure_band_mode: absolute"
```

---

## Task 4: 接線——`_exposure_decision` 傳 band_mode

**Files:**
- Modify: `quantcore/backtest/strategies/vol_target_base.py`（`_exposure_decision`，約 163-169 行的 `target_exposure(...)` 呼叫）
- Test: `tests/test_backtest/test_vol_target_base.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_backtest/test_vol_target_base.py` 加（檔頭補 `from quantcore.portfolio.exposure import target_exposure`）：

```python
def test_exposure_check_uses_log_band_mode():
    # 接線驗證：config 的 log 模式須流進 target_exposure。
    # 以決策落盤的 σ̂_p 與 e0 獨立重算 log 帶判定，應與策略內部一致。
    snap, dates = _snap()
    cfg = make_cfg(
        ["A", "B"],
        risk={"vol_model": "ewma", "garch_window": 100, "exposure_band_mode": "log"},
        signal={"top_k": 2},
    )
    strat = _FixedRisky(cfg, absmom={"A": True, "B": True})
    strat.decide(make_view(snap, dates[50]), DecisionEvent.SELECTION)
    e0 = strat._e_current
    dec = strat.decide(make_view(snap, dates[55]), DecisionEvent.EXPOSURE_CHECK)
    expected = target_exposure(
        dec.diagnostics.sigma_p,
        cfg.risk.vol_target_annual,
        cfg.risk.exposure_min,
        cfg.risk.exposure_band,
        e0,
        "log",
    )
    assert dec.diagnostics.band_blocked == expected.band_blocked
    assert dec.diagnostics.exposure_applied == pytest.approx(expected.exposure_applied)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_vol_target_base.py::test_exposure_check_uses_log_band_mode -q`
Expected: FAIL（策略仍走 absolute，band_blocked 判定與 log 期望不一致；若剛好一致則此步可能誤 PASS，Step 3 後仍須全綠）

- [ ] **Step 3: 實作接線**

在 `quantcore/backtest/strategies/vol_target_base.py` 的 `_exposure_decision`，`target_exposure(...)` 呼叫加最後一個引數：

```python
        exp = target_exposure(
            sigma_p,
            cfg.risk.vol_target_annual,
            cfg.risk.exposure_min,
            cfg.risk.exposure_band,
            e_current,
            cfg.risk.exposure_band_mode,
        )
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/test_vol_target_base.py -q`
Expected: PASS（含既有 absolute 流程測試）

- [ ] **Step 5: commit**

```bash
git add quantcore/backtest/strategies/vol_target_base.py tests/test_backtest/test_vol_target_base.py
git commit -m "feat(backtest): 曝險決策接入 exposure_band_mode"
```

---

## Task 5: `compute_metrics` 補 `annualized_vol`

**Files:**
- Modify: `quantcore/backtest/metrics.py`
- Test: `tests/test_backtest/test_metrics.py`

- [ ] **Step 1: 寫失敗測試**

改 `tests/test_backtest/test_metrics.py::test_compute_metrics_returns_all_keys` 的 keys 集合，加入 `"annualized_vol"`；並新增值測試：

```python
def test_annualized_vol_matches_std_times_sqrt252():
    from quantcore.backtest.metrics import annualized_vol

    n = 300
    rng = np.random.default_rng(0)
    r = rng.normal(0, 0.01, n)
    nav = pd.Series(np.cumprod(1 + r), index=pd.RangeIndex(n))
    daily = nav.pct_change().dropna().to_numpy()
    assert annualized_vol(nav) == pytest.approx(np.std(daily, ddof=1) * np.sqrt(252))
```

在 `test_compute_metrics_returns_all_keys` 的集合中加 `"annualized_vol",`。

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_metrics.py -q`
Expected: FAIL（`annualized_vol` 未定義；keys 集合不符）

- [ ] **Step 3: 實作**

在 `quantcore/backtest/metrics.py`（`annualized_turnover` 附近，確認檔頭已 `import numpy as np`、有 `_DAYS_PER_YEAR`）加函數：

```python
def annualized_vol(nav: pd.Series) -> float:
    """實現年化波動 = std(日報酬, ddof=1)·√252（§6.4；vol targeting 追蹤誤差用）。"""
    r = nav.pct_change().dropna().to_numpy()
    if len(r) < 2:
        return float("nan")
    return float(np.std(r, ddof=1) * np.sqrt(_DAYS_PER_YEAR))
```

在 `compute_metrics` 的回傳 dict 加一鍵（`annualized_turnover` 那行附近）：

```python
        "annualized_vol": annualized_vol(nav),
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/test_metrics.py -q`
Expected: PASS

- [ ] **Step 5: commit**

```bash
git add quantcore/backtest/metrics.py tests/test_backtest/test_metrics.py
git commit -m "feat(backtest): compute_metrics 加 annualized_vol(§6.4)"
```

---

## Task 6: 前沿純核心（pareto / 支配 / 併表）

**Files:**
- Create: `quantcore/experiments/exposure_band_frontier.py`
- Test: `tests/test_experiments/test_exposure_band_frontier.py`

- [ ] **Step 1: 寫失敗測試**

建 `tests/test_experiments/test_exposure_band_frontier.py`：

```python
"""換手率–追蹤誤差前沿純函數（純邏輯，不跑回測）。"""

from __future__ import annotations

import pandas as pd

from quantcore.experiments.exposure_band_frontier import (
    assemble_frontier,
    frontier_dominates,
    pareto_front,
)


def test_pareto_front_drops_dominated():
    pts = [(1.0, 0.05), (1.5, 0.06), (2.0, 0.04), (3.0, 0.03)]
    assert pareto_front(pts) == [(1.0, 0.05), (2.0, 0.04), (3.0, 0.03)]


def test_frontier_dominates_true_when_log_weakly_better_everywhere():
    log_pts = [(1.0, 0.03), (2.0, 0.02)]
    abs_pts = [(1.5, 0.05), (2.5, 0.04)]
    assert frontier_dominates(log_pts, abs_pts) is True


def test_frontier_dominates_false_when_abs_has_unreachable_point():
    log_pts = [(1.0, 0.03), (2.0, 0.02)]
    abs_pts = [(0.5, 0.01)]  # 更低換手且更低追蹤誤差，log 觸不到
    assert frontier_dominates(log_pts, abs_pts) is False


def test_assemble_frontier_parses_band_and_tracking_error():
    df = pd.DataFrame(
        [
            {"cell_label": "risk.exposure_band=0.08", "strategy_id": "full",
             "annualized_turnover": 2.0, "annualized_vol": 0.12, "sharpe": 0.9},
            {"cell_label": "baseline", "strategy_id": "full",
             "annualized_turnover": 9.9, "annualized_vol": 0.30, "sharpe": 0.1},
        ]
    )
    out = assemble_frontier(df, mode="absolute", sigma_star=0.10)
    assert list(out.columns) == ["mode", "band", "strategy_id", "turnover", "tracking_error", "sharpe"]
    # baseline 列被略過（非 risk.exposure_band= 網格格）
    assert len(out) == 1
    row = out.iloc[0]
    assert row["band"] == 0.08 and row["mode"] == "absolute"
    assert row["turnover"] == 2.0
    assert row["tracking_error"] == pytest.approx(0.02)  # |0.12 − 0.10|
```

（檔頭補 `import pytest`。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_experiments/test_exposure_band_frontier.py -q`
Expected: FAIL（模組不存在）

- [ ] **Step 3: 實作純核心**

建 `quantcore/experiments/exposure_band_frontier.py`：

```python
"""曝險帶 absolute vs log 的換手率–追蹤誤差前沿消融（規格 §1.7、設計文件 §7）。

純核心（pareto_front / frontier_dominates / assemble_frontier）可單測；
run_frontier 為薄 CLI 驅動，重用 experiments.ablation.run_ablation 跑兩趟掃描。
presentation 不涉入；此為 experiments 層，允許 import 引擎。
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

_EPS = 1e-12


def pareto_front(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """(turnover, tracking_error) 皆越小越好。回非被支配點，依 turnover 升序。"""
    front: list[tuple[float, float]] = []
    best_te = float("inf")
    for turn, te in sorted(set(points)):
        if te < best_te - _EPS:
            front.append((turn, te))
            best_te = te
    return front


def frontier_dominates(
    log_pts: list[tuple[float, float]], abs_pts: list[tuple[float, float]]
) -> bool:
    """log 是否弱支配 abs：每個 abs 點都有某 log 點 turnover≤ 且 tracking≤。"""
    return all(
        any(lt <= at + _EPS and le <= ae + _EPS for lt, le in log_pts)
        for at, ae in abs_pts
    )


def assemble_frontier(comparison: pd.DataFrame, mode: str, sigma_star: float) -> pd.DataFrame:
    """comparison.parquet（cell_label/strategy_id/annualized_turnover/annualized_vol/sharpe）
    → 前沿長表。只取 cell_label 形如 'risk.exposure_band=<v>' 的網格格（略過 baseline）。
    """
    rows = []
    for _, r in comparison.iterrows():
        label = str(r["cell_label"])
        if not label.startswith("risk.exposure_band="):
            continue
        band = float(label.split("=", 1)[1])
        rows.append(
            {
                "mode": mode,
                "band": band,
                "strategy_id": r["strategy_id"],
                "turnover": float(r["annualized_turnover"]),
                "tracking_error": abs(float(r["annualized_vol"]) - sigma_star),
                "sharpe": float(r["sharpe"]),
            }
        )
    return pd.DataFrame(rows, columns=["mode", "band", "strategy_id", "turnover", "tracking_error", "sharpe"])
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_experiments/test_exposure_band_frontier.py -q`
Expected: PASS

- [ ] **Step 5: commit**

```bash
git add quantcore/experiments/exposure_band_frontier.py tests/test_experiments/test_exposure_band_frontier.py
git commit -m "feat(experiments): 曝險帶前沿純核心(pareto/支配/併表)"
```

---

## Task 7: 前沿 CLI 驅動（兩趟消融 + 支配判定）

**Files:**
- Modify: `quantcore/experiments/exposure_band_frontier.py`（加 `run_frontier` + `_cli` + `__main__`）

> 說明：本任務為協調層，串接兩趟真實回測消融（分鐘級），不寫快速單測——邏輯已由 Task 6 覆蓋，此處以 smoke 執行驗證產出形狀。

- [ ] **Step 1: 實作 run_frontier + CLI**

在 `quantcore/experiments/exposure_band_frontier.py` 末尾（純函數之後）加：

```python
def run_frontier(
    config_path: str,
    out_root: str = "runs",
    strategies: tuple[str, ...] = ("voltarget_only", "full"),
    abs_bands: tuple[float, ...] = (0.06, 0.08, 0.10, 0.13, 0.16),
    log_bands: tuple[float, ...] = (0.10, 0.15, 0.20, 0.25),
) -> pd.DataFrame:
    """跑 absolute/log 兩趟帶寬掃描，回合併前沿表並印各策略支配判定。"""
    from quantcore.config import load_config
    from quantcore.data.snapshot import load_snapshot
    from quantcore.experiments.ablation import run_ablation

    cfg = load_config(config_path)
    snapshot = load_snapshot(cfg.snapshot)
    sids = list(strategies)

    def _pass(mode: str, bands: tuple[float, ...]) -> pd.DataFrame:
        risk = cfg.risk.model_copy(update={"exposure_band_mode": mode})
        base = cfg.model_copy(update={"risk": risk})
        run_dir = run_ablation(
            base_cfg=base,
            snapshot=snapshot,
            strategy_ids=sids,
            param_grid={"risk.exposure_band": list(bands)},
            out_root=out_root,
            label=f"frontier_{mode}",
        )
        table = pd.read_parquet(run_dir / "comparison.parquet")
        return assemble_frontier(table, mode, cfg.risk.vol_target_annual)

    front = pd.concat([_pass("absolute", abs_bands), _pass("log", log_bands)], ignore_index=True)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("=== 曝險帶前沿（換手率↓ / 追蹤誤差↓）===")
    print(front.sort_values(["strategy_id", "mode", "band"]).to_string(index=False))
    print("\n=== 支配判定（log 弱支配 absolute？）===")
    for sid in sids:
        sub = front[front["strategy_id"] == sid]
        log_f = pareto_front(list(zip(sub[sub["mode"] == "log"]["turnover"],
                                      sub[sub["mode"] == "log"]["tracking_error"])))
        abs_f = pareto_front(list(zip(sub[sub["mode"] == "absolute"]["turnover"],
                                      sub[sub["mode"] == "absolute"]["tracking_error"])))
        verdict = "支配" if frontier_dominates(log_f, abs_f) else "未支配"
        print(f"  {sid}: log {verdict} absolute")
    return front


def _cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m quantcore.experiments.exposure_band_frontier")
    p.add_argument("--config", default="quantcore/config/default.yaml")
    p.add_argument("--out-root", default="runs")
    args = p.parse_args(argv)
    run_frontier(args.config, args.out_root)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
```

- [ ] **Step 2: ruff format + import 排序檢查**

Run: `uv run ruff format quantcore/experiments/exposure_band_frontier.py && uv run ruff check quantcore/experiments/exposure_band_frontier.py`
Expected: 無錯（格式化後無 diff 報錯、無 lint 問題）

- [ ] **Step 3: smoke 執行（真實回測，分鐘級）**

Run: `uv run python -m quantcore.experiments.exposure_band_frontier --config quantcore/config/default.yaml`
Expected: 印出前沿表（`voltarget_only` 與 `full` 各 9 列：absolute 5 + log 4）與兩行支配判定；`runs/` 下產生 `*_frontier_absolute_ablation` 與 `*_frontier_log_ablation` 兩個目錄，各含 `comparison.parquet`。

- [ ] **Step 4: commit**

```bash
git add quantcore/experiments/exposure_band_frontier.py
git commit -m "feat(experiments): 曝險帶前沿 CLI 驅動(兩趟消融+支配判定)"
```

---

## Task 8: 全套測試 + 不變量回歸

**Files:** 無（驗證）

- [ ] **Step 1: 跑不變量與全測試**

Run: `uv run pytest tests/test_invariants/ -q && uv run pytest -q`
Expected: 全綠。重點確認 INV-5（會計）、INV-6（可重現）不因新增 config 欄位而破。

- [ ] **Step 2: 確認 absolute 路徑回測輸出未變（INV-6 手查）**

Run: `uv run pytest tests/test_invariants/test_reproducibility.py -q`
Expected: PASS（default 仍 absolute，三元組決定性不變）

- [ ] **Step 3: 若全綠，準備整合**

Run: `git log --oneline feature/exposure-band-log-mode ~8..HEAD`
Expected: 見 Task 1–7 的提交序列。後續由 finishing-a-development-branch 決定合併方式。

---

## 消融結果落地（實作完成後、非本計畫程式步驟）

依設計文件 §8 AC5：跑 `run_frontier`，**僅當 log 前沿在 `voltarget_only` 與 `full` 兩者上都支配 absolute**，才把 `default.yaml` 的 `exposure_band_mode` 改為 `log`（另起一次 commit + 消融證據落盤）。否則保留 absolute，log 留作已驗證 config 選項。此決策點交回使用者拍板。
