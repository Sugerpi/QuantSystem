# Phase 7 Web Dashboard 重製 — 計畫 1：Web 地基 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 FastAPI + Jinja2 + HTMX + Plotly 建出深色 Bloomberg 風 dashboard 的可運行骨架（左導覽 + 頂部控制列 + 一頁真資料的總覽），並退役 Streamlit 展示層。

**Architecture:** `presentation/web/` 新增伺服器渲染前端；`readers.py`（資料層）原封沿用；狀態走 URL query string；§2.2 行程邊界由既有 AST 守護（`rglob` 掃全 `presentation/`）自動涵蓋新 `web/`。本計畫只交付地基與總覽頁，其餘 8 頁在計畫 2。

**Tech Stack:** Python 3.11、FastAPI、Starlette `TestClient`（httpx）、Jinja2、Plotly（沿用）、HTMX（vendored）、pytest、ruff。

設計文件：[2026-07-31-phase7-web-dashboard-rebuild-design.md](../specs/2026-07-31-phase7-web-dashboard-rebuild-design.md)（§2 架構、§4 主題、§10 切段）。

**分支**：建議於新分支 `feature/phase7-web-dashboard` 進行（比照 repo 慣例 feature 分支 `--no-ff`）。本計畫所有 commit 落此分支。

---

## 檔案結構（本計畫建立/修改）

```
quantcore/presentation/web/
  __init__.py            建立（空）
  __main__.py            建立（uvicorn 進入點）
  templating.py          建立（Jinja2Templates + 路徑常數）
  controls.py            建立（Controls dataclass + parse_controls，純函數）
  cache.py               建立（(path, mtime) 讀檔快取）
  charts.py              建立（Plotly 深色 template + to_fragment）
  rendering.py           建立（render_page：整頁 vs HX 片段）
  app.py                 建立（create_app factory + index 轉址）
  routes/__init__.py     建立（空）
  routes/overview.py     建立（頁 1 總覽 + NAV 常數）
  routes/stubs.py        建立（其餘 8 頁佔位，計畫 2 取代）
  templates/base.html    建立（骨架）
  templates/_sidebar.html 建立
  templates/_controls.html 建立
  templates/overview.html 建立
  templates/overview_content.html 建立
  templates/stub_content.html 建立
  static/css/app.css     建立（深色 Bloomberg 主題）
  static/js/htmx.min.js  建立（vendored，Task 6）
  static/js/plotly.min.js 建立（vendored，Task 6）
  static/js/app.js       建立（少量膠水，Task 6）

pyproject.toml           修改（移除 streamlit、加 fastapi/uvicorn/jinja2/httpx）
quantcore/presentation/app.py       刪除（Streamlit 入口）
quantcore/presentation/controls.py  刪除（Streamlit 控制列）
quantcore/presentation/pages/       刪除（9 個 Streamlit 頁）
tests/test_presentation/test_app_smoke.py  刪除（AppTest 冒煙）
tests/test_presentation/test_controls.py   刪除（Streamlit controls 測試）

tests/test_presentation/test_web_controls.py  建立
tests/test_presentation/test_web_cache.py     建立
tests/test_presentation/test_web_charts.py    建立
tests/test_presentation/test_web_app.py       建立
tests/test_presentation/test_web_htmx.py      建立
```

`readers.py`、`tests/test_presentation/{conftest.py,test_readers.py,test_snapshot_readers.py,test_decision_explorer.py,test_architecture.py}` **不動**（`test_architecture.py` 的 `rglob` 已自動守護 `web/`）。

---

### Task 1: 依賴替換 + 退役 Streamlit 展示層

**Files:**
- Modify: `pyproject.toml`
- Delete: `quantcore/presentation/app.py`、`quantcore/presentation/controls.py`、`quantcore/presentation/pages/`（整個資料夾）、`tests/test_presentation/test_app_smoke.py`、`tests/test_presentation/test_controls.py`

- [ ] **Step 1: 確認沒有其他地方 import 待刪模組**

Run: `git grep -n "presentation.app\|presentation.controls\|presentation import app\|presentation import controls\|streamlit" -- quantcore tests`
Expected: 命中只落在待刪的 `presentation/app.py`、`presentation/controls.py`、`presentation/pages/*`、`test_app_smoke.py`、`test_controls.py`、以及 `pyproject.toml` 的 `streamlit` 依賴行。若有其他檔案命中，停下來回報。

