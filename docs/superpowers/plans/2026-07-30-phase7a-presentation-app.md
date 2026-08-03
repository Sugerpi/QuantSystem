# Phase 7a 計畫 2b-1 — dashboard app 骨架 + 核心 3 頁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建 Streamlit dashboard 入口 `app.py` + 全域控制列 + 3 個資料全備頁（總覽、決策解剖=AC①、組合與成本）+ Run Lab stub，全部以 `AppTest` 冒煙守護，並完成 **AC① 人工手查**文件。

**Architecture:** `app.py` 用 `st.navigation([st.Page(...)])` 定義多頁（明確中文標題、取代 auto-`pages/` 偵測）；`controls.render_sidebar()` 在每頁前執行、把「run 多選 / 策略 / 日期範圍」寫入 `st.session_state`；頁面檔案薄——讀 `controls` accessors + `readers`（計畫 2a）+ plotly 畫圖。`presentation/` 仍**永不 import 引擎**（AST 架構守護測試覆蓋 app/controls/pages）。

**Tech Stack:** Python 3.12、streamlit 1.60、plotly 6.9、pandas、pytest、uv、ruff。`streamlit.testing.v1.AppTest` 冒煙（`at.run(); assert not at.exception`，session_state 可預注入）。

---

## 設計依據
- 設計文件 §5.2（app.py）、§5.3（pages）、§5.4（依賴）、§6（測試）、§2（Decision Explorer 六層 = AC①）。
- 前置：計畫 2a 完成——`quantcore/presentation/readers.py` 有 16 函數（`list_runs`/`load_nav`/`load_weights`/`load_metrics`/`load_decisions`/`decision_layers`/`load_trades`/`load_correlation`/`load_residuals`/`correlation_matrix_at`/`load_adj_close_panel`/`load_snapshot_metadata`/`load_snapshot_manifest`/`load_manifest`/`load_run_config` + `DecisionLayers`）。本機 `runs/` 有 2 canonical run（ewma/dcc）。
- **本計畫只做頁 1/2/5 + 頁 8 stub**。頁 3/4/6/7/9 屬計畫 2b-2。

## 驗證過的 Streamlit API（ground truth）
- `st.navigation([st.Page("path", title=..., default=?)]) -> nav; nav.run()`；`st.Page` 吃檔案路徑 + 明確 `title`。用 st.navigation 時 auto-`pages/` 偵測被取代。
- `AppTest.from_file(path, *, default_timeout=3)`、`.run()`、`.exception`（None=無例外）、`.sidebar`、`.title`、`.metric` 等元素存取；`.session_state[k]=v` 可在 `.run()` 前預注入。
- plotly：`st.plotly_chart(fig)`；`import plotly.graph_objects as go`。

## Streamlit 實作風險與 fallback（兩處已知不確定性，implementer 遇到即用 fallback）
1. **`st.Page("pages/..")` 相對路徑解析**：Streamlit 以「入口檔所在目錄」解析 st.Page 相對路徑（app.py 在 `presentation/` → `pages/..` 對到 `presentation/pages/..`）。若 `AppTest.from_file` 下相對路徑解析失敗，改用絕對路徑：`from pathlib import Path` + `_HERE = Path(__file__).parent` + `st.Page(_HERE / "pages" / "1_Overview.py", title=..)`。
2. **`st.stop()` 在 AppTest 下**：`st.stop()` 是 Streamlit 正常控制流，`AppTest` 應視為正常停止（`at.exception` 仍 None）。若某版本把它記為例外，改為 `if _runs:` 包住頁面主體、`else: st.info(...)`（不用 st.stop）。冒煙測試 `*_graceful` 會抓到此差異。

