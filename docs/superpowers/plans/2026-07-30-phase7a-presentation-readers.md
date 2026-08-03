# Phase 7a 計畫 2a — presentation readers 地基 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建 `presentation/readers.py`——純函數、TDD、CI 可跑的唯讀 artifact 載入層，把 `runs/`、`snapshots/` 的 parquet/JSON 解析成 tidy 結構，含 Decision Explorer 六層抽取（AC① 的自動化 golden），並以架構守護測試把「presentation 永不 import 引擎」（§2.2）變成紅綠燈。

**Architecture:** 薄頁面、胖 readers。所有 JSON 字串欄與檔案載入集中於 `readers.py`，9 頁只呼叫 readers + 畫圖（Plan 2b）。readers 只 import stdlib/pandas/pyarrow/yaml，**絕不** import `quantcore.{backtest,models,signals,portfolio,experiments,data,config}`——由 AST 架構守護測試強制。缺 `model_details/`、`trades.parquet` 的舊 run 回 `None`（「本次未儲存」），不崩潰。

**Tech Stack:** Python 3.12、pandas、pyarrow、pyyaml、pytest、uv、ruff。**本計畫不新增相依**——readers 只用 stdlib/pandas/yaml（均已為專案相依）。streamlit/plotly 是 Plan 2b（頁面）才需要，屆時再加（YAGNI）。

---

## 設計依據
- 設計文件：[`2026-07-29-phase7a-dashboard-design.md`](../specs/2026-07-29-phase7a-dashboard-design.md) §5.1（readers）、§2（Decision Explorer 六層）、§6（測試）。
- 前置：計畫 1（引擎落盤）已完成，本機 `runs/` 有 2 個 canonical run（ewma/dcc）。本計畫**不**建 Streamlit 頁面（Plan 2b）。

## 真實 artifact schema（ground truth，計畫 1 落盤實測）

| 檔案 | 欄位 |
|---|---|
| `decisions.parquet` | `decision_date, execution_date, strategy_id, event, target_weights*, eligible*, selected*, momentum_scores*, absmom*, sigma_hat*, w_risky*, sigma_p, exposure_raw, exposure_applied, band_blocked, vol_fell_back*, garch_params*, corr_fell_back`（`*`=JSON 字串欄，`sort_keys` 序列化） |
| `trades.parquet` | `execution_date, strategy_id, ticker, drifted_weight, target_weight, delta_weight, side, notional, fill_price, shares, cost` |
| `model_details/correlation.parquet` | `decision_date, strategy_id, ticker_i, ticker_j, corr` |
| `model_details/residuals.parquet` | `strategy_id, ticker, date, std_resid` |
| `nav.parquet` | `date, strategy_id, nav, turnover, cost` |
| `weights.parquet` | `date, strategy_id, ticker, weight` |
| `metrics.json` | `{strategy_id: {annualized_return, annualized_turnover, average_exposure, calmar, cost_drag_bps_per_year, max_drawdown, n_days, sharpe, sortino, subperiods}}` |
| `manifest.json` | `{identity{config_hash,snapshot_id,git_commit,quantcore_version}, content_hashes{...}, created_at}` |
| `config.yaml` | 完整 QuantConfig dump |
| 快照 `snapshots/<id>/prices.parquet` | `date, ticker, close, adj_close`（讀 adj_close 面板） |
| 快照 `snapshots/<id>/metadata.json` | overrides 裁決清單、跨源差異（頁 7） |
| 快照 `snapshots/<id>/MANIFEST.json` | 快照 identity/hash |

> **JSON 欄解析慣例**：`target_weights/eligible/selected/momentum_scores/absmom/sigma_hat/w_risky/vol_fell_back/garch_params` 皆 `json.loads`；`None` 字面（Phase 2/3 空欄）→ Python `None`。`band_blocked/corr_fell_back` 為 nullable boolean（pandas `boolean` dtype），讀回為 `True/False/<NA>`。

## 檔案結構