- [ ] **Step 2: 改 `pyproject.toml` 依賴**

在 `[project].dependencies` 移除 `"streamlit>=1.59.1",`；新增下列三行（`plotly`/`scipy`/`pandas` 保留不動）：

```toml
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "jinja2>=3.1",
```

在 `[project.optional-dependencies].dev` 新增（`TestClient` 需要 httpx）：

```toml
    "httpx>=0.27",
```

- [ ] **Step 3: 刪除 Streamlit 展示層與其測試**

```bash
git rm quantcore/presentation/app.py quantcore/presentation/controls.py
git rm -r quantcore/presentation/pages
git rm tests/test_presentation/test_app_smoke.py tests/test_presentation/test_controls.py
```

- [ ] **Step 4: 同步環境並確認既有測試仍綠**

Run: `uv sync --extra dev && uv run pytest tests/test_presentation -q`
Expected: PASS（`test_readers.py`/`test_snapshot_readers.py`/`test_decision_explorer.py`/`test_architecture.py` 全綠；已無 streamlit 相關測試）。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "refactor(phase7): 退役 Streamlit 展示層、換上 FastAPI 依賴"
```

---

### Task 2: `web/controls.py` — 全域控制（query string → Controls，純函數）

**Files:**
- Create: `quantcore/presentation/web/__init__.py`（空檔）
- Create: `quantcore/presentation/web/controls.py`
- Test: `tests/test_presentation/test_web_controls.py`

- [ ] **Step 1: 寫失敗測試**

```python
from pathlib import Path

from quantcore.presentation.web.controls import parse_controls

_RUNS = [
    {"name": "vol_eval", "path": "/r/vol_eval", "strategies": []},
    {"name": "canonical_ewma", "path": "/r/canonical_ewma", "strategies": ["bh_spy", "full"]},
]


def test_default_picks_latest_backtest_run_not_vol_eval():
    c = parse_controls({}, Path("/r"), _RUNS)
    assert c.run == "canonical_ewma"
    assert c.run_dir == Path("/r/canonical_ewma")
    assert c.strategies == ["bh_spy", "full"]
    assert c.available_runs == ["vol_eval", "canonical_ewma"]


def test_explicit_run_honoured():
    c = parse_controls({"run": "vol_eval"}, Path("/r"), _RUNS)
    assert c.run == "vol_eval"
    assert c.strategies == []


def test_strat_csv_filtered_to_available():
    c = parse_controls({"strat": "full"}, Path("/r"), _RUNS)
    assert c.strategies == ["full"]


def test_bogus_strat_falls_back_to_all():
    c = parse_controls({"strat": "nope"}, Path("/r"), _RUNS)
    assert c.strategies == ["bh_spy", "full"]


def test_empty_runs_yields_none_run():
    c = parse_controls({}, Path("/r"), [])
    assert c.run is None
    assert c.run_dir is None
    assert c.available_runs == []