## 檔案結構
| 檔案 | 職責 | 動作 |
|---|---|---|
| `pyproject.toml` | 加 streamlit/plotly 相依 | 修改 |
| `quantcore/presentation/controls.py` | `runs_root`/`selected_runs`/`selected_strategies`/`date_range` accessors + `render_sidebar` | 新增 |
| `quantcore/presentation/app.py` | st.navigation 入口 + render_sidebar | 新增 |
| `quantcore/presentation/pages/1_Overview.py` | 總覽 | 新增 |
| `quantcore/presentation/pages/2_Decision_Explorer.py` | 決策解剖（AC① UI） | 新增 |
| `quantcore/presentation/pages/5_Portfolio_Cost.py` | 組合與成本 | 新增 |
| `quantcore/presentation/pages/8_Run_Lab.py` | Run Lab stub（顯示 Phase 7b） | 新增 |
| `tests/test_presentation/test_controls.py` | controls accessors 單元測試 | 新增 |
| `tests/test_presentation/test_app_smoke.py` | app + 4 頁 AppTest 冒煙 | 新增 |
| `docs/phase7a-ac1-handcheck.md` | AC① 人工手查文件 | 新增 |

## 設計決定
- **控制列在 `app.py`、狀態走 `session_state`**：頁面讀 `controls` accessors（session_state，缺省優雅）；冒煙測試直接預注入 session_state 測單頁。
- **runs_root 解析順序**：`session_state["runs_root"]` → 環境變數 `QUANTCORE_RUNS_ROOT` → `"runs"`。讓冒煙測試/部署可指向不同根。
- **頁面對「未選 run / 缺資料」優雅**：顯示提示 `st.info(...)` 後 `return`，不拋例外（冒煙與真實皆穩）。
- **plotly 用 graph_objects**：對數 NAV、堆疊面積、瀑布皆手控；零前端碼。
- ASCII 檔名 + `st.Page(title="中文")`：檔名穩健跨平台，導覽標題由 st.Page 給中文。

---

## Task 1: 相依 + controls.py + 冒煙 fixture

**Files:** modify `pyproject.toml`; create `quantcore/presentation/controls.py`, `tests/test_presentation/test_controls.py`; extend `tests/test_presentation/conftest.py`.

- [ ] **Step 1: 加相依。** `uv add streamlit plotly`（進主 `dependencies`）。
  Run: `uv add streamlit plotly 2>&1 | tail -3`
  Expected: 安裝成功、`pyproject.toml`/`uv.lock` 更新。

- [ ] **Step 2: 擴充 conftest 加 runs-root fixture。** 在 `tests/test_presentation/conftest.py` 末尾加（沿用既有 `run_dir` fixture）：
```python
@pytest.fixture(scope="session")
def runs_root(run_dir):
    """run_dir 的父目錄——作為 dashboard 的 runs 根（含一個合成 run）。"""
    return run_dir.parent
```

- [ ] **Step 3: 寫失敗測試。** 建 `tests/test_presentation/test_controls.py`：
```python
from pathlib import Path

from quantcore.presentation import controls


def test_runs_root_prefers_session_then_env_then_default(monkeypatch):
    monkeypatch.delenv("QUANTCORE_RUNS_ROOT", raising=False)
    assert controls.runs_root({}) == Path("runs")
    monkeypatch.setenv("QUANTCORE_RUNS_ROOT", "/tmp/r")
    assert controls.runs_root({}) == Path("/tmp/r")
    assert controls.runs_root({"runs_root": "/tmp/s"}) == Path("/tmp/s")  # session 優先


def test_selection_accessors_default_empty():
    assert controls.selected_runs({}) == []
    assert controls.selected_strategies({}) == []
    assert controls.date_range({}) == (None, None)


def test_selection_accessors_read_state():
    st = {"selected_runs": ["r1"], "selected_strategies": ["full"], "date_range": ("2020", "2021")}
    assert controls.selected_runs(st) == ["r1"]
    assert controls.selected_strategies(st) == ["full"]
    assert controls.date_range(st) == ("2020", "2021")
```

- [ ] **Step 4: 跑測試確認失敗.** `uv run pytest tests/test_presentation/test_controls.py -v` → FAIL（無 controls）。