| 檔案 | 職責 | 動作 |
|---|---|---|
| `quantcore/presentation/__init__.py` | 既存空 package | 不動 |
| `quantcore/presentation/readers.py` | 唯讀 artifact 載入 + JSON 解析 + Decision Explorer 六層 + list_runs + 快照讀取 | 新增 |
| `tests/test_presentation/__init__.py` | 測試 package | 新增 |
| `tests/test_presentation/conftest.py` | 合成 run fixture（run_experiment on 合成快照，決定性、CI 可跑） | 新增 |
| `tests/test_presentation/test_readers.py` | run-level 載入 + JSON 解析 + 缺檔優雅 | 新增 |
| `tests/test_presentation/test_decision_explorer.py` | 六層抽取 golden（AC① 自動化） | 新增 |
| `tests/test_presentation/test_snapshot_readers.py` | 快照 prices/metadata 讀取 | 新增 |
| `tests/test_presentation/test_architecture.py` | AST 守護：presentation 不 import 引擎 | 新增 |

## 設計決定
- **readers 回 tidy pandas，不自訂重型型別**：Decision Explorer 六層回一個 `dataclass`（`DecisionLayers`），其餘回 `pd.DataFrame`/`dict`/`None`。
- **缺檔 = `None`**：`trades.parquet`、`model_details/*` 缺時對應 loader 回 `None`（§0「本次未儲存」）。核心檔（nav/weights/decisions/metrics/manifest）缺則讓 `FileNotFoundError` 自然拋（run 目錄不完整是真錯）。
- **readers import 白名單**：`json/pathlib/dataclasses/functools`（stdlib）、`pandas`、`yaml`。**禁** `quantcore.*` 引擎模組。架構測試以 AST 掃 import 節點強制。
- **AC① golden**：六層抽取對合成 run 的某決策，逐層與「獨立 `pd.read_parquet`+`json.loads` 解出的原始值」比對——鎖住抽取不錯映/不腐蝕（人工手查在 Plan 2b 對真實資料做）。

---

## Task 1: presentation 測試骨架 + 架構守護測試 + readers stub

**Files:**
- Create: `tests/test_presentation/__init__.py`, `tests/test_presentation/test_architecture.py`
- Create (stub): `quantcore/presentation/readers.py`（先放 module docstring + import 供架構測試掃）

> 本計畫不新增相依（readers 只用 pandas/yaml，均已存在）。streamlit/plotly 延到 Plan 2b。

- [ ] **Step 1: 建 readers stub。** 建 `quantcore/presentation/readers.py`：
```python
"""唯讀 artifact 載入層（§11.1 行程邊界；§5.1）。

presentation 永不 import 引擎：只讀 runs/、snapshots/ 的 parquet/JSON。
由 tests/test_presentation/test_architecture.py 的 AST 守護強制此邊界。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

__all__: list[str] = []
```

- [ ] **Step 2: 寫架構守護測試（先驗證它會抓違規）。** 建 `tests/test_presentation/__init__.py`（空檔）與 `tests/test_presentation/test_architecture.py`：
```python
"""架構守護：presentation 永不 import 引擎模組（§2.2 行程邊界紅綠燈化）。"""

import ast
from pathlib import Path

_PRESENTATION = Path(__file__).resolve().parents[2] / "quantcore" / "presentation"
_FORBIDDEN_PREFIXES = (
    "quantcore.backtest",
    "quantcore.models",
    "quantcore.signals",
    "quantcore.portfolio",
    "quantcore.experiments",
    "quantcore.data",
    "quantcore.config",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def _all_py() -> list[Path]:
    return [p for p in _PRESENTATION.rglob("*.py")]


def test_presentation_never_imports_engine():
    offenders = {}
    for path in _all_py():
        bad = {
            m
            for m in _imported_modules(path)
            if any(m == pre or m.startswith(pre + ".") for pre in _FORBIDDEN_PREFIXES)
        }
        if bad:
            offenders[str(path.relative_to(_PRESENTATION))] = sorted(bad)
    assert not offenders, f"presentation 違規 import 引擎：{offenders}"


def test_guard_has_teeth():
    """對一段含違規 import 的合成程式碼，守護邏輯必須抓到（否則守護是空殼）。"""
    import ast as _ast

    src = "from quantcore.backtest.engine import run_strategy\n"
    mods = {n.module for n in _ast.walk(_ast.parse(src)) if isinstance(n, _ast.ImportFrom)}
    assert any(m.startswith("quantcore.backtest") for m in mods)
```

- [ ] **Step 3: 跑測試。**
  Run: `uv run pytest tests/test_presentation/test_architecture.py -v`
  Expected: PASS（stub readers 只 import stdlib/pandas/yaml，無違規；`test_guard_has_teeth` 證守護有牙齒）。