def test_query_suffix_roundtrips_selection():
    c = parse_controls({"run": "canonical_ewma", "strat": "full"}, Path("/r"), _RUNS)
    assert c.query_suffix == "?run=canonical_ewma&strat=full"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_presentation/test_web_controls.py -q`
Expected: FAIL（`ModuleNotFoundError: quantcore.presentation.web.controls`）

- [ ] **Step 3: 建 `web/__init__.py`（空）與 `web/controls.py`**

`quantcore/presentation/web/__init__.py`：空檔。

`quantcore/presentation/web/controls.py`：

```python
"""全域控制列狀態：query string → Controls（純函數，可獨立測）。

不 import 引擎（§2.2）。run 預設優先選有 strategies 的回測 run，比照舊
Streamlit controls 的 is_backtest_run 防呆——否則 nav 類頁面對缺 nav 的
vol_eval/ablation run 崩潰。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Controls:
    runs_root: Path
    run: str | None
    run_dir: Path | None
    strategies: list[str]
    available_runs: list[str]
    available_strategies: list[str]
    date_from: str | None
    date_to: str | None

    @property
    def query_suffix(self) -> str:
        parts: list[str] = []
        if self.run:
            parts.append(f"run={self.run}")
        if self.strategies:
            parts.append("strat=" + ",".join(self.strategies))
        if self.date_from:
            parts.append(f"from={self.date_from}")
        if self.date_to:
            parts.append(f"to={self.date_to}")
        return ("?" + "&".join(parts)) if parts else ""


def _resolve_run(requested: str | None, runs: list[dict]) -> dict | None:
    if not runs:
        return None
    by_name = {r["name"]: r for r in runs}
    if requested and requested in by_name:
        return by_name[requested]
    backtest = [r for r in runs if r.get("strategies")]
    return backtest[-1] if backtest else runs[-1]


def parse_controls(params: Mapping[str, str], runs_root: Path, runs: list[dict]) -> Controls:
    """由 query params + list_runs 結果組出 Controls。runs 為 readers.list_runs 輸出。"""
    names = [r["name"] for r in runs]
    chosen = _resolve_run(params.get("run"), runs)
    date_from = params.get("from") or None
    date_to = params.get("to") or None
    if chosen is None:
        return Controls(runs_root, None, None, [], names, [], date_from, date_to)
    available = list(chosen.get("strategies") or [])
    raw = params.get("strat")
    if raw:
        requested = [s for s in raw.split(",") if s]
        strategies = [s for s in requested if s in available] or available
    else:
        strategies = available
    return Controls(
        runs_root=runs_root,
        run=chosen["name"],
        run_dir=Path(chosen["path"]),
        strategies=strategies,
        available_runs=names,
        available_strategies=available,
        date_from=date_from,
        date_to=date_to,
    )
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_presentation/test_web_controls.py -q`
Expected: PASS（6 項）

- [ ] **Step 5: Commit**

```bash
git add quantcore/presentation/web/__init__.py quantcore/presentation/web/controls.py tests/test_presentation/test_web_controls.py
git commit -m "feat(phase7): web controls—query string 全域選擇（純函數）"
```

---

### Task 3: `web/cache.py` — (path, mtime) 讀檔快取

**Files:**
- Create: `quantcore/presentation/web/cache.py`
- Test: `tests/test_presentation/test_web_cache.py`

- [ ] **Step 1: 寫失敗測試**

```python
import os

from quantcore.presentation.web import cache


def test_read_caches_until_mtime_changes(tmp_path):
    cache.clear()
    p = tmp_path / "f.txt"
    p.write_text("1", encoding="utf-8")
    calls = {"n": 0}

    def loader(path):
        calls["n"] += 1
        return path.read_text(encoding="utf-8")

    assert cache.read(p, loader) == "1"
    assert cache.read(p, loader) == "1"
    assert calls["n"] == 1

    p.write_text("2", encoding="utf-8")
    st = p.stat()
    os.utime(p, (st.st_atime, st.st_mtime + 10))
    assert cache.read(p, loader) == "2"
    assert calls["n"] == 2
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_presentation/test_web_cache.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 建 `web/cache.py`**

```python
"""讀檔快取：以 (路徑, mtime) 為鍵包 readers。同路徑 mtime 變即失效重載。

localhost 單人、runs/ 為不可變產物，此快取避免切頁重讀 parquet。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")

_CACHE: dict[tuple[str, float], object] = {}


def read(path: Path, loader: Callable[[Path], T]) -> T:
    key = (str(path), path.stat().st_mtime)
    if key not in _CACHE:
        for stale in [k for k in _CACHE if k[0] == key[0]]:
            del _CACHE[stale]
        _CACHE[key] = loader(path)
    return _CACHE[key]  # type: ignore[return-value]


def clear() -> None:
    _CACHE.clear()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_presentation/test_web_cache.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/presentation/web/cache.py tests/test_presentation/test_web_cache.py
git commit -m "feat(phase7): web 讀檔快取（path+mtime 失效）"
```

---

### Task 4: `web/charts.py` — Plotly 深色 template + to_fragment

**Files:**
- Create: `quantcore/presentation/web/charts.py`
- Test: `tests/test_presentation/test_web_charts.py`

- [ ] **Step 1: 寫失敗測試**

```python
import plotly.graph_objects as go

from quantcore.presentation.web import charts


def test_style_dark_sets_black_bg():
    fig = go.Figure()
    charts.style_dark(fig)
    assert fig.layout.paper_bgcolor == "#000000"
    assert fig.layout.plot_bgcolor == "#000000"


def test_to_fragment_is_embeddable_div():
    fig = go.Figure(data=[go.Scatter(y=[1, 2, 3])])
    html = charts.to_fragment(fig, "chart-x")
    assert "chart-x" in html
    assert "<html" not in html.lower()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_presentation/test_web_charts.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 建 `web/charts.py`**