- [ ] **Step 5: 實作 controls.py。** 建 `quantcore/presentation/controls.py`：
```python
"""全域控制列 + 跨頁選擇存取（§11.2 全域控制列）。

accessors 收一個 mapping（st.session_state 或 dict），純函數、可獨立測。
render_sidebar 由 app.py 於每頁前呼叫，把選擇寫入 session_state。
不 import 引擎（§2.2）。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import streamlit as st

from quantcore.presentation import readers


def runs_root(state: Mapping) -> Path:
    """runs 根：session_state → 環境變數 QUANTCORE_RUNS_ROOT → 'runs'。"""
    val = state.get("runs_root") or os.environ.get("QUANTCORE_RUNS_ROOT") or "runs"
    return Path(val)


def selected_runs(state: Mapping) -> list[str]:
    return list(state.get("selected_runs") or [])


def selected_strategies(state: Mapping) -> list[str]:
    return list(state.get("selected_strategies") or [])


def date_range(state: Mapping) -> tuple:
    return tuple(state.get("date_range") or (None, None))


def render_sidebar() -> None:
    """側欄全域控制列：run 多選、策略多選、日期範圍。寫入 st.session_state。"""
    st.sidebar.title("QuantCore")
    root = runs_root(st.session_state)
    runs = readers.list_runs(root)
    if not runs:
        st.sidebar.warning(f"{root} 下無 run")
        return
    names = [r["name"] for r in runs]
    default = st.session_state.get("selected_runs") or names[-1:]
    st.sidebar.multiselect("Run（可多選比較）", names, default=default, key="selected_runs")

    strat_union = sorted(
        {s for r in runs if r["name"] in selected_runs(st.session_state) for s in r["strategies"]}
    )
    if strat_union:
        st.sidebar.multiselect("策略", strat_union, default=strat_union, key="selected_strategies")
```

- [ ] **Step 6: 跑測試確認通過.** `uv run pytest tests/test_presentation/test_controls.py tests/test_presentation/test_architecture.py -v` → PASS（controls 只 import streamlit/readers/stdlib，架構守護仍綠）。

- [ ] **Step 7: Commit.**
```bash
git add pyproject.toml uv.lock quantcore/presentation/controls.py tests/test_presentation/test_controls.py tests/test_presentation/conftest.py
git commit -m "feat(phase7a): dashboard 相依 + controls 全域控制列/accessors"
```

---

## Task 2: app.py（st.navigation 入口）+ 冒煙

**Files:** create `quantcore/presentation/app.py`, `tests/test_presentation/test_app_smoke.py`.

- [ ] **Step 1: 寫失敗冒煙測試。** 建 `tests/test_presentation/test_app_smoke.py`：
```python
"""dashboard AppTest 冒煙：入口 + 各頁對合成 run 渲染不拋例外。"""

from streamlit.testing.v1 import AppTest

_APP = "quantcore/presentation/app.py"


def _seed(at, runs_root, run_name, strategy="full"):
    at.session_state["runs_root"] = str(runs_root)
    at.session_state["selected_runs"] = [run_name]
    at.session_state["selected_strategies"] = [strategy]


def test_app_entry_renders(runs_root, run_dir):
    at = AppTest.from_file(_APP, default_timeout=30)
    _seed(at, runs_root, run_dir.name)
    at.run()
    assert not at.exception
```

- [ ] **Step 2: 跑測試確認失敗.** `uv run pytest tests/test_presentation/test_app_smoke.py -v` → FAIL（無 app.py）。

- [ ] **Step 3: 實作 app.py。** 建 `quantcore/presentation/app.py`：
```python
"""QuantCore dashboard 入口（§11.1/§11.2）。st.navigation 多頁 + 全域控制列。

行程邊界（§2.2）：只讀 runs/、snapshots/。不 import 引擎。
"""

from __future__ import annotations

import streamlit as st

from quantcore.presentation import controls

st.set_page_config(page_title="QuantCore Dashboard", layout="wide")

_PAGES = [
    st.Page("pages/1_Overview.py", title="總覽", default=True),
    st.Page("pages/2_Decision_Explorer.py", title="決策解剖"),
    st.Page("pages/5_Portfolio_Cost.py", title="組合與成本"),
    st.Page("pages/8_Run_Lab.py", title="回測工作台"),
]

nav = st.navigation(_PAGES)
controls.render_sidebar()
nav.run()
```

