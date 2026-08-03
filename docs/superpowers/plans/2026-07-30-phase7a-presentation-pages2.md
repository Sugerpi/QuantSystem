# Phase 7a 計畫 2b-2 — dashboard 其餘 5 頁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 補齊 dashboard 其餘 5 頁——頁 3 GARCH、頁 4 相關結構、頁 6 消融、頁 7 資料品質、頁 9 價格與交易——讀 model_details/快照/ablation/trades，並接進 `app.py` 的 st.navigation。

**Architecture:** 沿用 2b-1：頁面薄、讀 `controls` + `readers`、plotly 畫圖、缺資料 `st.info` 優雅、`AppTest` 冒煙、AST 架構守護（不 import 引擎）。新增 readers 讀 vol_eval/ablation/snapshot 路徑；頁 4 用**頁內第二個 run 選擇器**做 DCC vs EWMA 疊圖（全域多 run 比較仍延後）。

**Tech Stack:** streamlit 1.59、plotly、pandas、numpy、scipy（QQ 理論分位）、pytest、uv、ruff。

---

## 設計依據
- 設計文件 §1（頁 3/4/6/7/9 資料就緒）、§11.2（頁面內容）。
- 前置：計畫 2a（readers 16 函數）+ 2b-1（app/controls/頁 1/2/5/8）完成。本機 `runs/` 有 canonical ewma/dcc、`runs/vol_eval/`、`runs/*_ablation`；快照 `2026-07-16_20ed09`。

## 真實 schema（ground truth，實測）
| 檔案 | 欄位 |
|---|---|
| `runs/vol_eval/vol_eval_comparison.parquet` | `ticker, spec(ewma\|garch_arch), n_points, n_fallback, qlike, mz_r2` |
| ablation `comparison.parquet` | `cell_label, strategy_id, annualized_return, sharpe, sortino, max_drawdown, calmar, annualized_turnover, cost_drag_bps_per_year, n_days, average_exposure` |
| ablation `bootstrap.parquet` | `vs, metric, point, lo, hi, excludes_zero` |
| `model_details/correlation.parquet` | `decision_date, strategy_id, ticker_i, ticker_j, corr`（僅 full/full_erc） |
| `model_details/residuals.parquet` | `strategy_id, ticker, date, std_resid` |
| `trades.parquet` | `execution_date, strategy_id, ticker, drifted_weight, target_weight, delta_weight, side, notional, fill_price, shares, cost` |
| `decisions.parquet` | `garch_params`(JSON {ticker:{omega,alpha,beta,nu}}|None), `vol_fell_back`(JSON dict), `corr_fell_back`(bool) |
| 快照 `metadata.json` | `overrides`(list), `sources`(dict), `tickers`(dict) |
| run `config.yaml` | `snapshot: snapshots/<id>` |

## 設計決定
- **頁 3 GARCH**：EWMA run 的 `garch_params` 為 None → 該頁「本策略無 GARCH 參數（EWMA）」優雅；GARCH run（canonical 預設 garch_arch）才顯參數軌跡。QQ 用 `scipy.stats.norm.ppf`，ACF 用 numpy 自相關。**已實現波動 proxy 疊圖**留後續 enrich（需快照報酬對齊，超出本段核心）。
- **頁 4 相關**：主 run 熱圖 + 時間滑桿 + 資產對時間序列 + `corr_fell_back` 標記；DCC vs EWMA 疊圖用**頁內第二 run 選擇器**（避免全域多 run 重構）。
- **頁 6 消融**：讀選中 run 的 `comparison.parquet`/`bootstrap.parquet`（缺則優雅）；指標表 + 敏感度熱圖（cell×strategy 的 Sharpe）+ 配對 bootstrap CI + 常駐提示「敏感度表用於檢驗穩健性，不是挑最好的一格」。
- **頁 7 資料品質**：由選中 run 的 `config.yaml` 找快照 → MANIFEST/sources/tickers/overrides。
- **頁 9 價格與交易**：由選中 run 的快照 adj_close 面板 + `trades.parquet`；多選標的、價格折線 + 買賣標記 + blotter 表。
- 新 readers 一律缺檔回 `None`（比照既有），不 import 引擎。