```python
"""Plotly 圖表：深色 Bloomberg 風統一樣式 + 可嵌入片段。

不 import 引擎（§2.2）。顏色 token 集中此處，供各頁圖表沿用。
"""

from __future__ import annotations

import plotly.graph_objects as go

BG = "#000000"
FG = "#d8d8d3"
GRID = "#1c1c1c"
AMBER = "#ff8c1a"
UP = "#26a65b"
DOWN = "#e0483e"
COLORWAY = ["#e8b64a", "#3a6ea5", "#26a65b", "#7a5aa5", "#ff8c1a", "#8a8a82"]


def style_dark(fig: go.Figure) -> go.Figure:
    """套用深色主題（黑底、細格線、等寬字、Bloomberg 色盤）。"""
    fig.update_layout(
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(color=FG, family="ui-monospace, Menlo, monospace", size=12),
        colorway=COLORWAY,
        margin=dict(l=48, r=16, t=24, b=32),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    return fig


def to_fragment(fig: go.Figure, div_id: str) -> str:
    """轉成可嵌入 HTML 片段（不含 plotly.js，不含 <html>）。plotly.js 由 base.html 一次載入。"""
    return fig.to_html(include_plotlyjs=False, full_html=False, div_id=div_id)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_presentation/test_web_charts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/presentation/web/charts.py tests/test_presentation/test_web_charts.py
git commit -m "feat(phase7): web charts—Plotly 深色 template + 可嵌入片段"
```

---

### Task 5: app factory + 骨架模板 + 深色 CSS + 總覽頁（真資料 KPI）

**Files:**
- Create: `quantcore/presentation/web/templating.py`
- Create: `quantcore/presentation/web/rendering.py`
- Create: `quantcore/presentation/web/app.py`
- Create: `quantcore/presentation/web/routes/__init__.py`（空）
- Create: `quantcore/presentation/web/routes/overview.py`
- Create: `quantcore/presentation/web/templates/base.html`
- Create: `quantcore/presentation/web/templates/_sidebar.html`
- Create: `quantcore/presentation/web/templates/_controls.html`
- Create: `quantcore/presentation/web/templates/overview.html`
- Create: `quantcore/presentation/web/templates/overview_content.html`
- Create: `quantcore/presentation/web/static/css/app.css`
- Test: `tests/test_presentation/test_web_app.py`

- [ ] **Step 1: 寫失敗測試**

```python
from fastapi.testclient import TestClient

from quantcore.presentation.web.app import create_app


def _client(runs_root):
    return TestClient(create_app(runs_root=runs_root))


def test_index_redirects_to_overview(runs_root):
    r = _client(runs_root).get("/", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"] == "/overview"


def test_overview_returns_200_with_run_data(runs_root):
    r = _client(runs_root).get("/overview")
    assert r.status_code == 200
    assert "總覽" in r.text
    assert "full" in r.text  # 合成 run 有 bh_spy/full 策略


def test_sidebar_lists_nine_pages(runs_root):
    r = _client(runs_root).get("/overview")
    for label in [
        "總覽", "決策解剖", "GARCH", "相關結構", "組合與成本",
        "消融", "資料品質", "回測工作台", "價格與交易",
    ]:
        assert label in r.text


def test_default_run_is_a_backtest_run(runs_root):
    r = _client(runs_root).get("/overview")
    assert r.status_code == 200
    assert "無回測 run" not in r.text
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_presentation/test_web_app.py -q`
Expected: FAIL（`ModuleNotFoundError: quantcore.presentation.web.app`）

- [ ] **Step 3: 建 templating / rendering / app / routes / 模板 / CSS**

`quantcore/presentation/web/templating.py`：

```python
"""Jinja2 模板引擎 + 路徑常數（單一來源）。"""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
```

`quantcore/presentation/web/rendering.py`：

```python
"""頁面渲染：整頁 vs HTMX 片段。HX-Request → 只回內容片段（不含骨架）。"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from quantcore.presentation.web.templating import templates

NAV = [
    ("/overview", "總覽"),
    ("/decisions", "決策解剖"),
    ("/garch", "GARCH"),
    ("/correlation", "相關結構"),
    ("/portfolio", "組合與成本"),
    ("/ablation", "消融"),
    ("/data-quality", "資料品質"),
    ("/run-lab", "回測工作台"),
    ("/price-trades", "價格與交易"),
]


def render_page(
    request: Request,
    *,
    active: str,
    full_template: str,
    content_template: str,
    context: dict,
) -> HTMLResponse:
    base_ctx = {"nav": NAV, "active": active, **context}
    is_hx = request.headers.get("HX-Request") == "true"
    name = content_template if is_hx else full_template
    return templates.TemplateResponse(request, name, base_ctx)
```