- [ ] **Step 4: 建 4 頁最小 stub 讓入口可跑。** 為使 st.navigation 不因缺檔失敗，先建 4 個最小頁檔（後續 task 填真內容）。建：
  - `quantcore/presentation/pages/1_Overview.py`：`import streamlit as st` + `st.title("總覽")`
  - `quantcore/presentation/pages/2_Decision_Explorer.py`：`import streamlit as st` + `st.title("決策解剖")`
  - `quantcore/presentation/pages/5_Portfolio_Cost.py`：`import streamlit as st` + `st.title("組合與成本")`
  - `quantcore/presentation/pages/8_Run_Lab.py`：`import streamlit as st` + `st.title("回測工作台")`

- [ ] **Step 5: 跑測試確認通過.** `uv run pytest tests/test_presentation/test_app_smoke.py tests/test_presentation/test_architecture.py -v` → PASS（入口渲染預設頁無例外；架構守護掃 app/controls/pages 皆無引擎 import）。

- [ ] **Step 6: Commit.**
```bash
git add quantcore/presentation/app.py quantcore/presentation/pages/ tests/test_presentation/test_app_smoke.py
git commit -m "feat(phase7a): dashboard app.py（st.navigation 入口 + 4 頁 stub）+ 入口冒煙"
```

---

## Task 3: 頁 1 總覽

**Files:** rewrite `quantcore/presentation/pages/1_Overview.py`; extend `test_app_smoke.py`.

- [ ] **Step 1: 寫失敗冒煙測試。** 追加到 `test_app_smoke.py`：
```python
def test_overview_renders(runs_root, run_dir):
    at = AppTest.from_file("quantcore/presentation/pages/1_Overview.py", default_timeout=30)
    _seed(at, runs_root, run_dir.name)
    at.run()
    assert not at.exception
    assert any("總覽" in t.value for t in at.title)


def test_overview_no_selection_is_graceful(runs_root):
    at = AppTest.from_file("quantcore/presentation/pages/1_Overview.py", default_timeout=30)
    at.session_state["runs_root"] = str(runs_root)
    at.session_state["selected_runs"] = []
    at.run()
    assert not at.exception  # 未選 run 也不崩潰
```

- [ ] **Step 2: 跑確認失敗（斷言 title / graceful）.** `uv run pytest tests/test_presentation/test_app_smoke.py -k overview -v` → FAIL（stub 無 graceful/內容）。

- [ ] **Step 3: 實作頁 1。** 覆寫 `quantcore/presentation/pages/1_Overview.py`：
```python
"""頁 1 總覽：NAV 對數疊圖、指標表、drawdown、曝險 E(t)、子期間表（§11.2）。"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quantcore.presentation import controls, readers

st.title("總覽")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)
_strats = controls.selected_strategies(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
nav = readers.load_nav(run_dir)
metrics = readers.load_metrics(run_dir)
decisions = readers.load_decisions(run_dir)
shown = _strats or sorted(nav["strategy_id"].unique())

# NAV 對數疊圖
fig = go.Figure()
for sid in shown:
    sub = nav[nav["strategy_id"] == sid].sort_values("date")
    fig.add_trace(go.Scatter(x=sub["date"], y=sub["nav"], name=sid, mode="lines"))
fig.update_yaxes(type="log", title="NAV（對數）")
fig.update_layout(title="NAV 疊圖", height=420)
st.plotly_chart(fig, use_container_width=True)

# 指標表
rows = [{"strategy": s, **{k: metrics[s][k] for k in
        ("annualized_return", "sharpe", "sortino", "max_drawdown", "calmar",
         "annualized_turnover", "average_exposure")}} for s in shown if s in metrics]
st.subheader("指標")
st.dataframe(pd.DataFrame(rows).set_index("strategy"), use_container_width=True)

# Drawdown
st.subheader("回撤")
dd = go.Figure()
for sid in shown:
    sub = nav[nav["strategy_id"] == sid].sort_values("date")
    cummax = sub["nav"].cummax()
    dd.add_trace(go.Scatter(x=sub["date"], y=sub["nav"] / cummax - 1.0, name=sid, mode="lines"))
dd.update_layout(height=300, yaxis_title="drawdown")
st.plotly_chart(dd, use_container_width=True)

# 曝險 E(t)（decisions.exposure_applied）
st.subheader("曝險 E(t)")
et = go.Figure()
for sid in shown:
    sub = decisions[(decisions["strategy_id"] == sid) & decisions["exposure_applied"].notna()]
    if not sub.empty:
        sub = sub.sort_values("decision_date")
        et.add_trace(go.Scatter(x=sub["decision_date"], y=sub["exposure_applied"], name=sid))
et.update_layout(height=300, yaxis_title="E(t)")
st.plotly_chart(et, use_container_width=True)

# 子期間表（第一個選中策略）
if shown and shown[0] in metrics and metrics[shown[0]].get("subperiods"):
    st.subheader(f"子期間績效（{shown[0]}）")
    st.dataframe(pd.DataFrame(metrics[shown[0]]["subperiods"]), use_container_width=True)
```