- [ ] **Step 4: Commit。**
```bash
git add quantcore/presentation/readers.py tests/test_presentation/__init__.py tests/test_presentation/test_architecture.py
git commit -m "feat(phase7a): readers stub + 架構守護測試（§2.2 presentation 不 import 引擎，紅綠燈化）"
```

---

## Task 2: run-level 載入器（nav/weights/trades/metrics/manifest/config）

**Files:**
- Modify: `quantcore/presentation/readers.py`
- Create: `tests/test_presentation/conftest.py`, `tests/test_presentation/test_readers.py`

- [ ] **Step 1: 建合成 run fixture。** 建 `tests/test_presentation/conftest.py`（用 run_experiment 產真實結構的 run，決定性、CI 可跑、不需真實快照）：
```python
"""合成 run fixture：以 run_experiment 在合成快照上產出真實結構的 run 目錄（CI 可跑）。

注意：這是唯一「間接經由 experiments 產生測試資料」之處，屬測試 setup、非 presentation 執行期
import；presentation 執行期仍只讀檔案（架構守護測試覆蓋 quantcore/presentation/ 原始碼）。
"""

import numpy as np
import pandas as pd
import pytest

from quantcore.config import load_config
from quantcore.experiments.runner import run_experiment
from tests.fixtures.synthetic import make_dates, make_snapshot


@pytest.fixture(scope="session")
def run_dir(tmp_path_factory):
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["SPY", "QQQ", "IWM"]
    cfg.universe.min_history_days = 5
    cfg.signal.top_k = 2
    cfg.signal.momentum_lookback = 5
    cfg.signal.momentum_skip = 1
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    cfg.risk.vol_model = "ewma"
    cfg.risk.corr_model = "ewma"
    dates = make_dates(80)
    rng = np.random.default_rng(3)
    snap = make_snapshot(
        {
            "SPY": list(100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, 80))),
            "QQQ": list(200.0 * np.cumprod(1 + rng.normal(0.0005, 0.012, 80))),
            "IWM": list(150.0 * np.cumprod(1 + rng.normal(0.0005, 0.013, 80))),
        },
        dates,
    )
    out = tmp_path_factory.mktemp("runs")
    return run_experiment(
        cfg=cfg,
        snapshot=snap,
        out_root=out,
        label="fix",
        strategy_ids=["bh_spy", "full"],
        now=pd.Timestamp("2026-07-30T10:00:00"),
    )
```

- [ ] **Step 2: 寫失敗測試。** 建 `tests/test_presentation/test_readers.py`：
```python
import pandas as pd

from quantcore.presentation import readers


def test_load_nav_weights(run_dir):
    nav = readers.load_nav(run_dir)
    assert {"date", "strategy_id", "nav", "turnover", "cost"} <= set(nav.columns)
    w = readers.load_weights(run_dir)
    assert {"date", "strategy_id", "ticker", "weight"} <= set(w.columns)


def test_load_trades_present(run_dir):
    tr = readers.load_trades(run_dir)
    assert tr is not None
    assert {"execution_date", "strategy_id", "ticker", "delta_weight", "cost"} <= set(tr.columns)


def test_load_trades_absent_returns_none(tmp_path):
    (tmp_path / "nav.parquet").write_bytes(b"")  # 任意檔，確保目錄存在
    assert readers.load_trades(tmp_path) is None


def test_load_metrics_and_manifest(run_dir):
    m = readers.load_metrics(run_dir)
    assert "full" in m and "sharpe" in m["full"]
    mf = readers.load_manifest(run_dir)
    assert set(mf) == {"identity", "content_hashes", "created_at"}


def test_load_config(run_dir):
    c = readers.load_run_config(run_dir)
    assert c["risk"]["corr_model"] == "ewma"
```

- [ ] **Step 3: 跑測試確認失敗。**
  Run: `uv run pytest tests/test_presentation/test_readers.py -v`
  Expected: FAIL（`AttributeError: module ... has no attribute 'load_nav'`）