`quantcore/presentation/web/app.py`：

```python
"""FastAPI app factory。掛靜態檔、模板、路由。啟動回測只走 subprocess（Run Lab，7b）。

不 import 引擎（§2.2）——只 import readers 與 web 子模組。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from quantcore.presentation.web.routes import overview
from quantcore.presentation.web.templating import STATIC_DIR


def create_app(runs_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="QuantCore Dashboard")
    root = runs_root or Path(os.environ.get("QUANTCORE_RUNS_ROOT", "runs"))
    app.state.runs_root = Path(root)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(overview.router)

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse("/overview")

    return app


app = create_app()
```

`quantcore/presentation/web/routes/__init__.py`：空檔。

`quantcore/presentation/web/routes/overview.py`：

```python
"""頁 1 總覽：KPI 卡片（本計畫只做卡片；NAV/回撤/曝險圖屬計畫 2）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, controls
from quantcore.presentation.web.rendering import render_page

router = APIRouter()


def controls_for(request: Request) -> controls.Controls:
    root = request.app.state.runs_root
    runs = cache.read(root, readers.list_runs) if root.exists() else []
    return controls.parse_controls(request.query_params, root, runs)


@router.get("/overview", response_class=HTMLResponse)
def overview(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    metrics_by_strategy: dict[str, dict] = {}
    if ctrl.run_dir is not None and (ctrl.run_dir / "metrics.json").exists():
        all_metrics = cache.read(
            ctrl.run_dir / "metrics.json", lambda p: readers.load_metrics(p.parent)
        )
        for sid in ctrl.strategies:
            m = all_metrics.get(sid, {})
            metrics_by_strategy[sid] = {
                k: v for k, v in m.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
    return render_page(
        request,
        active="/overview",
        full_template="overview.html",
        content_template="overview_content.html",
        context={"ctrl": ctrl, "metrics_by_strategy": metrics_by_strategy},
    )
```

`quantcore/presentation/web/templates/base.html`：

```html
<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QuantCore Dashboard</title>
<link rel="stylesheet" href="/static/css/app.css">
</head>
<body>
<div class="app">
  {% include "_sidebar.html" %}
  <div class="main">
    {% include "_controls.html" %}
    <div id="content" class="content">
      {% block content %}{% endblock %}
    </div>
  </div>
</div>
</body>
</html>
```

`quantcore/presentation/web/templates/_sidebar.html`：

```html
<nav class="sidebar">
  <div class="brand">QuantCore</div>
  {% for href, label in nav %}
  <a class="nav-item {% if href == active %}active{% endif %}" href="{{ href }}{{ ctrl.query_suffix }}">{{ label }}</a>
  {% endfor %}
</nav>
```

`quantcore/presentation/web/templates/_controls.html`：

```html
<header class="controls">
  <form method="get" class="control-form">
    <label class="ctl">RUN
      <select name="run" onchange="this.form.submit()">
        {% for r in ctrl.available_runs %}
        <option value="{{ r }}" {% if r == ctrl.run %}selected{% endif %}>{{ r }}</option>
        {% endfor %}
      </select>
    </label>
  </form>
  <span class="spacer"></span>
  <span class="ident">{{ ctrl.run or "—" }}</span>
</header>
```

`quantcore/presentation/web/templates/overview.html`：

```html
{% extends "base.html" %}
{% block content %}{% include "overview_content.html" %}{% endblock %}
```

`quantcore/presentation/web/templates/overview_content.html`：

```html
<h1 class="page-title">總覽</h1>
{% if ctrl.run is none %}
<p class="empty">runs/ 下無回測 run。</p>
{% else %}
{% for sid, metrics in metrics_by_strategy.items() %}
<section class="strat-block">
  <h2 class="strat-name">{{ sid }}</h2>
  <div class="kpi-grid">
    {% for key, val in metrics.items() %}
    <div class="kpi-card">
      <div class="kpi-label">{{ key }}</div>
      <div class="kpi-value">{{ "%.4g"|format(val) }}</div>
    </div>
    {% endfor %}
  </div>
</section>
{% endfor %}
{% endif %}
```