- [ ] **Step 4: 跑確認通過.** `uv run pytest tests/test_presentation/test_app_smoke.py -k overview -v` → PASS。

- [ ] **Step 5: Commit.**
```bash
git add quantcore/presentation/pages/1_Overview.py tests/test_presentation/test_app_smoke.py
git commit -m "feat(phase7a): 頁 1 總覽（NAV 對數疊圖/指標/回撤/曝險/子期間）"
```

---

## Task 4: 頁 2 決策解剖（AC① UI）

**Files:** rewrite `quantcore/presentation/pages/2_Decision_Explorer.py`; extend `test_app_smoke.py`.

- [ ] **Step 1: 寫失敗冒煙測試。** 追加到 `test_app_smoke.py`：
```python
def test_decision_explorer_renders_six_layers(runs_root, run_dir):
    at = AppTest.from_file("quantcore/presentation/pages/2_Decision_Explorer.py", default_timeout=30)
    _seed(at, runs_root, run_dir.name, strategy="full")
    at.run()
    assert not at.exception
    # 六層小標題皆出現（markdown/subheader 文字）
    text = " ".join(m.value for m in at.markdown) + " ".join(s.value for s in at.subheader)
    for layer in ("合格選單", "動量分數", "絕對動量", "波動", "曝險", "目標權重"):
        assert layer in text
```

- [ ] **Step 2: 跑確認失敗.** `uv run pytest tests/test_presentation/test_app_smoke.py -k decision_explorer -v` → FAIL。

- [ ] **Step 3: 實作頁 2。** 覆寫 `quantcore/presentation/pages/2_Decision_Explorer.py`：
```python
"""頁 2 決策解剖（Decision Explorer，§11.2）：六層垂直瀑布。AC① 的 UI 出口。

資料源：readers.decision_layers（計畫 2a，逐層對應 decisions.parquet）。
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quantcore.presentation import controls, readers

st.title("決策解剖")

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
sub = dec[dec["strategy_id"] == strat].sort_values("decision_date")
if sub.empty:
    st.info(f"{strat} 無決策紀錄。")
    st.stop()

dates = list(sub["decision_date"])
idx = st.slider("決策日", 0, len(dates) - 1, len(dates) - 1)
ddate = dates[idx]
L = readers.decision_layers(run_dir, strat, ddate)
st.caption(f"{strat} · {pd.Timestamp(ddate).date()} · event={L.event} · exec={L.execution_date}")

# (a) 合格選單
st.subheader("(a) point-in-time 合格選單")
st.write(", ".join(L.eligible))

# (b) 動量分數長條圖，前 K 高亮
st.subheader("(b) 動量分數（前 K 高亮）")
if L.momentum_scores:
    items = sorted(L.momentum_scores.items(), key=lambda kv: kv[1], reverse=True)
    colors = ["#2ca02c" if k in (L.selected or []) else "#b0b0b0" for k, _ in items]
    bar = go.Figure(go.Bar(x=[k for k, _ in items], y=[v for _, v in items], marker_color=colors))
    bar.update_layout(height=300)
    st.plotly_chart(bar, use_container_width=True)
else:
    st.write("本策略無動量層。")

# (c) 絕對動量 pass/fail
st.subheader("(c) 絕對動量 pass/fail")
if L.absmom:
    st.dataframe(pd.DataFrame({"ticker": list(L.absmom), "pass": list(L.absmom.values())}),
                 use_container_width=True)
else:
    st.write("—")

# (d) GARCH σ̂（年化純量，含前一決策日對照）
st.subheader("(d) 波動 σ̂（年化，vs 上一決策日）")
prev = sub[sub["decision_date"] < ddate]
prev_sigma = readers.decision_layers(run_dir, strat, prev["decision_date"].iloc[-1]).sigma_hat \
    if not prev.empty else None
if L.sigma_hat:
    rows = [{"ticker": t, "σ̂": v, "σ̂(前)": (prev_sigma or {}).get(t)} for t, v in L.sigma_hat.items()]
    st.dataframe(pd.DataFrame(rows).set_index("ticker"), use_container_width=True)
else:
    st.write("—")

# (e) 曝險公式展開
st.subheader("(e) 曝險：E = clip(σ*/σ̂_p)")
if L.sigma_p is not None:
    st.write({"σ̂_p": L.sigma_p, "exposure_raw": L.exposure_raw,
              "exposure_applied": L.exposure_applied, "band_blocked": bool(L.band_blocked)})
    if L.w_risky:
        st.caption("inverse-vol 權重 w_risky")
        st.dataframe(pd.DataFrame({"ticker": list(L.w_risky), "w_risky": list(L.w_risky.values())}),
                     use_container_width=True)
else:
    st.write("本策略無曝險層。")

# (f) 最終目標權重 vs 漂移後現況
st.subheader("(f) 目標權重（含 CASH）")
st.dataframe(pd.DataFrame({"ticker": list(L.target_weights),
                           "target": list(L.target_weights.values())}).set_index("ticker"),
             use_container_width=True)
```