## 檔案結構
| 檔案 | 動作 |
|---|---|
| `pyproject.toml` | 加 scipy（QQ）| 修改 |
| `quantcore/presentation/readers.py` | +`load_vol_eval`/`load_comparison`/`load_bootstrap`/`snapshot_dir_for_run` | 修改 |
| `quantcore/presentation/pages/3_GARCH.py` | 新增 |
| `quantcore/presentation/pages/4_Correlation.py` | 新增 |
| `quantcore/presentation/pages/6_Ablation.py` | 新增 |
| `quantcore/presentation/pages/7_Data_Quality.py` | 新增 |
| `quantcore/presentation/pages/9_Price_Trades.py` | 新增 |
| `quantcore/presentation/app.py` | st.navigation 加 5 頁 | 修改 |
| `tests/test_presentation/test_readers.py` | +新 readers 測試 | 修改 |
| `tests/test_presentation/test_app_smoke.py` | +5 頁冒煙 | 修改 |

---

## Task 1: 新 readers（vol_eval / comparison / bootstrap / snapshot_dir_for_run）

**Files:** modify `quantcore/presentation/readers.py`, `tests/test_presentation/test_readers.py`.

- [ ] **Step 1: 寫失敗測試。** 追加到 `tests/test_presentation/test_readers.py`：
```python
def test_load_comparison_bootstrap_absent_returns_none(tmp_path):
    assert readers.load_comparison(tmp_path) is None
    assert readers.load_bootstrap(tmp_path) is None
    assert readers.load_vol_eval(tmp_path) is None


def test_snapshot_dir_for_run(run_dir):
    # run 的 config.yaml 有 snapshot 欄；snapshot_dir_for_run 應回其 Path
    from quantcore.presentation import readers as R

    cfg = R.load_run_config(run_dir)
    got = R.snapshot_dir_for_run(run_dir)
    assert str(got) == cfg["snapshot"]
```

- [ ] **Step 2: 跑確認失敗。** `uv run pytest tests/test_presentation/test_readers.py -k "comparison or bootstrap or snapshot_dir" -v` → FAIL。

- [ ] **Step 3: 實作。** 在 `readers.py` 加（各名稱進 `__all__`）：
```python
def load_comparison(run_dir: str | Path) -> pd.DataFrame | None:
    """ablation comparison.parquet（cell_label×strategy×指標）。缺 → None。"""
    p = Path(run_dir) / "comparison.parquet"
    return pd.read_parquet(p) if p.exists() else None


def load_bootstrap(run_dir: str | Path) -> pd.DataFrame | None:
    """ablation bootstrap.parquet（vs/metric/point/lo/hi/excludes_zero）。缺 → None。"""
    p = Path(run_dir) / "bootstrap.parquet"
    return pd.read_parquet(p) if p.exists() else None


def load_vol_eval(vol_eval_dir: str | Path) -> pd.DataFrame | None:
    """vol_eval_comparison.parquet（ticker×spec 的 qlike/mz_r2）。缺 → None。"""
    p = Path(vol_eval_dir) / "vol_eval_comparison.parquet"
    return pd.read_parquet(p) if p.exists() else None


def snapshot_dir_for_run(run_dir: str | Path) -> Path:
    """該 run 的 config.yaml 記錄的快照目錄（供頁 7/9 讀快照）。"""
    return Path(load_run_config(run_dir)["snapshot"])
```

- [ ] **Step 4: 跑確認通過。** `uv run pytest tests/test_presentation/test_readers.py tests/test_presentation/test_architecture.py -v` → PASS。

