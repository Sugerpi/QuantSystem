# 顯著性檢定 · 巢狀階梯 + 分指標 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 讓 significance_report 對巢狀消融階梯（bh_spy→mom_only→mom_ivol→full）的相鄰步、分指標（Sharpe/Calmar/MaxDD）產出 CI + 置換 p-value，寫出「哪一層在哪個指標上顯著加分」的乾淨結論。

**Architecture:** 重用既有 `paired_metric_diff_ci` / `stationary_bootstrap_indices` / `permutation_test_paired`；新增 MaxDD 陣列版 metric、config 宣告階梯、`significance_report._ladder_analysis`。RNG 走 `cfg.seed`（INV-6）。

**Tech Stack:** Python、numpy、pandas、pytest、uv、ruff format。

**規格對照：** `docs/superpowers/specs/2026-08-21-significance-ladder-design.md`

---

## Task 1: MaxDD 陣列版 metric

**Files:**
- Modify: `quantcore/backtest/metrics.py`（緊接既有 `metric_calmar` 之後）
- Test: `tests/test_backtest/test_metrics.py`

- [ ] **Step 1: 寫失敗測試**（加到 `tests/test_backtest/test_metrics.py` 末尾）

```python
def test_metric_max_drawdown_matches_nav_maxdd():
    import numpy as np

    from quantcore.backtest.metrics import (
        _nav_from_returns,
        max_drawdown,
        metric_max_drawdown,
    )

    r = np.array([0.1, -0.5, 0.2])  # nav: 1→1.1→0.55→0.66，峰 1.1 谷 0.55
    got = metric_max_drawdown(r, np.zeros_like(r))
    assert abs(got - (-0.5)) < 1e-12  # 0.55/1.1 - 1 = -0.5
    assert got == max_drawdown(_nav_from_returns(r))  # 與 nav 版一致
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_metrics.py::test_metric_max_drawdown_matches_nav_maxdd -v`
Expected: FAIL（`metric_max_drawdown` 不存在）

- [ ] **Step 3: 實作**（在 `metrics.py` 的 `metric_calmar` 定義之後新增）

```python
def metric_max_drawdown(r: np.ndarray, rf: np.ndarray) -> float:
    """報酬陣列版 MaxDD（供 significance；rf 未用）。回負值或 0；越接近 0 越好。"""
    return max_drawdown(_nav_from_returns(r))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/test_metrics.py -v`
Expected: PASS（全部）

- [ ] **Step 5: ruff + Commit**

```bash
uv run ruff format quantcore tests && uv run ruff check quantcore tests
git add quantcore/backtest/metrics.py tests/test_backtest/test_metrics.py
git commit -m "feat(backtest): metric_max_drawdown 陣列版（供 significance 階梯）"
```
（訊息結尾保留 Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>）

---

## Task 2: config ablation_ladder

**Files:**
- Modify: `quantcore/config/schema.py`（`StatsConfig`）
- Modify: `quantcore/config/default.yaml`、`canonical_ewma.yaml`、`canonical_dcc.yaml`（各 `stats:` 區塊）
- Test: `tests/test_config.py`

- [ ] **Step 1: 寫失敗測試**（加到 `tests/test_config.py` 末尾）

```python
def test_stats_ablation_ladder_loads():
    from quantcore.config import load_config

    cfg = load_config("quantcore/config/default.yaml")
    assert cfg.stats.ablation_ladder == ["bh_spy", "mom_only", "mom_ivol", "full"]


def test_ablation_ladder_min_length():
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
            pbo_n_splits=16,
            mc_permutations=1000,
            ablation_ladder=["full"],  # 少於 2 → 應拒絕
        )
```

> 註：`StatsConfig(...)` 建構須帶齊所有必填欄位；實作前先讀 `schema.py` 現況（Task 1 系列已加的 significance/psr/pbo/mc 欄位都在），以實際欄位為準補齊建構引數。

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_config.py::test_stats_ablation_ladder_loads tests/test_config.py::test_ablation_ladder_min_length -v`
Expected: FAIL

- [ ] **Step 3: 改 schema**（`StatsConfig` 在 `mc_permutations` 之後新增欄位）

```python
    ablation_ladder: list[str] = Field(min_length=2)  # 巢狀階梯（simple→rich）
```

在 `StatsConfig` 既有 validator 之後新增元素非空驗證：

```python
    @model_validator(mode="after")
    def _ladder_nonempty(self) -> StatsConfig:
        if any(not s.strip() for s in self.ablation_ladder):
            raise ValueError("ablation_ladder 元素不可為空字串")
        return self