- [ ] **Step 4: 實作。** 在 `readers.py` 加（並把函數名加入 `__all__`）：
```python
def load_nav(run_dir: str | Path) -> pd.DataFrame:
    """nav.parquet（date, strategy_id, nav, turnover, cost）。"""
    return pd.read_parquet(Path(run_dir) / "nav.parquet")


def load_weights(run_dir: str | Path) -> pd.DataFrame:
    """weights.parquet（date, strategy_id, ticker, weight）。"""
    return pd.read_parquet(Path(run_dir) / "weights.parquet")


def load_trades(run_dir: str | Path) -> pd.DataFrame | None:
    """trades.parquet（缺 → None，舊 run「本次未儲存」）。"""
    p = Path(run_dir) / "trades.parquet"
    return pd.read_parquet(p) if p.exists() else None


def load_metrics(run_dir: str | Path) -> dict:
    """metrics.json（{strategy_id: {...}}）。"""
    return json.loads((Path(run_dir) / "metrics.json").read_text(encoding="utf-8"))


def load_manifest(run_dir: str | Path) -> dict:
    """manifest.json（identity/content_hashes/created_at）。"""
    return json.loads((Path(run_dir) / "manifest.json").read_text(encoding="utf-8"))


def load_run_config(run_dir: str | Path) -> dict:
    """該 run 的 config.yaml（dict）。"""
    return yaml.safe_load((Path(run_dir) / "config.yaml").read_text(encoding="utf-8"))
```
更新 `__all__` 加這 6 個名稱。

- [ ] **Step 5: 跑測試確認通過。**
  Run: `uv run pytest tests/test_presentation/test_readers.py -v`
  Expected: PASS

- [ ] **Step 6: Commit。**
```bash
git add quantcore/presentation/readers.py tests/test_presentation/conftest.py tests/test_presentation/test_readers.py
git commit -m "feat(phase7a): readers run-level 載入器（nav/weights/trades/metrics/manifest/config）"
```

---

## Task 3: decisions 載入 + JSON 欄解析

**Files:**
- Modify: `quantcore/presentation/readers.py`
- Modify: `tests/test_presentation/test_readers.py`

- [ ] **Step 1: 寫失敗測試。** 追加到 `test_readers.py`：
```python
def test_load_decisions_parses_json_columns(run_dir):
    dec = readers.load_decisions(run_dir)
    # full 策略某決策列
    full = dec[dec["strategy_id"] == "full"].iloc[0]
    assert isinstance(full["target_weights"], dict)
    assert isinstance(full["eligible"], list)
    assert isinstance(full["selected"], list)
    # None 字面欄（如 bh_spy 的 momentum_scores）→ Python None
    bh = dec[dec["strategy_id"] == "bh_spy"].iloc[0]
    assert bh["momentum_scores"] is None
    # nullable boolean 保持
    assert dec["band_blocked"].dtype.name == "boolean"
    assert "corr_fell_back" in dec.columns
```

- [ ] **Step 2: 跑測試確認失敗。**
  Run: `uv run pytest tests/test_presentation/test_readers.py::test_load_decisions_parses_json_columns -v`
  Expected: FAIL（無 `load_decisions`）

- [ ] **Step 3: 實作。** 在 `readers.py` 加：
```python
_JSON_COLS = (
    "target_weights",
    "eligible",
    "selected",
    "momentum_scores",
    "absmom",
    "sigma_hat",
    "w_risky",
    "vol_fell_back",
    "garch_params",
)


def _parse_json_cell(v):
    """JSON 字串 → Python 物件；None/NA → None（Phase 2/3 空欄慣例）。"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return json.loads(v)


def load_decisions(run_dir: str | Path) -> pd.DataFrame:
    """decisions.parquet，JSON 字串欄就地解析為 Python 物件（dict/list/None）。

    band_blocked/corr_fell_back 維持 nullable boolean。回傳供 Decision Explorer 與頁面消費。
    """
    dec = pd.read_parquet(Path(run_dir) / "decisions.parquet")
    for c in _JSON_COLS:
        if c in dec.columns:
            dec[c] = dec[c].map(_parse_json_cell)
    return dec
```
`__all__` 加 `load_decisions`。

- [ ] **Step 4: 跑測試確認通過。**
  Run: `uv run pytest tests/test_presentation/test_readers.py -v`
  Expected: PASS

- [ ] **Step 5: Commit。**
```bash
git add quantcore/presentation/readers.py tests/test_presentation/test_readers.py
git commit -m "feat(phase7a): readers.load_decisions + JSON 欄解析"
```