- [ ] **Step 5: Commit。**
```bash
git add quantcore/presentation/readers.py tests/test_presentation/test_readers.py
git commit -m "feat(phase7a): readers load_comparison/bootstrap/vol_eval + snapshot_dir_for_run"
```

---

## Task 2: 頁 3 GARCH

**Files:** modify `pyproject.toml`（加 scipy）; create `quantcore/presentation/pages/3_GARCH.py`; extend `test_app_smoke.py`.

- [ ] **Step 1: 加 scipy。** `uv add scipy 2>&1 | tail -2`（QQ 理論分位；已為 arch 傳遞相依，此處顯式化）。

- [ ] **Step 2: 寫失敗冒煙測試。** 追加到 `test_app_smoke.py`：
```python
def test_garch_page_renders(runs_root, run_dir):
    at = AppTest.from_file("quantcore/presentation/pages/3_GARCH.py", default_timeout=30)
    _seed(at, runs_root, run_dir.name, strategy="full")
    at.run()
    assert not at.exception
    assert any("GARCH" in t.value or "波動" in t.value for t in at.title)
```

- [ ] **Step 3: 跑確認失敗。** `uv run pytest tests/test_presentation/test_app_smoke.py -k garch -v` → FAIL。

- [ ] **Step 4: 實作頁 3。** 建 `quantcore/presentation/pages/3_GARCH.py`：
```python
"""頁 3 GARCH 檢視（§11.2）：參數軌跡、persistence、fallback、QLIKE/MZ-R²、殘差 QQ/ACF。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scipy import stats

from quantcore.presentation import controls, readers

st.title("GARCH 檢視")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)
_strats = controls.selected_strategies(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
dec = readers.load_decisions(run_dir)
strat = (_strats or sorted(dec["strategy_id"].unique()))[0]
sub = dec[(dec["strategy_id"] == strat)].sort_values("decision_date")

# 參數軌跡（ω,α,β,ν）+ persistence
st.subheader("GARCH 參數軌跡與 persistence")
rows = []
for _, r in sub.iterrows():
    gp = r["garch_params"]
    if not gp:
        continue
    for t, p in gp.items():
        if p:
            rows.append({"date": r["decision_date"], "ticker": t, **p, "persistence": p["alpha"] + p["beta"]})
if not rows:
    st.info("本策略/此 run 無 GARCH 參數（EWMA 或非波動目標策略）。")
else:
    import pandas as pd

    pt = pd.DataFrame(rows)
    tick = st.selectbox("資產", sorted(pt["ticker"].unique()))
    tp = pt[pt["ticker"] == tick].sort_values("date")
    fig = go.Figure()
    for col in ("omega", "alpha", "beta", "nu", "persistence"):
        fig.add_trace(go.Scatter(x=tp["date"], y=tp[col], name=col, mode="lines"))
    fig.update_layout(height=360)
    st.plotly_chart(fig, use_container_width=True)

# fallback 頻率
st.subheader("GARCH fallback 頻率（vol_fell_back）")
fb = []
for _, r in sub.iterrows():
    d = r["vol_fell_back"] or {}
    for t, v in d.items():
        fb.append({"ticker": t, "fell_back": bool(v)})
if fb:
    import pandas as pd

    fbdf = pd.DataFrame(fb).groupby("ticker")["fell_back"].mean().reset_index()
    st.plotly_chart(go.Figure(go.Bar(x=fbdf["ticker"], y=fbdf["fell_back"])).update_layout(height=280),
                    use_container_width=True)
else:
    st.write("—")

# QLIKE / MZ-R²（vol_eval）
st.subheader("QLIKE / MZ-R²（GARCH vs EWMA）")
ve = readers.load_vol_eval(_root / "vol_eval")
if ve is None:
    st.info("本次未儲存（無 runs/vol_eval/）。")
else:
    st.dataframe(ve, use_container_width=True)

# 殘差 QQ + ACF
st.subheader("標準化殘差 QQ / ACF")
resid = readers.load_residuals(run_dir)
if resid is None or resid.empty:
    st.info("本次未儲存（無 model_details/residuals）。")
else:
    r_strat = resid[resid["strategy_id"] == strat] if "strategy_id" in resid.columns else resid
    tks = sorted(r_strat["ticker"].unique())
    if tks:
        tk = st.selectbox("殘差資產", tks, key="resid_tk")
        s = r_strat[r_strat["ticker"] == tk]["std_resid"].dropna().to_numpy()
        # QQ
        n = len(s)
        theo = stats.norm.ppf((np.arange(1, n + 1) - 0.5) / n)
        qq = go.Figure(go.Scatter(x=theo, y=np.sort(s), mode="markers"))
        lim = [min(theo.min(), s.min()), max(theo.max(), s.max())]
        qq.add_trace(go.Scatter(x=lim, y=lim, mode="lines", name="y=x"))
        qq.update_layout(height=320, title="QQ（標準化殘差 vs 常態）",
                         xaxis_title="理論分位", yaxis_title="樣本分位")
        st.plotly_chart(qq, use_container_width=True)
        # ACF（numpy 自相關，前 20 落後）
        s0 = s - s.mean()
        denom = np.dot(s0, s0)
        lags = min(20, n - 1)
        acf = [np.dot(s0[:-k], s0[k:]) / denom for k in range(1, lags + 1)]
        st.plotly_chart(go.Figure(go.Bar(x=list(range(1, lags + 1)), y=acf)).update_layout(
            height=280, title="ACF（標準化殘差）", xaxis_title="lag"), use_container_width=True)
```