- [ ] **Step 4: 跑確認通過.** `uv run pytest tests/test_presentation/test_app_smoke.py -k decision_explorer -v` → PASS。

- [ ] **Step 5: Commit.**
```bash
git add quantcore/presentation/pages/2_Decision_Explorer.py tests/test_presentation/test_app_smoke.py
git commit -m "feat(phase7a): 頁 2 決策解剖 六層瀑布（AC① UI，讀 decision_layers）"
```

---

## Task 5: 頁 5 組合與成本

**Files:** rewrite `quantcore/presentation/pages/5_Portfolio_Cost.py`; extend `test_app_smoke.py`.

- [ ] **Step 1: 寫失敗冒煙測試。** 追加到 `test_app_smoke.py`：
```python
def test_portfolio_cost_renders(runs_root, run_dir):
    at = AppTest.from_file("quantcore/presentation/pages/5_Portfolio_Cost.py", default_timeout=30)
    _seed(at, runs_root, run_dir.name, strategy="full")
    at.run()
    assert not at.exception
    text = " ".join(s.value for s in at.subheader)
    assert "權重" in text and "成本" in text
```

- [ ] **Step 2: 跑確認失敗.** `uv run pytest tests/test_presentation/test_app_smoke.py -k portfolio -v` → FAIL。

- [ ] **Step 3: 實作頁 5。** 覆寫 `quantcore/presentation/pages/5_Portfolio_Cost.py`：
```python
"""頁 5 組合與成本（§11.2）：權重堆疊面積、曝險軌跡+帶事件、換手、累積成本。"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from quantcore.presentation import controls, readers

st.title("組合與成本")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)
_strats = controls.selected_strategies(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
nav = readers.load_nav(run_dir)
weights = readers.load_weights(run_dir)
decisions = readers.load_decisions(run_dir)
strat = (_strats or sorted(nav["strategy_id"].unique()))[0]

# 權重堆疊面積（含現金）
st.subheader(f"權重堆疊（{strat}，含現金）")
w = weights[weights["strategy_id"] == strat]
wide = w.pivot_table(index="date", columns="ticker", values="weight", fill_value=0.0).sort_index()
area = go.Figure()
for col in wide.columns:
    area.add_trace(go.Scatter(x=wide.index, y=wide[col], name=col, stackgroup="w", mode="lines"))
area.update_layout(height=380)
st.plotly_chart(area, use_container_width=True)

# 曝險軌跡 + 帶事件標記（band_blocked）
st.subheader("曝險軌跡與帶事件")
d = decisions[(decisions["strategy_id"] == strat) & decisions["exposure_applied"].notna()].sort_values(
    "decision_date"
)
exp = go.Figure()
exp.add_trace(go.Scatter(x=d["decision_date"], y=d["exposure_applied"], name="E(t)", mode="lines"))
blocked = d[d["band_blocked"] == True]  # noqa: E712 (pandas nullable boolean 比對)
if not blocked.empty:
    exp.add_trace(go.Scatter(x=blocked["decision_date"], y=blocked["exposure_applied"],
                             name="band-blocked", mode="markers", marker_symbol="x"))
exp.update_layout(height=300, yaxis_title="E(t)")
st.plotly_chart(exp, use_container_width=True)

# 換手 + 累積成本
st.subheader("每次再平衡換手率與累積成本")
n = nav[nav["strategy_id"] == strat].sort_values("date")
tc = go.Figure()
tc.add_trace(go.Bar(x=n["date"], y=n["turnover"], name="turnover"))
tc.add_trace(go.Scatter(x=n["date"], y=n["cost"].cumsum(), name="累積成本", yaxis="y2", mode="lines"))
tc.update_layout(height=320, yaxis=dict(title="turnover"),
                 yaxis2=dict(title="累積成本", overlaying="y", side="right"))
st.plotly_chart(tc, use_container_width=True)
```