`quantcore/presentation/web/static/css/app.css`：

```css
:root {
  --bg: #000; --panel: #0a0a0a; --panel-2: #121212;
  --border: #2a2a2a; --border-soft: #1f1f1f;
  --fg: #d8d8d3; --fg-dim: #8a8a82; --fg-faint: #5a5a52;
  --amber: #ff8c1a; --up: #26a65b; --down: #e0483e; --blue: #3a6ea5;
  --mono: ui-monospace, "SF Mono", Menlo, monospace;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font-family: var(--mono); font-size: 13px; }
.app { display: grid; grid-template-columns: 176px 1fr; min-height: 100vh; }
.sidebar { background: var(--panel); border-right: 1px solid var(--border); padding: 12px 8px; display: flex; flex-direction: column; gap: 2px; }
.brand { color: var(--amber); font-weight: 500; letter-spacing: 0.5px; padding: 4px 10px 14px; }
.nav-item { color: var(--fg-dim); text-decoration: none; padding: 7px 10px; border-radius: 4px; }
.nav-item:hover { color: var(--fg); background: var(--panel-2); }
.nav-item.active { color: var(--amber); background: #141008; border-left: 2px solid var(--amber); }
.main { display: flex; flex-direction: column; min-width: 0; }
.controls { display: flex; align-items: center; gap: 12px; padding: 8px 16px; background: var(--panel); border-bottom: 1px solid var(--border); }
.controls .ctl { color: var(--fg-dim); font-size: 11px; }
.controls select { background: var(--panel-2); color: var(--fg); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px; font-family: var(--mono); margin-left: 6px; }
.controls .spacer { flex: 1; }
.controls .ident { color: var(--fg-faint); font-size: 11px; }
.content { padding: 16px; min-width: 0; }
.page-title { font-size: 16px; font-weight: 500; margin: 0 0 12px; }
.empty { color: var(--fg-dim); }
.strat-block { margin-bottom: 18px; }
.strat-name { font-size: 13px; color: var(--amber); margin: 0 0 8px; }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
.kpi-card { background: var(--panel); border: 1px solid var(--border-soft); border-radius: 8px; padding: 10px 12px; }
.kpi-label { color: var(--fg-dim); font-size: 11px; }
.kpi-value { font-size: 20px; font-weight: 500; margin-top: 2px; }
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_presentation/test_web_app.py -q`
Expected: PASS（4 項）

- [ ] **Step 5: Commit**

```bash
git add quantcore/presentation/web tests/test_presentation/test_web_app.py
git commit -m "feat(phase7): FastAPI app 骨架 + 深色主題 + 總覽頁 KPI（真資料）"
```

---

### Task 6: 導覽 HTMX 局部換頁 + 其餘 8 頁 stub + vendored JS

**Files:**
- Create: `quantcore/presentation/web/routes/stubs.py`
- Create: `quantcore/presentation/web/templates/stub_content.html`
- Create: `quantcore/presentation/web/static/js/app.js`
- Create（vendored）: `quantcore/presentation/web/static/js/plotly.min.js`、`quantcore/presentation/web/static/js/htmx.min.js`
- Modify: `quantcore/presentation/web/app.py`（include stubs router）
- Modify: `quantcore/presentation/web/templates/base.html`（加 JS script 標籤）
- Modify: `quantcore/presentation/web/templates/_sidebar.html`（nav 加 hx-get）
- Test: `tests/test_presentation/test_web_htmx.py`

- [ ] **Step 1: 寫失敗測試**

```python
from fastapi.testclient import TestClient

from quantcore.presentation.web.app import create_app


def _client(runs_root):
    return TestClient(create_app(runs_root=runs_root))


def test_hx_request_returns_content_only(runs_root):
    r = _client(runs_root).get("/overview", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "總覽" in r.text
    assert '<nav class="sidebar"' not in r.text  # 片段不含骨架
    assert "<!doctype html>" not in r.text.lower()


def test_full_request_includes_shell(runs_root):
    r = _client(runs_root).get("/overview")
    assert '<nav class="sidebar"' in r.text


def test_stub_pages_reachable(runs_root):
    client = _client(runs_root)
    for path in ["/decisions", "/garch", "/correlation", "/portfolio",
                 "/ablation", "/data-quality", "/run-lab", "/price-trades"]:
        r = client.get(path)
        assert r.status_code == 200
        assert "建置中" in r.text


def test_stub_hx_fragment_excludes_shell(runs_root):
    r = _client(runs_root).get("/garch", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert '<nav class="sidebar"' not in r.text
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_presentation/test_web_htmx.py -q`
Expected: FAIL（stub 路由不存在 → 404）