- [ ] **Step 5: 跑確認通過。** `uv run pytest tests/test_presentation/test_app_smoke.py -k garch -v` → PASS。

- [ ] **Step 6: Commit。**
```bash
git add pyproject.toml uv.lock quantcore/presentation/pages/3_GARCH.py tests/test_presentation/test_app_smoke.py
git commit -m "feat(phase7a): 頁 3 GARCH（參數軌跡/persistence/fallback/QLIKE/殘差 QQ/ACF）"
```

---

## Task 3: 頁 4 相關結構

**Files:** create `quantcore/presentation/pages/4_Correlation.py`; extend `test_app_smoke.py`.

- [ ] **Step 1: 寫失敗冒煙測試。** 追加到 `test_app_smoke.py`：
```python
def test_correlation_page_renders(runs_root, run_dir):
    at = AppTest.from_file("quantcore/presentation/pages/4_Correlation.py", default_timeout=30)
    _seed(at, runs_root, run_dir.name, strategy="full")
    at.run()
    assert not at.exception
    assert any("相關" in s.value for s in at.subheader)
```

- [ ] **Step 2: 跑確認失敗。** `uv run pytest tests/test_presentation/test_app_smoke.py -k correlation_page -v` → FAIL。

- [ ] **Step 3: 實作頁 4。** 建 `quantcore/presentation/pages/4_Correlation.py`：
```python
"""頁 4 相關結構（§11.2）：相關矩陣熱圖 + 時間滑桿、資產對時間序列、DCC vs EWMA 疊圖。"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from quantcore.presentation import controls, readers

st.title("相關結構")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)
_strats = controls.selected_strategies(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
corr = readers.load_correlation(run_dir)
if corr is None or corr.empty:
    st.info("本次未儲存（無 model_details/correlation；僅 full/full_erc 有相關矩陣）。")
    st.stop()

strat = (_strats or sorted(corr["strategy_id"].unique()))[0]
csub = corr[corr["strategy_id"] == strat]
dates = sorted(csub["decision_date"].unique())

# 熱圖 + 時間滑桿
st.subheader("相關矩陣熱圖")
i = st.slider("決策日", 0, len(dates) - 1, len(dates) - 1)
mat = readers.correlation_matrix_at(csub, strat, dates[i])
st.plotly_chart(go.Figure(go.Heatmap(z=mat.values, x=list(mat.columns), y=list(mat.index),
                zmin=-1, zmax=1, colorscale="RdBu")).update_layout(height=460),
                use_container_width=True)

# 任選資產對時間序列
st.subheader("資產對相關時間序列")
tickers = sorted(mat.index)
c1, c2 = st.columns(2)
ti = c1.selectbox("資產 i", tickers, index=0)
tj = c2.selectbox("資產 j", tickers, index=min(1, len(tickers) - 1))
pair = csub[(csub["ticker_i"] == ti) & (csub["ticker_j"] == tj)].sort_values("decision_date")
ts = go.Figure(go.Scatter(x=pair["decision_date"], y=pair["corr"], mode="lines", name=f"{ti}-{tj}"))

# DCC vs EWMA 疊圖：頁內選第二個 run
st.subheader("疊圖：另一個 run（DCC vs EWMA）")
others = [r["name"] for r in readers.list_runs(_root) if r["name"] != _runs[0]]
if others:
    r2 = st.selectbox("第二個 run", ["（不疊）"] + others)
    if r2 != "（不疊）":
        c2df = readers.load_correlation(_root / r2)
        if c2df is not None and not c2df.empty:
            s2 = (_strats or sorted(c2df["strategy_id"].unique()))[0]
            p2 = c2df[(c2df["strategy_id"] == s2) & (c2df["ticker_i"] == ti) & (c2df["ticker_j"] == tj)]
            p2 = p2.sort_values("decision_date")
            ts.add_trace(go.Scatter(x=p2["decision_date"], y=p2["corr"], mode="lines", name=f"{r2}"))
ts.update_layout(height=320, yaxis_title="corr")
st.plotly_chart(ts, use_container_width=True)
```