---

## Task 4: Decision Explorer 六層抽取（AC① 自動化 golden）

**Files:**
- Modify: `quantcore/presentation/readers.py`
- Create: `tests/test_presentation/test_decision_explorer.py`

- [ ] **Step 1: 寫失敗測試（golden）。** 建 `tests/test_presentation/test_decision_explorer.py`：
```python
"""Decision Explorer 六層抽取 = AC① 自動化：抽取須逐層對上獨立解析的原始 decisions 列。"""

import json

import pandas as pd

from quantcore.presentation import readers


def _raw_row(run_dir, strategy_id, decision_date):
    dec = pd.read_parquet(run_dir / "decisions.parquet")
    m = (dec["strategy_id"] == strategy_id) & (dec["decision_date"] == decision_date)
    return dec[m].iloc[0]


def test_six_layers_match_raw_decisions(run_dir):
    dec = readers.load_decisions(run_dir)
    full = dec[(dec["strategy_id"] == "full") & (dec["selected"].map(bool))].iloc[0]
    sid, ddate = full["strategy_id"], full["decision_date"]

    layers = readers.decision_layers(run_dir, sid, ddate)
    raw = _raw_row(run_dir, sid, ddate)

    # (a) eligible  (b) momentum_scores + selected  (c) absmom
    assert layers.eligible == json.loads(raw["eligible"])
    assert layers.momentum_scores == json.loads(raw["momentum_scores"])
    assert layers.selected == json.loads(raw["selected"])
    assert layers.absmom == json.loads(raw["absmom"])
    # (d) sigma_hat（年化純量 dict）
    assert layers.sigma_hat == json.loads(raw["sigma_hat"])
    # (e) 曝險公式各項
    assert layers.w_risky == json.loads(raw["w_risky"])
    assert layers.sigma_p == raw["sigma_p"]
    assert layers.exposure_raw == raw["exposure_raw"]
    assert layers.exposure_applied == raw["exposure_applied"]
    assert bool(layers.band_blocked) == bool(raw["band_blocked"])
    # (f) 目標權重（含 CASH）
    assert layers.target_weights == json.loads(raw["target_weights"])


def test_decision_layers_missing_returns_none(run_dir):
    assert readers.decision_layers(run_dir, "full", pd.Timestamp("1990-01-01")) is None
```

- [ ] **Step 2: 跑測試確認失敗。**
  Run: `uv run pytest tests/test_presentation/test_decision_explorer.py -v`
  Expected: FAIL（無 `decision_layers`）

- [ ] **Step 3: 實作。** 在 `readers.py` 加 dataclass + 抽取（頂部 import 區補 `from dataclasses import dataclass`）：
```python
@dataclass(frozen=True)
class DecisionLayers:
    """Decision Explorer 六層（§11.2 頁 2；§2 對照表）。純資料，供頁面渲染。"""

    strategy_id: str
    decision_date: pd.Timestamp
    execution_date: pd.Timestamp | None
    event: str
    eligible: list[str]  # (a)
    momentum_scores: dict[str, float] | None  # (b)
    selected: list[str]  # (b) 前 K
    absmom: dict[str, bool] | None  # (c)
    sigma_hat: dict[str, float] | None  # (d) 年化純量
    w_risky: dict[str, float] | None  # (e)
    sigma_p: float | None  # (e)
    exposure_raw: float | None  # (e)
    exposure_applied: float | None  # (e)
    band_blocked: bool | None  # (e)
    target_weights: dict[str, float]  # (f) 含 CASH


def decision_layers(
    run_dir: str | Path, strategy_id: str, decision_date
) -> DecisionLayers | None:
    """抽取某策略某決策日的六層。查無回 None。

    這是 AC① 的自動化出口：頁面渲染此結構，人工手查（Plan 2b）比對 decisions.parquet。
    """
    dec = load_decisions(run_dir)
    ddate = pd.Timestamp(decision_date)
    m = (dec["strategy_id"] == strategy_id) & (dec["decision_date"] == ddate)
    if not m.any():
        return None
    r = dec[m].iloc[0]

    def f(v):
        return None if pd.isna(v) else float(v)

    def b(v):
        return None if pd.isna(v) else bool(v)

    return DecisionLayers(
        strategy_id=strategy_id,
        decision_date=ddate,
        execution_date=None if pd.isna(r["execution_date"]) else r["execution_date"],
        event=r["event"],
        eligible=r["eligible"],
        momentum_scores=r["momentum_scores"],
        selected=r["selected"],
        absmom=r["absmom"],
        sigma_hat=r["sigma_hat"],
        w_risky=r["w_risky"],
        sigma_p=f(r["sigma_p"]),
        exposure_raw=f(r["exposure_raw"]),
        exposure_applied=f(r["exposure_applied"]),
        band_blocked=b(r["band_blocked"]),
        target_weights=r["target_weights"],
    )
```
`__all__` 加 `DecisionLayers`、`decision_layers`。