- [ ] **Step 3: 建 stub 路由與模板、加 JS、接 HTMX**

`quantcore/presentation/web/templates/stub_content.html`：

```html
<h1 class="page-title">{{ title }}</h1>
<p class="empty">建置中（計畫 2 提供）。</p>
```

`quantcore/presentation/web/routes/stubs.py`：

```python
"""其餘 8 頁佔位。計畫 2 逐頁以真實內容取代。共用 render_page → HTMX 片段自動生效。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation.web import cache, controls
from quantcore.presentation.web.rendering import render_page

router = APIRouter()

_STUBS = [
    ("/decisions", "決策解剖"),
    ("/garch", "GARCH"),
    ("/correlation", "相關結構"),
    ("/portfolio", "組合與成本"),
    ("/ablation", "消融"),
    ("/data-quality", "資料品質"),
    ("/run-lab", "回測工作台"),
    ("/price-trades", "價格與交易"),
]


def _controls(request: Request) -> controls.Controls:
    from quantcore.presentation import readers

    root = request.app.state.runs_root
    runs = cache.read(root, readers.list_runs) if root.exists() else []
    return controls.parse_controls(request.query_params, root, runs)


def _make(path: str, title: str):
    def handler(request: Request) -> HTMLResponse:
        return render_page(
            request,
            active=path,
            full_template="stub.html",
            content_template="stub_content.html",
            context={"ctrl": _controls(request), "title": title},
        )

    return handler


for _path, _title in _STUBS:
    router.add_api_route(_path, _make(_path, _title), methods=["GET"], response_class=HTMLResponse)
```

新增 `quantcore/presentation/web/templates/stub.html`：

```html
{% extends "base.html" %}
{% block content %}{% include "stub_content.html" %}{% endblock %}
```

`quantcore/presentation/web/static/js/app.js`：

```javascript
if (window.htmx) {
  htmx.config.defaultSwapStyle = "innerHTML";
}
```

修改 `quantcore/presentation/web/app.py`：在 import 區加 `from quantcore.presentation.web.routes import overview, stubs`，並在 `create_app` 內 `app.include_router(overview.router)` 之後加 `app.include_router(stubs.router)`。

修改 `quantcore/presentation/web/templates/base.html`：在 `</head>` 前加：

```html
<script src="/static/js/htmx.min.js" defer></script>
<script src="/static/js/plotly.min.js"></script>
<script src="/static/js/app.js" defer></script>
```

修改 `quantcore/presentation/web/templates/_sidebar.html` 的 nav 連結，改為（保留 href 供無 JS 降級，加 HTMX 局部換頁）：

```html
  <a class="nav-item {% if href == active %}active{% endif %}"
     href="{{ href }}{{ ctrl.query_suffix }}"
     hx-get="{{ href }}{{ ctrl.query_suffix }}" hx-target="#content" hx-push-url="true">{{ label }}</a>
```

- [ ] **Step 4: Vendored JS（離線產生，不依賴外網資料）**

plotly.js 由已安裝的 plotly 套件離線輸出：

Run: `uv run python -c "import plotly, pathlib; pathlib.Path('quantcore/presentation/web/static/js/plotly.min.js').write_text(plotly.offline.get_plotlyjs(), encoding='utf-8')"`
Expected: 產生 `plotly.min.js`（數 MB）。

htmx.js 由 CDN 取一次 vendored（開發機一次性下載，非執行期資料）：

Run: `curl -L -o quantcore/presentation/web/static/js/htmx.min.js https://cdnjs.cloudflare.com/ajax/libs/htmx/2.0.3/htmx.min.js`
Expected: 產生 `htmx.min.js`（~50KB）。若開發機無網路，暫以 `<script src="https://cdnjs.cloudflare.com/ajax/libs/htmx/2.0.3/htmx.min.js"></script>` 替代並記 backlog。

- [ ] **Step 5: 跑測試確認通過**