- [ ] **Step 4: 跑確認通過.** `uv run pytest tests/test_presentation/test_app_smoke.py -k portfolio -v` → PASS。

- [ ] **Step 5: Commit.**
```bash
git add quantcore/presentation/pages/5_Portfolio_Cost.py tests/test_presentation/test_app_smoke.py
git commit -m "feat(phase7a): 頁 5 組合與成本（權重堆疊/曝險帶事件/換手成本）"
```

---

## Task 6: 頁 8 Run Lab stub

**Files:** rewrite `quantcore/presentation/pages/8_Run_Lab.py`; extend `test_app_smoke.py`.

- [ ] **Step 1: 寫失敗冒煙測試。** 追加到 `test_app_smoke.py`：
```python
def test_run_lab_stub(runs_root, run_dir):
    at = AppTest.from_file("quantcore/presentation/pages/8_Run_Lab.py", default_timeout=30)
    _seed(at, runs_root, run_dir.name)
    at.run()
    assert not at.exception
    assert any("7b" in m.value or "Phase 7b" in m.value for m in at.info + at.markdown)
```
（`at.info` 為 st.info 元素列表；若該版本以 markdown 呈現，改判 markdown。實作用 `st.info`。）

- [ ] **Step 2: 跑確認失敗.** `uv run pytest tests/test_presentation/test_app_smoke.py -k run_lab -v` → FAIL。

- [ ] **Step 3: 實作頁 8 stub。** 覆寫 `quantcore/presentation/pages/8_Run_Lab.py`：
```python
"""頁 8 回測工作台（Run Lab）—— 7a 只放 stub，互動 job runner 於 Phase 7b（§11.3）。"""

import streamlit as st

st.title("回測工作台")
st.info("Run Lab（提交 config → subprocess 跑引擎 → status.json 輪詢）將於 **Phase 7b** 實作。")
st.caption("§11.3：單 worker 佇列、status.json 心跳、崩潰復原、schema 表單自動生成。")
```

- [ ] **Step 4: 跑確認通過.** `uv run pytest tests/test_presentation/test_app_smoke.py -k run_lab -v` → PASS。

- [ ] **Step 5: Commit.**
```bash
git add quantcore/presentation/pages/8_Run_Lab.py tests/test_presentation/test_app_smoke.py
git commit -m "feat(phase7a): 頁 8 Run Lab stub（指向 Phase 7b）"
```

---

## Task 7: 全套件閘門 + 架構守護 + ruff

**Files:** 無（驗證）。

- [ ] **Step 1: presentation 全套件.** `uv run pytest tests/test_presentation/ -v` → PASS（controls + app + 4 頁冒煙 + 2a 的 readers/守護/AC① golden 全綠）。
- [ ] **Step 2: 架構守護明確.** `uv run pytest tests/test_presentation/test_architecture.py -v` → PASS（app/controls/pages 皆不 import 引擎）。
- [ ] **Step 3: 全套件不回歸.** `uv run pytest -m "not requires_snapshot" -q` → PASS。
- [ ] **Step 4: lint/format.** `uv run ruff check . && uv run ruff format --check .` → PASS。
- [ ] **Step 5: Commit（若 format 有改動）.** `git add -A && git commit -m "chore(phase7a): ruff format" || echo 無改動`。