- [ ] **Step 4: 跑測試確認通過。**
  Run: `uv run pytest tests/test_presentation/test_decision_explorer.py -v`
  Expected: PASS

- [ ] **Step 5: Commit。**
```bash
git add quantcore/presentation/readers.py tests/test_presentation/test_decision_explorer.py
git commit -m "feat(phase7a): Decision Explorer 六層抽取（AC① 自動化 golden）"
```

---

## Task 5: correlation + residuals 載入（缺檔優雅）

**Files:**
- Modify: `quantcore/presentation/readers.py`
- Modify: `tests/test_presentation/test_readers.py`

- [ ] **Step 1: 寫失敗測試。** 追加到 `test_readers.py`：
```python
def test_load_correlation_and_residuals(run_dir):
    corr = readers.load_correlation(run_dir)
    assert corr is not None
    assert {"decision_date", "strategy_id", "ticker_i", "ticker_j", "corr"} <= set(corr.columns)
    assert set(corr["strategy_id"].unique()) <= {"full", "full_erc"}
    resid = readers.load_residuals(run_dir)
    assert resid is not None
    assert {"strategy_id", "ticker", "date", "std_resid"} <= set(resid.columns)


def test_model_details_absent_returns_none(tmp_path):
    assert readers.load_correlation(tmp_path) is None
    assert readers.load_residuals(tmp_path) is None


def test_correlation_matrix_at_reshapes_long_to_square(run_dir):
    corr = readers.load_correlation(run_dir)
    d0 = corr["decision_date"].iloc[0]
    mat = readers.correlation_matrix_at(corr, "full", d0)
    assert mat.index.tolist() == mat.columns.tolist()  # 方陣、對稱標籤
    assert (mat.values.diagonal() == 1.0).all() or abs(mat.values.diagonal() - 1.0).max() < 1e-9
```

- [ ] **Step 2: 跑測試確認失敗。**
  Run: `uv run pytest tests/test_presentation/test_readers.py -k "correlation or residual or model_details" -v`
  Expected: FAIL（無 `load_correlation`）

- [ ] **Step 3: 實作。** 在 `readers.py` 加：
```python
def load_correlation(run_dir: str | Path) -> pd.DataFrame | None:
    """model_details/correlation.parquet（長格式）。缺 → None（本次未儲存）。"""
    p = Path(run_dir) / "model_details" / "correlation.parquet"
    return pd.read_parquet(p) if p.exists() else None


def load_residuals(run_dir: str | Path) -> pd.DataFrame | None:
    """model_details/residuals.parquet。缺 → None。"""
    p = Path(run_dir) / "model_details" / "residuals.parquet"
    return pd.read_parquet(p) if p.exists() else None


def correlation_matrix_at(corr: pd.DataFrame, strategy_id: str, decision_date) -> pd.DataFrame:
    """長格式 → 某策略某決策日的方陣相關矩陣（頁 4 熱圖）。"""
    ddate = pd.Timestamp(decision_date)
    sub = corr[(corr["strategy_id"] == strategy_id) & (corr["decision_date"] == ddate)]
    return sub.pivot(index="ticker_i", columns="ticker_j", values="corr")
```
`__all__` 加三個名稱。

- [ ] **Step 4: 跑測試確認通過。**
  Run: `uv run pytest tests/test_presentation/test_readers.py -v`
  Expected: PASS

- [ ] **Step 5: Commit。**
```bash
git add quantcore/presentation/readers.py tests/test_presentation/test_readers.py
git commit -m "feat(phase7a): readers correlation/residuals 載入 + 相關矩陣重塑（缺檔優雅）"
```