```

- [ ] **Step 4: 改三份 yaml**（各 `stats:` 區塊加入，縮排對齊）

```yaml
  ablation_ladder: [bh_spy, mom_only, mom_ivol, full]   # 巢狀階梯（simple→rich）
```

- [ ] **Step 5: 跑測試確認通過**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS（全部）

- [ ] **Step 6: ruff + Commit**

```bash
uv run ruff format quantcore tests && uv run ruff check quantcore tests
git add quantcore/config/schema.py quantcore/config/default.yaml quantcore/config/canonical_ewma.yaml quantcore/config/canonical_dcc.yaml tests/test_config.py
git commit -m "feat(config): StatsConfig 新增 ablation_ladder"
```
（訊息結尾保留 Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>）

---

## Task 3: significance_report 階梯分析

**Files:**
- Modify: `quantcore/experiments/significance_report.py`
- Test: `tests/test_experiments/test_significance_report.py`

- [ ] **Step 1: 寫失敗測試**（加到 `tests/test_experiments/test_significance_report.py` 末尾；沿用既有 `_make_ablation_run` 合成快照 fixture）

```python
def test_significance_ladder_section(tmp_path):
    cfg, snap, run_dir = _make_ablation_run(tmp_path)
    # 合成 run 只跑了 ["full", "mom_ivol"]，故階梯改用這兩者（simple→rich）以符合 run 策略集
    cfg2 = cfg.model_copy(
        update={"stats": cfg.stats.model_copy(update={"ablation_ladder": ["mom_ivol", "full"]})}
    )
    out = build_significance_report(cfg2, snap, run_dir)
    ladder = out["ladder"]
    assert isinstance(ladder, list) and len(ladder) == 3  # 1 步 × 3 指標
    metrics = {row["metric"] for row in ladder}
    assert metrics == {"sharpe", "calmar", "max_drawdown"}
    row = ladder[0]
    assert set(row) >= {
        "step", "simpler", "richer", "added_layer",
        "metric", "observed", "ci_lo", "ci_hi", "ci_excludes_zero", "p_value",
    }
    assert row["simpler"] == "mom_ivol" and row["richer"] == "full"


def test_significance_ladder_missing_strategy_raises(tmp_path):
    import pytest

    cfg, snap, run_dir = _make_ablation_run(tmp_path)
    cfg2 = cfg.model_copy(
        update={"stats": cfg.stats.model_copy(update={"ablation_ladder": ["bh_spy", "full"]})}
    )
    with pytest.raises(ValueError, match="ablation_ladder"):
        build_significance_report(cfg2, snap, run_dir)  # bh_spy 不在此 run
```

> 註：既有 `test_significance_reproducible` 會一併覆蓋新 `ladder` 區塊的 INV-6 位元可重現，不需另寫；但實作後務必確認該測試仍綠。

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_experiments/test_significance_report.py::test_significance_ladder_section -v`
Expected: FAIL（無 `ladder` 鍵）

- [ ] **Step 3: 實作**

在 `significance_report.py` 的 import 區更新既有 `from quantcore.backtest.metrics import ...`，補上 `metric_max_drawdown`、`paired_metric_diff_ci`、`stationary_bootstrap_indices`（這三者與既有 `metric_calmar`/`metric_sharpe` 同樣都定義在 `quantcore/backtest/metrics.py`，**不是** significance.py）：

```python
from quantcore.backtest.metrics import (
    metric_calmar,
    metric_max_drawdown,
    metric_sharpe,
    paired_metric_diff_ci,
    stationary_bootstrap_indices,
)
```

`from quantcore.backtest.significance import ...` 維持既有（psr / expected_max_sharpe / deflated_sharpe_ratio / pbo_cscv / permutation_test_paired），不變。

在模組層（`_daily_rf` 之後）新增常數與階梯函式：