---

## Task 8: AC① 人工手查文件

**Files:** create `docs/phase7a-ac1-handcheck.md`。需本機真實 canonical run。

> AC① 的人工形式（設計 §0）：對真實 run 任選一決策日，Decision Explorer 六層 vs `decisions.parquet` 手查逐格一致，寫成文件。

- [ ] **Step 1: 選一個真實決策。** 挑 `runs/*_canonical_ewma` 的 `full` 策略一個有 selected 的決策日：
```bash
uv run python - <<'PY'
import glob, pandas as pd
from quantcore.presentation import readers
RUN = sorted(glob.glob("runs/*_canonical_ewma"))[-1]
dec = readers.load_decisions(RUN)
row = dec[(dec.strategy_id=="full") & (dec.selected.map(bool))].iloc[len(dec)//2]
print("RUN", RUN); print("date", row.decision_date)
L = readers.decision_layers(RUN, "full", row.decision_date)
print("eligible", L.eligible)
print("selected", L.selected)
print("momentum_scores", L.momentum_scores)
print("absmom", L.absmom)
print("sigma_hat", L.sigma_hat)
print("w_risky", L.w_risky)
print("sigma_p/exp_raw/exp_applied/band", L.sigma_p, L.exposure_raw, L.exposure_applied, L.band_blocked)
print("target_weights", L.target_weights)
PY
```

- [ ] **Step 2: 獨立手查原始 parquet 對照。** 用 `pandas` 直接讀該列原始 JSON 字串，逐層 `json.loads` 比對上一步 `decision_layers` 的輸出（六層逐格相同）：
```bash
uv run python - <<'PY'
import glob, json, pandas as pd
RUN = sorted(glob.glob("runs/*_canonical_ewma"))[-1]
dec = pd.read_parquet(f"{RUN}/decisions.parquet")
sub = dec[(dec.strategy_id=="full") & (dec.selected.map(lambda s: bool(json.loads(s))))]
row = sub.iloc[len(dec)//2] if len(sub)>len(dec)//2 else sub.iloc[len(sub)//2]
print("date", row.decision_date)
for c in ("eligible","selected","momentum_scores","absmom","sigma_hat","w_risky","target_weights"):
    print(c, json.loads(row[c]))
print("sigma_p", row.sigma_p, "exp_raw", row.exposure_raw, "exp_applied", row.exposure_applied, "band", row.band_blocked)
PY
```
  確認兩份輸出六層逐格一致（自動化 golden 已鎖，此為人工複核 + 存證）。

- [ ] **Step 3: 寫 handcheck 文件。** 建 `docs/phase7a-ac1-handcheck.md`，內容含：選定的 run / 策略 / 決策日、六層逐格數值表（Decision Explorer vs decisions.parquet 原始）、結論「六層逐格一致，AC① 人工手查通過」。附一句：自動化形式由 `tests/test_presentation/test_decision_explorer.py` 的 golden 常態守護。

- [ ] **Step 4: Commit.**
```bash
git add docs/phase7a-ac1-handcheck.md
git commit -m "docs(phase7a): AC① 人工手查（Decision Explorer 六層 vs decisions.parquet 逐格一致）"
```

---

## 完成後
Plan 2b-1 完成 → dashboard 可 `uv run streamlit run quantcore/presentation/app.py` 啟動，總覽/決策解剖/組合成本三頁對真實 canonical run 可用，**AC① 自動化 + 人工手查皆達成**，Run Lab 佔位。

**下一步**：Plan 2b-2（頁 3 GARCH / 頁 4 相關結構 / 頁 6 消融 / 頁 7 資料品質 / 頁 9 價格與交易，讀 model_details/快照/ablation/trades）。之後 7b Run Lab、7c 研究報告。

---

*Phase 7a 計畫 2b-1 — 2026-07-30。實作設計文件 §5.2/§5.3 的 app 骨架 + 核心 3 頁 + AC① 人工手查。頁 3/4/6/7/9 屬計畫 2b-2。*