---

## Task 6: 快照讀取器（prices 面板 / metadata / MANIFEST）

**Files:**
- Modify: `quantcore/presentation/readers.py`
- Create: `tests/test_presentation/test_snapshot_readers.py`

- [ ] **Step 1: 寫失敗測試。** 建 `tests/test_presentation/test_snapshot_readers.py`（用合成快照落到暫存目錄，避免依賴真實快照，CI 可跑）：
```python
"""快照讀取器（頁 7 資料品質、頁 9 價格）。以合成快照結構測試，CI 可跑。"""

import json

import numpy as np
import pandas as pd

from quantcore.presentation import readers
from tests.fixtures.synthetic import make_dates, make_snapshot


def _write_snapshot(root, sid="synthetic_01"):
    d = root / sid
    d.mkdir(parents=True)
    dates = make_dates(30)
    rng = np.random.default_rng(0)
    snap = make_snapshot(
        {"SPY": list(100.0 * np.cumprod(1 + rng.normal(0, 0.01, 30)))}, dates
    )
    snap["prices"].to_parquet(d / "prices.parquet", index=False)
    (d / "metadata.json").write_text(json.dumps({"overrides": []}), encoding="utf-8")
    (d / "MANIFEST.json").write_text(json.dumps({"snapshot_id": sid}), encoding="utf-8")
    return d


def test_load_adj_close_panel(tmp_path):
    d = _write_snapshot(tmp_path)
    panel = readers.load_adj_close_panel(d)
    assert "SPY" in panel.columns
    assert panel.index.name == "date"
    assert panel["SPY"].notna().all()


def test_load_snapshot_metadata_and_manifest(tmp_path):
    d = _write_snapshot(tmp_path)
    meta = readers.load_snapshot_metadata(d)
    assert "overrides" in meta
    man = readers.load_snapshot_manifest(d)
    assert man["snapshot_id"] == "synthetic_01"
```

- [ ] **Step 2: 跑測試確認失敗。**
  Run: `uv run pytest tests/test_presentation/test_snapshot_readers.py -v`
  Expected: FAIL（無 `load_adj_close_panel`）

- [ ] **Step 3: 實作。** 在 `readers.py` 加：
```python
def load_adj_close_panel(snapshot_dir: str | Path) -> pd.DataFrame:
    """快照 prices.parquet → date×ticker 的 adj_close 面板（頁 9 價格折線）。"""
    prices = pd.read_parquet(Path(snapshot_dir) / "prices.parquet")
    panel = prices.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    panel.index.name = "date"
    return panel


def load_snapshot_metadata(snapshot_dir: str | Path) -> dict:
    """快照 metadata.json（overrides 裁決、跨源差異；頁 7）。"""
    return json.loads((Path(snapshot_dir) / "metadata.json").read_text(encoding="utf-8"))


def load_snapshot_manifest(snapshot_dir: str | Path) -> dict:
    """快照 MANIFEST.json（頁 7）。"""
    return json.loads((Path(snapshot_dir) / "MANIFEST.json").read_text(encoding="utf-8"))
```
`__all__` 加三個名稱。

- [ ] **Step 4: 跑測試確認通過。**
  Run: `uv run pytest tests/test_presentation/test_snapshot_readers.py -v`
  Expected: PASS

- [ ] **Step 5: Commit。**
```bash
git add quantcore/presentation/readers.py tests/test_presentation/test_snapshot_readers.py
git commit -m "feat(phase7a): readers 快照 prices 面板 / metadata / MANIFEST"
```

---

## Task 7: run 探索（list_runs，供全域控制列的 run 選擇器）

**Files:**
- Modify: `quantcore/presentation/readers.py`
- Modify: `tests/test_presentation/test_readers.py`

- [ ] **Step 1: 寫失敗測試。** 追加到 `test_readers.py`：
```python
def test_list_runs_discovers_and_reads_identity(run_dir):
    runs_root = run_dir.parent
    runs = readers.list_runs(runs_root)
    names = [r["name"] for r in runs]
    assert run_dir.name in names
    entry = next(r for r in runs if r["name"] == run_dir.name)
    assert "created_at" in entry and "snapshot_id" in entry and "strategies" in entry
    assert "full" in entry["strategies"]


def test_list_runs_skips_non_run_dirs(tmp_path):
    (tmp_path / "not_a_run").mkdir()
    assert readers.list_runs(tmp_path) == []
```