Run: `uv run pytest tests/test_presentation/test_web_htmx.py -q`
Expected: PASS（4 項）

- [ ] **Step 6: Commit**

```bash
git add quantcore/presentation/web tests/test_presentation/test_web_htmx.py
git commit -m "feat(phase7): HTMX 局部換頁 + 8 頁 stub + vendored htmx/plotly"
```

---

### Task 7: 進入點 + 文件更新 + 全套綠燈

**Files:**
- Create: `quantcore/presentation/web/__main__.py`
- Modify: `README.md`（若有舊 `streamlit run` 指令）、`PROGRESS.md`（Phase 7 變更紀錄一行）

- [ ] **Step 1: 建 `web/__main__.py`**

```python
"""localhost 啟動：uv run python -m quantcore.presentation.web"""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("quantcore.presentation.web.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 更新文件中的啟動指令**

Run: `git grep -n "streamlit run" -- README.md PROGRESS.md docs`
Expected: 列出所有舊指令位置。將每處 `uv run streamlit run quantcore/presentation/app.py` 改為 `uv run python -m quantcore.presentation.web`（若某處是歷史紀錄語句則保留原文、不改寫過去）。於 `PROGRESS.md` 的「變更紀錄」加一行：

```markdown
- 2026-07-31：**Phase 7 展示層重製（計畫 1 Web 地基）**——退役 Streamlit，改 FastAPI + Jinja2 + HTMX + Plotly；深色 Bloomberg 骨架（左導覽 + query-string 控制列）+ 總覽頁 KPI（真資料）+ 8 頁 stub；`readers.py`/引擎/快照不動，AST 行程邊界守護自動涵蓋新 `web/`。啟動改 `uv run python -m quantcore.presentation.web`。計畫 2 做九頁唯讀（含價格與交易旗艦頁）。
```

- [ ] **Step 3: 全套測試 + lint 綠燈**

Run: `uv run pytest -q && uv run ruff check quantcore tests && uv run ruff format --check quantcore tests`
Expected: 全綠、ruff 乾淨。若 `ruff format --check` 有意見，跑 `uv run ruff format quantcore tests` 後重驗。

- [ ] **Step 4: 人工冒煙（可選但建議）**

Run: `uv run python -m quantcore.presentation.web`
於瀏覽器開 `http://127.0.0.1:8000`：確認深色骨架、左導覽 9 項、總覽頁 KPI 卡片顯示、點其他頁顯示「建置中」、換 run 下拉可切換。Ctrl-C 結束。

- [ ] **Step 5: Commit**

```bash
git add quantcore/presentation/web/__main__.py README.md PROGRESS.md
git commit -m "chore(phase7): web 進入點 + 文件啟動指令更新（計畫 1 完成）"
```

---

## Self-Review 對照

- **Spec 覆蓋（§10 計畫 1）**：依賴替換 + 退役 Streamlit（Task 1）✓、`app.py` factory（Task 5）✓、`base.html` 骨架左導覽 + 控制列（Task 5）✓、`app.css` 深色 Bloomberg（Task 5）✓、`controls.py` query 解析（Task 2）✓、`cache.py`（Task 3）✓、`charts.py` Plotly 深色 template（Task 4）✓、AST 架構守護涵蓋 `web/`（既有 `rglob` 自動涵蓋，`test_architecture.py` 不改；全套於 Task 7 驗）✓、vendored htmx/plotly（Task 6）✓、`TestClient` 冒煙（Task 5/6）✓。
- **邊界**：全 `web/` 只 import `readers` 與 `fastapi`/`jinja2`/`plotly`/stdlib，無引擎 import——由 `test_architecture.py` 於 Task 1/7 全套執行時把關。
- **狀態模型**：query string（§2.4）由 `controls.query_suffix` 貫穿導覽（Task 2/5/6）。
- **無 placeholder**：各 Task 均附完整程式碼與確切指令。
- **型別一致**：`Controls`（欄位 + `query_suffix`）、`parse_controls(params, runs_root, runs)`、`render_page(request, *, active, full_template, content_template, context)`、`cache.read(path, loader)`、`charts.style_dark/to_fragment`、`NAV`（`rendering.py` 單一來源）跨 Task 一致。
- **延後**：頁 1 的 NAV/回撤/曝險圖與頁 2–7、9 內容、旗艦頁 9 四元件 → 計畫 2；Run Lab（頁 8 真功能）→ 7b。