- [ ] **Step 4: 跑確認通過。** `uv run pytest tests/test_presentation/test_app_smoke.py -k correlation_page -v` → PASS。

- [ ] **Step 5: Commit。**
```bash
git add quantcore/presentation/pages/4_Correlation.py tests/test_presentation/test_app_smoke.py
git commit -m "feat(phase7a): 頁 4 相關結構（熱圖時間滑桿/資產對序列/第二 run 疊圖）"
```

---

## Task 4: 頁 6 消融

**Files:** create `quantcore/presentation/pages/6_Ablation.py`; extend `test_app_smoke.py`.

- [ ] **Step 1: 寫失敗冒煙測試。** 追加到 `test_app_smoke.py`：
```python
def test_ablation_page_graceful(runs_root, run_dir):
    at = AppTest.from_file("quantcore/presentation/pages/6_Ablation.py", default_timeout=30)
    _seed(at, runs_root, run_dir.name)
    at.run()
    assert not at.exception  # 合成 run 無 comparison → 優雅提示，不崩潰
```

- [ ] **Step 2: 跑確認失敗。** `uv run pytest tests/test_presentation/test_app_smoke.py -k ablation_page -v` → FAIL。

- [ ] **Step 3: 實作頁 6。** 建 `quantcore/presentation/pages/6_Ablation.py`：
```python
"""頁 6 消融比較（§11.2）：指標表、敏感度熱圖、配對 bootstrap CI。"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from quantcore.presentation import controls, readers

st.title("消融比較")
st.caption("提示：敏感度表用於檢驗穩健性，不是用來挑最好的一格。")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
comp = readers.load_comparison(run_dir)
if comp is None:
    st.info("本 run 無消融表（comparison.parquet）——請選一個消融 run。")
    st.stop()

st.subheader("指標表")
st.dataframe(comp, use_container_width=True)

# 敏感度熱圖（cell × strategy 的 Sharpe）
st.subheader("敏感度熱圖（Sharpe：cell × 策略）")
metric = st.selectbox("指標", ["sharpe", "calmar", "max_drawdown", "annualized_return"])
piv = comp.pivot_table(index="cell_label", columns="strategy_id", values=metric)
st.plotly_chart(go.Figure(go.Heatmap(z=piv.values, x=list(piv.columns), y=list(piv.index),
                colorscale="Viridis")).update_layout(height=420), use_container_width=True)

# 配對 bootstrap CI
st.subheader("配對 bootstrap CI（full vs 消融版）")
bs = readers.load_bootstrap(run_dir)
if bs is None:
    st.info("本 run 無 bootstrap.parquet。")
else:
    st.dataframe(bs, use_container_width=True)
```