- [ ] **Step 2: 跑測試確認失敗。**
  Run: `uv run pytest tests/test_presentation/test_readers.py -k list_runs -v`
  Expected: FAIL（無 `list_runs`）

- [ ] **Step 3: 實作。** 在 `readers.py` 加：
```python
def list_runs(runs_root: str | Path) -> list[dict]:
    """掃 runs_root 下含 manifest.json 的 run 目錄，回 [{name, path, created_at, snapshot_id,
    git_commit, strategies}]，供全域控制列 run 選擇器。非 run 目錄（無 manifest）略過。"""
    root = Path(runs_root)
    out = []
    for d in sorted(root.iterdir()):
        mf = d / "manifest.json"
        if not (d.is_dir() and mf.exists()):
            continue
        manifest = json.loads(mf.read_text(encoding="utf-8"))
        ident = manifest.get("identity", {})
        metrics = load_metrics(d) if (d / "metrics.json").exists() else {}
        out.append(
            {
                "name": d.name,
                "path": str(d),
                "created_at": manifest.get("created_at"),
                "snapshot_id": ident.get("snapshot_id"),
                "git_commit": ident.get("git_commit"),
                "strategies": sorted(metrics.keys()),
            }
        )
    return out
```
`__all__` 加 `list_runs`。

- [ ] **Step 4: 跑測試確認通過。**
  Run: `uv run pytest tests/test_presentation/test_readers.py -v`
  Expected: PASS

- [ ] **Step 5: Commit。**
```bash
git add quantcore/presentation/readers.py tests/test_presentation/test_readers.py
git commit -m "feat(phase7a): readers.list_runs（run 探索，供全域控制列）"
```

---

## Task 8: readers 全套件閘門 + 架構守護 + ruff

**Files:** 無（驗證）

- [ ] **Step 1: 跑 presentation 全套件。**
  Run: `uv run pytest tests/test_presentation/ -v`
  Expected: PASS（含架構守護測試——readers.py 只 import stdlib/pandas/yaml，無引擎）。

- [ ] **Step 2: 全套件不回歸（排除慢 AC 閘門）。**
  Run: `uv run pytest -m "not requires_snapshot" -q`
  Expected: PASS。

- [ ] **Step 3: lint/format。**
  Run: `uv run ruff check . && uv run ruff format --check .`
  Expected: PASS。

- [ ] **Step 4: 對真實 canonical run 冒煙（非測試，確認 readers 吃真實資料）。**
  Run:
```bash
uv run python - <<'PY'
import glob
from quantcore.presentation import readers
RUN = sorted(glob.glob("runs/*_canonical_dcc"))[-1]
runs = readers.list_runs("runs")
print("runs discovered:", len(runs))
dec = readers.load_decisions(RUN)
full = dec[(dec.strategy_id=="full") & (dec.selected.map(bool))].iloc[0]
L = readers.decision_layers(RUN, "full", full.decision_date)
print("layers ok:", L.selected, "E=", L.exposure_applied, "band_blocked=", L.band_blocked)
print("corr matrix shape:", readers.correlation_matrix_at(readers.load_correlation(RUN), "full", full.decision_date).shape)
print("trades:", None if readers.load_trades(RUN) is None else len(readers.load_trades(RUN)))
PY
```
  Expected: 印出 discovered runs、六層、相關矩陣形狀、交易筆數——readers 對真實資料無誤。

- [ ] **Step 5: Commit（若 ruff format 有改動）。**
```bash
git add -A && git commit -m "chore(phase7a): ruff format" || echo "無 format 改動"
```

---

## 完成後
Plan 2a 完成 → `readers.py` 全 loader + Decision Explorer 六層（AC① 自動化）+ 架構守護齊備、CI 可跑。

**下一步**：Plan 2b（`app.py` + 全域控制列 + 9 頁 Streamlit + AC① 人工手查）。屆時再開一份 writing-plans，頁面呼叫本層 readers、以 `streamlit.testing.v1.AppTest` 冒煙。

---

*Phase 7a 計畫 2a — 2026-07-30。實作設計文件 §5.1/§2/§6 的 readers 地基。Plan 2b（UI）待本計畫執行完後展開。*