```python
# 階梯相鄰步 → 該步新增的層（人可讀標籤；非可調參數）
_LAYER_LABELS = {
    ("bh_spy", "mom_only"): "橫斷面動量選股",
    ("mom_only", "mom_ivol"): "inverse-vol 定倉",
    ("mom_ivol", "full"): "組合波動目標",
}
_LADDER_METRICS = (
    ("sharpe", metric_sharpe),
    ("calmar", metric_calmar),
    ("max_drawdown", metric_max_drawdown),
)


def _ladder_analysis(cfg, snapshot, cell_ret, rng) -> list[dict]:
    """巢狀階梯相鄰步 × 分指標的配對 CI + 置換 p-value。

    來源同 full-vs-all 置換：baseline cell 的各策略日報酬（同 clock、等長）。
    MaxDD 為負值、越接近 0 越好；observed = metric(richer) − metric(simpler)，
    正 diff（MaxDD）= 回撤改善。
    """
    ladder = list(cfg.stats.ablation_ladder)
    base_ret = cell_ret[cell_ret["cell_label"] == "baseline"]
    available = set(base_ret["strategy_id"].unique())
    missing = [s for s in ladder if s not in available]
    if missing:
        raise ValueError(f"ablation_ladder 策略不在消融 run 中：{missing}（run 有：{sorted(available)}）")

    series: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for sid in ladder:
        sub = base_ret[base_ret["strategy_id"] == sid].sort_values("date")
        series[sid] = (sub["ret"].to_numpy(), _daily_rf(snapshot, sub["date"]))

    rows: list[dict] = []
    for step in range(len(ladder) - 1):
        simpler, richer = ladder[step], ladder[step + 1]
        ra, rf_a = series[richer]
        rb, _rf_b = series[simpler]
        idx = stationary_bootstrap_indices(
            len(ra), cfg.stats.bootstrap_mean_block, cfg.stats.bootstrap_reps, rng
        )
        label = _LAYER_LABELS.get((simpler, richer), f"{simpler}→{richer}")
        for mname, mfn in _LADDER_METRICS:
            ci = paired_metric_diff_ci(ra, rb, rf_a, mfn, idx, cfg.stats.bootstrap_alpha)
            perm = permutation_test_paired(
                ra, rb, rf_a, mfn, cfg.stats.mc_permutations, cfg.stats.bootstrap_mean_block, rng
            )
            rows.append(
                {
                    "step": step + 1,
                    "simpler": simpler,
                    "richer": richer,
                    "added_layer": label,
                    "metric": mname,
                    "observed": ci["point"],
                    "ci_lo": ci["lo"],
                    "ci_hi": ci["hi"],
                    "ci_excludes_zero": ci["excludes_zero"],
                    "p_value": perm["p_value"],
                }
            )
    return rows
```

在 `build_significance_report` 內，於既有 `perm` 區塊算完之後、組 `report` 之前，用**同一個 `rng`** 續跑階梯（順序寫死確保 INV-6）：

```python
    ladder = _ladder_analysis(cfg, snapshot, cell_ret, rng)
```

並在 `report` dict 加入頂層鍵：

```python
        "permutation": perm,
        "ladder": ladder,
    }
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_experiments/test_significance_report.py -v`
Expected: PASS（含既有 reproducible / schema / guard 測試不回歸）

- [ ] **Step 5: ruff + Commit**

```bash
uv run ruff format quantcore tests && uv run ruff check quantcore tests
git add quantcore/experiments/significance_report.py tests/test_experiments/test_significance_report.py
git commit -m "feat(experiments): significance_report 巢狀階梯分指標 CI+置換"
```
（訊息結尾保留 Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>）

---

## Task 4: 回歸關卡 + 真快照冒煙

**Files:** 無新增；驗證關卡。

- [ ] **Step 1: 不變量**

Run: `uv run pytest tests/test_invariants/ -q`
Expected: PASS

- [ ] **Step 2: 相關子集全跑**

Run: `uv run pytest tests/test_backtest/ tests/test_experiments/ tests/test_config.py -q`
Expected: PASS（無回歸）

- [ ] **Step 3: ruff 全樹**

Run: `uv run ruff format --check quantcore tests && uv run ruff check quantcore tests`
Expected: 乾淨

- [ ] **Step 4: 真快照冒煙（用已存在的 sig_smoke run，或重跑）**

Run: 對既有消融 run 目錄跑
`uv run python -m quantcore.experiments.significance_report --config quantcore/config/default.yaml --run-dir <消融 run 目錄>`
Expected: `significance.json` 含 `ladder` 區塊、3 步 × 3 指標 = 9 列（預設階梯，前提是該 run 跑了 bh_spy/mom_only/mom_ivol/full 四策略；若舊 run 未含，重跑一次含四策略的 ablation）。人工檢視每步每指標的 `ci_excludes_zero` 與 `p_value`，形成一句結論。

---

## 自我檢查結論

- **Spec 覆蓋**：§3 config→Task 2；§4 metric_max_drawdown→Task 1；§5 _ladder_analysis→Task 3；§6 測試分散於各 Task + Task 4。
- **型別一致**：`metric_max_drawdown(r, rf)` 簽章與 `metric_calmar` 一致；`paired_metric_diff_ci` 回 `{point,lo,hi,excludes_zero}`、`permutation_test_paired` 回 `{observed,p_value}`，欄位對應正確。
- **RNG 順序**：階梯續用既有 `rng`、順序寫死，既有 reproducible 測試覆蓋 INV-6。
- **import 正確性**：計畫已明確指出 `paired_metric_diff_ci` / `stationary_bootstrap_indices` 在 `metrics.py`（非 significance.py），避免 import 錯誤。