- [ ] **Step 4: 跑確認通過。** `uv run pytest tests/test_presentation/test_app_smoke.py -k ablation_page -v` → PASS。

- [ ] **Step 5: Commit。**
```bash
git add quantcore/presentation/pages/6_Ablation.py tests/test_presentation/test_app_smoke.py
git commit -m "feat(phase7a): 頁 6 消融（指標表/敏感度熱圖/配對 bootstrap CI）"
```

---

## Task 5: 頁 7 資料品質

**Files:** create `quantcore/presentation/pages/7_Data_Quality.py`; extend `test_app_smoke.py`.

- [ ] **Step 1: 寫失敗冒煙測試。** 追加到 `test_app_smoke.py`：
```python
def test_data_quality_page(runs_root, run_dir):
    at = AppTest.from_file("quantcore/presentation/pages/7_Data_Quality.py", default_timeout=30)
    _seed(at, runs_root, run_dir.name)
    at.run()
    assert not at.exception
```

- [ ] **Step 2: 跑確認失敗。** `uv run pytest tests/test_presentation/test_app_smoke.py -k data_quality -v` → FAIL。

- [ ] **Step 3: 實作頁 7。** 建 `quantcore/presentation/pages/7_Data_Quality.py`：
```python
"""頁 7 資料品質（§11.2）：快照 MANIFEST、跨源差異、總報酬驗證、overrides 清單。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from quantcore.presentation import controls, readers

st.title("資料品質")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
snap_dir = readers.snapshot_dir_for_run(run_dir)
if not snap_dir.exists():
    st.info(f"快照 {snap_dir} 不在本機（可能只有 hash 進版控）。")
    st.stop()

st.subheader("快照 MANIFEST")
st.json(readers.load_snapshot_manifest(snap_dir))

meta = readers.load_snapshot_metadata(snap_dir)
st.subheader("資料源")
st.json(meta.get("sources", {}))

st.subheader(f"跨源裁決 overrides（{len(meta.get('overrides', []))} 筆）")
ov = meta.get("overrides", [])
if ov:
    st.dataframe(pd.DataFrame(ov), use_container_width=True)
else:
    st.write("無 overrides。")

st.subheader("選單 tickers")
st.json(meta.get("tickers", {}))
```

- [ ] **Step 4: 跑確認通過。** `uv run pytest tests/test_presentation/test_app_smoke.py -k data_quality -v` → PASS。
  （合成 run 的 config `snapshot` 指向合成 tmp 快照且該路徑不存在 → 走「快照不在本機」優雅分支，`at.exception` 仍 None。）

- [ ] **Step 5: Commit。**
```bash
git add quantcore/presentation/pages/7_Data_Quality.py tests/test_presentation/test_app_smoke.py
git commit -m "feat(phase7a): 頁 7 資料品質（MANIFEST/資料源/overrides/tickers）"
```

---

## Task 6: 頁 9 價格與交易

**Files:** create `quantcore/presentation/pages/9_Price_Trades.py`; extend `test_app_smoke.py`.

- [ ] **Step 1: 寫失敗冒煙測試。** 追加到 `test_app_smoke.py`：
```python
def test_price_trades_page(runs_root, run_dir):
    at = AppTest.from_file("quantcore/presentation/pages/9_Price_Trades.py", default_timeout=30)
    _seed(at, runs_root, run_dir.name, strategy="full")
    at.run()
    assert not at.exception
    assert any("交易" in s.value or "價格" in s.value for s in at.subheader)
```

- [ ] **Step 2: 跑確認失敗。** `uv run pytest tests/test_presentation/test_app_smoke.py -k price_trades -v` → FAIL。

- [ ] **Step 3: 實作頁 9。** 建 `quantcore/presentation/pages/9_Price_Trades.py`：
```python
"""頁 9 價格與交易（新增，§0/§3.5）：每檔 adj_close 折線 + 買賣標記 + blotter 明細表。"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from quantcore.presentation import controls, readers

st.title("價格與交易")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)
_strats = controls.selected_strategies(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
trades = readers.load_trades(run_dir)
if trades is None:
    st.info("本次未儲存（無 trades.parquet）。")
    st.stop()

strat = (_strats or sorted(trades["strategy_id"].unique()))[0]
tr = trades[trades["strategy_id"] == strat]
snap_dir = readers.snapshot_dir_for_run(run_dir)
panel = readers.load_adj_close_panel(snap_dir) if snap_dir.exists() else None

st.subheader("價格與進出場")
tickers = sorted(tr["ticker"].unique())
picks = st.multiselect("標的", tickers, default=tickers[:1])
fig = go.Figure()
for tk in picks:
    if panel is not None and tk in panel.columns:
        fig.add_trace(go.Scatter(x=panel.index, y=panel[tk], name=f"{tk} price", mode="lines"))
    t = tr[tr["ticker"] == tk]
    for side, sym, col in (("buy", "triangle-up", "#2ca02c"), ("sell", "triangle-down", "#d62728")):
        ts = t[t["side"] == side]
        y = (panel.loc[ts["execution_date"], tk].to_numpy()
             if panel is not None and tk in panel.columns else ts["fill_price"].to_numpy())
        fig.add_trace(go.Scatter(x=ts["execution_date"], y=y, mode="markers", name=f"{tk} {side}",
                      marker=dict(symbol=sym, size=9, color=col)))
fig.update_layout(height=460)
st.plotly_chart(fig, use_container_width=True)

st.subheader("交易明細（blotter）")
st.dataframe(tr.sort_values("execution_date"), use_container_width=True)
```

- [ ] **Step 4: 跑確認通過。** `uv run pytest tests/test_presentation/test_app_smoke.py -k price_trades -v` → PASS。
  （合成 run 的快照 tmp 路徑不存在 → `panel=None`，價格線略、以 blotter fill_price 標記 y，仍不崩潰。）

- [ ] **Step 5: Commit。**
```bash
git add quantcore/presentation/pages/9_Price_Trades.py tests/test_presentation/test_app_smoke.py
git commit -m "feat(phase7a): 頁 9 價格與交易（adj_close 折線 + 買賣標記 + blotter 表）"
```

---

## Task 7: 接進 app.py + 全套件閘門 + 真實 run 冒煙

**Files:** modify `quantcore/presentation/app.py`; 驗證。

- [ ] **Step 1: app.py 加 5 頁。** 把 `_PAGES` 改為（依 §11.2 頁序）：
```python
_PAGES = [
    st.Page("pages/1_Overview.py", title="總覽", default=True),
    st.Page("pages/2_Decision_Explorer.py", title="決策解剖"),
    st.Page("pages/3_GARCH.py", title="GARCH"),
    st.Page("pages/4_Correlation.py", title="相關結構"),
    st.Page("pages/5_Portfolio_Cost.py", title="組合與成本"),
    st.Page("pages/6_Ablation.py", title="消融"),
    st.Page("pages/7_Data_Quality.py", title="資料品質"),
    st.Page("pages/8_Run_Lab.py", title="回測工作台"),
    st.Page("pages/9_Price_Trades.py", title="價格與交易"),
]
```

- [ ] **Step 2: 入口冒煙 + presentation 全套件。** `uv run pytest tests/test_presentation/ -v` → PASS（app 入口 + 9 頁 + 架構守護 + readers/2a 全綠）。

- [ ] **Step 3: 全套件不回歸 + ruff。** `uv run pytest -m "not requires_snapshot" -q` → PASS；`uv run ruff check . && uv run ruff format --check .` → PASS。

- [ ] **Step 4: 對真實 canonical 冒煙（非測試，確認 9 頁吃真實資料）。** 逐頁跑 AppTest 對 `runs/*_canonical_dcc`（有 garch_params/correlation/trades）：
```bash
uv run python - <<'PY'
import glob
from streamlit.testing.v1 import AppTest
RUN = sorted(glob.glob("runs/*_canonical_dcc"))[-1]
name = RUN.replace("\\", "/").split("/")[-1]
pages = ["1_Overview","2_Decision_Explorer","3_GARCH","4_Correlation","5_Portfolio_Cost",
         "6_Ablation","7_Data_Quality","8_Run_Lab","9_Price_Trades"]
for pg in pages:
    at = AppTest.from_file(f"quantcore/presentation/pages/{pg}.py", default_timeout=60)
    at.session_state["runs_root"] = "runs"
    at.session_state["selected_runs"] = [name]
    at.session_state["selected_strategies"] = ["full"]
    at.run()
    print(pg, "exception:", bool(at.exception), "" if not at.exception else str(at.exception)[:200])
PY
```
  Expected: 每頁 `exception: False`（頁 3 GARCH 對 dcc run 有真實參數軌跡；頁 4 有相關矩陣；頁 9 有 trades + 真實快照價格；頁 6 對 canonical run 走「無消融」優雅）。若任一頁 True，停下 systematic-debugging。

  然後**單獨對 ablation run 冒煙頁 6 的 rich path**（canonical run 無 comparison，故上面只測到頁 6 的優雅分支）：
```bash
uv run python - <<'PY'
import glob
from streamlit.testing.v1 import AppTest
ABL = glob.glob("runs/*ablation*")[0].replace("\\", "/").split("/")[-1]
at = AppTest.from_file("quantcore/presentation/pages/6_Ablation.py", default_timeout=60)
at.session_state["runs_root"] = "runs"; at.session_state["selected_runs"] = [ABL]
at.run()
print("頁6 vs ablation exception:", bool(at.exception), "dataframes:", len(at.dataframe))
PY
```
  Expected: `exception: False`、`dataframes` ≥ 1（指標表 + bootstrap 表顯示）。

  > **已知邊界（記入 backlog）**：run 選擇器列出**所有** run，含 ablation run（無 `nav/decisions/weights`）。若使用者選 ablation run 去看 nav 類頁面（1/2/3/5/9），`load_nav`/`load_decisions` 會對缺核心檔拋 `FileNotFoundError`（核心檔缺＝真錯，非優雅退化）。2b-2 不處理；後續可為 run 加型別標記或選擇器過濾。頁 6 是 ablation run 的對應頁。

- [ ] **Step 5: Commit。**
```bash
git add quantcore/presentation/app.py
git commit -m "feat(phase7a): 9 頁全接進 app.py 導覽（§11.2 頁序）"
```

---

## 完成後
Plan 2b-2 完成 → dashboard 9 頁齊備（8 唯讀 + Run Lab stub），對真實 canonical/ablation run 可用。**Phase 7a UI 段（計畫 2b）完成。**

**下一步**：7b Run Lab（引擎端 status.json 心跳 + job runner + subprocess CLI + 崩潰復原，AC②③）、7c 研究報告。以及 2b 累積的 backlog（快取、全域多 run 疊圖、§11.2 richer 內容、頁 3 已實現波動 proxy）。

---

*Phase 7a 計畫 2b-2 — 2026-07-30。實作設計文件 §1/§11.2 的頁 3/4/6/7/9。7b/7c 另計畫。*
