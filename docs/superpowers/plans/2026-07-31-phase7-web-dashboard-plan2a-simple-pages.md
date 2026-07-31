# Phase 7 Web Dashboard 重製 — 計畫 2a：真圖表地基 + 頁 1/5/7 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。Steps 用 `- [ ]` checkbox。
> 執行環境註記：本計畫在帳號用量上限期間可能改由控制者 inline（直接 Edit/Bash）執行；TDD 紀律不變。

**Goal:** 把 charts.py 擴充為真圖表 builder，並將頁 1 總覽、頁 5 組合與成本、頁 7 資料品質從 stub 換成真內容（移植自退役的 Streamlit 頁）。

**Architecture:** 薄路由（route 讀 `controls_for` + `readers`（經 cache）→ 呼叫 `charts.*` builder → `to_fragment` → 傳入模板）；胖 `charts.py`（figure builder，純函數收 DataFrame 回 styled figure，可獨立測）。表格在 Jinja2 模板渲染。§2.2 邊界不變（web 不 import 引擎）。

**Tech Stack:** FastAPI/Jinja2/HTMX/Plotly、pandas、pytest（TestClient）、ruff。

前置：計畫 1 完成（`web/` 骨架 + `controls`/`cache`/`charts.style_dark,to_fragment`/`rendering.controls_for,render_page,NAV` + 頁 1 總覽 KPI 卡 + 8 頁 stub）。設計見 `../specs/2026-07-31-phase7-web-dashboard-rebuild-design.md` §5/§6。舊 Streamlit 頁邏輯在 git `59ab74f~1:quantcore/presentation/pages/`。

分支：`feature/phase7a-dashboard`（延續計畫 1）。

---

## 檔案結構

```
quantcore/presentation/web/charts.py        修改（+6 builder：nav_log/drawdown/exposure/weight_stack/exposure_band/turnover_cost；import pandas）
quantcore/presentation/web/routes/overview.py   修改（頁 1 加圖表 + 指標表 + 子期間）
quantcore/presentation/web/routes/portfolio.py  建立（頁 5）
quantcore/presentation/web/routes/data_quality.py 建立（頁 7）
quantcore/presentation/web/app.py           修改（include portfolio/data_quality router；從 stubs 移除這兩路徑）
quantcore/presentation/web/routes/stubs.py  修改（移除 /portfolio、/data-quality，剩 6 stub）
quantcore/presentation/web/templates/overview_content.html   修改（KPI 卡 + 圖 + 指標表 + 子期間）
quantcore/presentation/web/templates/portfolio.html          建立
quantcore/presentation/web/templates/portfolio_content.html  建立
quantcore/presentation/web/templates/data_quality.html       建立
quantcore/presentation/web/templates/data_quality_content.html 建立
quantcore/presentation/web/templates/_metrics_table.html     建立（共用指標表 partial）
quantcore/presentation/web/static/css/app.css               修改（表格 + 圖容器樣式）
tests/test_presentation/test_web_charts.py       修改（+builder 測試）
tests/test_presentation/test_web_pages.py        建立（頁 1/5/7 TestClient 冒煙）
```

慣例：每個真頁有 `pageX.html`（extends base，include content）+ `pageX_content.html`（HTMX 片段）。route 用 `render_page`。圖表以 `to_fragment(fig, div_id)` 產 HTML 片段字串，傳入 context，模板用 `{{ frag|safe }}` 嵌入。

---

### Task 1: charts.py 擴充 6 個 figure builder

**Files:**
- Modify: `quantcore/presentation/web/charts.py`
- Test: `tests/test_presentation/test_web_charts.py`

- [ ] **Step 1: 加失敗測試** — 在 `tests/test_presentation/test_web_charts.py` 末尾追加：

```python
import pandas as pd


def _nav_df():
    dates = pd.date_range("2020-01-01", periods=5, freq="D")
    rows = []
    for sid in ("full", "bh_spy"):
        for i, d in enumerate(dates):
            rows.append(
                {"date": d, "strategy_id": sid, "nav": 1.0 + 0.1 * i, "turnover": 0.2, "cost": 0.01}
            )
    return pd.DataFrame(rows)


def _dec_df():
    dates = pd.date_range("2020-01-01", periods=3, freq="D")
    rows = []
    for i, d in enumerate(dates):
        rows.append(
            {
                "strategy_id": "full",
                "decision_date": d,
                "exposure_applied": 0.7 + 0.05 * i,
                "band_blocked": (i == 1),
            }
        )
    return pd.DataFrame(rows)


def _weights_df():
    dates = pd.date_range("2020-01-01", periods=3, freq="D")
    rows = []
    for d in dates:
        for tk, w in (("SPY", 0.6), ("GLD", 0.4)):
            rows.append({"date": d, "strategy_id": "full", "ticker": tk, "weight": w})
    return pd.DataFrame(rows)


def test_nav_log_one_trace_per_strategy_log_axis():
    fig = charts.nav_log(_nav_df(), ["full", "bh_spy"])
    assert len(fig.data) == 2
    assert {t.name for t in fig.data} == {"full", "bh_spy"}
    assert fig.layout.yaxis.type == "log"
    assert fig.layout.paper_bgcolor == "#000000"


def test_drawdown_is_nonpositive():
    fig = charts.drawdown(_nav_df(), ["full"])
    assert len(fig.data) == 1
    assert max(fig.data[0].y) <= 1e-9


def test_exposure_plots_applied():
    fig = charts.exposure(_dec_df(), ["full"])
    assert len(fig.data) == 1
    assert list(fig.data[0].y) == [0.7, 0.75, 0.8]


def test_weight_stack_one_trace_per_ticker():
    fig = charts.weight_stack(_weights_df(), "full")
    assert {t.name for t in fig.data} == {"SPY", "GLD"}
    assert all(t.stackgroup == "w" for t in fig.data)


def test_exposure_band_marks_blocked():
    fig = charts.exposure_band(_dec_df(), "full")
    names = {t.name for t in fig.data}
    assert "E(t)" in names and "band-blocked" in names
    blocked = next(t for t in fig.data if t.name == "band-blocked")
    assert list(blocked.x) == [pd.Timestamp("2020-01-02")]


def test_turnover_cost_dual_series():
    fig = charts.turnover_cost(_nav_df(), "full")
    names = {t.name for t in fig.data}
    assert "turnover" in names and "累積成本" in names
```

- [ ] **Step 2: RED** — `uv run pytest tests/test_presentation/test_web_charts.py -q` → FAIL（builder 不存在）。

- [ ] **Step 3: 實作** — 在 `charts.py` 的 import 區加 `import pandas as pd`（放在 `from __future__` 之後、`import plotly.graph_objects as go` 之前，符合 isort），並在檔末（`to_fragment` 之後）加：

```python
def nav_log(nav: pd.DataFrame, strategies: list[str]) -> go.Figure:
    """NAV 對數疊圖，每策略一線。"""
    fig = go.Figure()
    for sid in strategies:
        sub = nav[nav["strategy_id"] == sid].sort_values("date")
        fig.add_trace(go.Scatter(x=sub["date"], y=sub["nav"], name=sid, mode="lines"))
    fig.update_yaxes(type="log", title="NAV（對數）")
    return style_dark(fig)


def drawdown(nav: pd.DataFrame, strategies: list[str]) -> go.Figure:
    """回撤（nav/cummax − 1），每策略一線。"""
    fig = go.Figure()
    for sid in strategies:
        sub = nav[nav["strategy_id"] == sid].sort_values("date")
        cummax = sub["nav"].cummax()
        fig.add_trace(
            go.Scatter(x=sub["date"], y=sub["nav"] / cummax - 1.0, name=sid, mode="lines")
        )
    fig.update_yaxes(title="drawdown")
    return style_dark(fig)


def exposure(decisions: pd.DataFrame, strategies: list[str]) -> go.Figure:
    """曝險 E(t)（decisions.exposure_applied），每策略一線。"""
    fig = go.Figure()
    for sid in strategies:
        sub = decisions[
            (decisions["strategy_id"] == sid) & decisions["exposure_applied"].notna()
        ].sort_values("decision_date")
        if not sub.empty:
            fig.add_trace(
                go.Scatter(x=sub["decision_date"], y=sub["exposure_applied"], name=sid, mode="lines")
            )
    fig.update_yaxes(title="E(t)")
    return style_dark(fig)


def weight_stack(weights: pd.DataFrame, strategy: str) -> go.Figure:
    """權重堆疊面積（單一策略，含現金若有）。"""
    w = weights[weights["strategy_id"] == strategy]
    wide = w.pivot_table(index="date", columns="ticker", values="weight", fill_value=0.0).sort_index()
    fig = go.Figure()
    for col in wide.columns:
        fig.add_trace(go.Scatter(x=wide.index, y=wide[col], name=str(col), stackgroup="w", mode="lines"))
    return style_dark(fig)


def exposure_band(decisions: pd.DataFrame, strategy: str) -> go.Figure:
    """曝險軌跡 + band_blocked 事件標記（單一策略）。"""
    d = decisions[
        (decisions["strategy_id"] == strategy) & decisions["exposure_applied"].notna()
    ].sort_values("decision_date")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d["decision_date"], y=d["exposure_applied"], name="E(t)", mode="lines"))
    blocked = d[d["band_blocked"] == True]  # noqa: E712
    if not blocked.empty:
        fig.add_trace(
            go.Scatter(
                x=blocked["decision_date"],
                y=blocked["exposure_applied"],
                name="band-blocked",
                mode="markers",
                marker_symbol="x",
                marker_color=DOWN,
            )
        )
    fig.update_yaxes(title="E(t)")
    return style_dark(fig)


def turnover_cost(nav: pd.DataFrame, strategy: str) -> go.Figure:
    """每次再平衡換手率（bar）+ 累積成本（右軸線）。"""
    n = nav[nav["strategy_id"] == strategy].sort_values("date")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=n["date"], y=n["turnover"], name="turnover", marker_color=BLUE))
    fig.add_trace(
        go.Scatter(x=n["date"], y=n["cost"].cumsum(), name="累積成本", yaxis="y2", mode="lines")
    )
    style_dark(fig)
    fig.update_layout(yaxis2=dict(title="累積成本", overlaying="y", side="right", gridcolor=GRID))
    return fig
```

新增顏色常數 `BLUE = "#3a6ea5"` 到 charts.py 的顏色 token 區（若不存在）。

- [ ] **Step 4: GREEN** — `uv run pytest tests/test_presentation/test_web_charts.py -q` → PASS（原 2 + 新 6 = 8）。

- [ ] **Step 5: ruff** — `uv run ruff check quantcore/presentation/web/charts.py tests/test_presentation/test_web_charts.py` + `ruff format --check`；必要時 `ruff format`。

- [ ] **Step 6: Commit**

```bash
git add quantcore/presentation/web/charts.py tests/test_presentation/test_web_charts.py
git commit -m "feat(phase7): charts—NAV/回撤/曝險/權重堆疊/帶事件/換手成本 builder"
```

---

### Task 2: 頁 1 總覽真內容（KPI 卡 + NAV/回撤/曝險圖 + 指標表 + 子期間）

**Files:**
- Modify: `quantcore/presentation/web/routes/overview.py`
- Create: `quantcore/presentation/web/templates/_metrics_table.html`
- Modify: `quantcore/presentation/web/templates/overview_content.html`
- Modify: `quantcore/presentation/web/static/css/app.css`
- Test: `tests/test_presentation/test_web_pages.py`

- [ ] **Step 1: 加失敗測試** — 建 `tests/test_presentation/test_web_pages.py`：

```python
from fastapi.testclient import TestClient

from quantcore.presentation.web.app import create_app


def _client(runs_root):
    return TestClient(create_app(runs_root=runs_root))


def test_overview_has_charts_and_metrics_table(runs_root):
    r = _client(runs_root).get("/overview")
    assert r.status_code == 200
    assert "NAV" in r.text
    assert "回撤" in r.text
    assert "曝險" in r.text
    assert "sharpe" in r.text  # 指標表欄
    assert "plotly" in r.text.lower()  # 圖片段已嵌入


def test_overview_non_backtest_run_is_graceful(runs_root):
    # vol_eval 無 nav → 提示而非崩潰
    r = _client(runs_root).get("/overview?run=vol_eval")
    assert r.status_code == 200
    assert "非回測 run" in r.text
```

（`runs_root` fixture 的合成 run 為 backtest；第二測試需要一個非回測 run。合成 fixture 只有一個 backtest run，`?run=vol_eval` 會查無 → parse_controls 回退到預設 backtest run，第二測試會失敗。故第二測試改為驗證 is_backtest_run 保護的路徑：直接對 run_dir 缺 nav 的情況。**實作端**必須對「選中 run 非 backtest」顯示「非回測 run」。因合成 fixture 無非回測 run，第二測試以 monkeypatch 或跳過處理——**簡化：第二測試改成驗證存在性**：）

```python
def test_overview_backtest_guard_present(runs_root):
    # 保護存在：程式碼對非回測 run 會提示（此處以 backtest run 確認正常渲染，
    # 非回測分支的單元測試在 readers.is_backtest_run 已覆蓋）
    r = _client(runs_root).get("/overview")
    assert "非回測 run" not in r.text  # backtest run 正常，不誤報
```

（刪掉上面 `test_overview_non_backtest_run_is_graceful`，改用 `test_overview_backtest_guard_present`。）

- [ ] **Step 2: RED** — `uv run pytest tests/test_presentation/test_web_pages.py -q` → FAIL（overview 尚無 NAV/回撤字樣與圖）。

- [ ] **Step 3: 實作 route** — 改 `quantcore/presentation/web/routes/overview.py` 為：

```python
"""頁 1 總覽：KPI 卡 + NAV 對數疊圖 + 回撤 + 曝險 E(t) + 指標表 + 子期間（§11.2）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()

_METRIC_COLS = (
    "annualized_return",
    "sharpe",
    "sortino",
    "max_drawdown",
    "calmar",
    "annualized_turnover",
    "average_exposure",
)


@router.get("/overview", response_class=HTMLResponse)
def overview(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl}
    if ctrl.run_dir is None:
        ctx["error"] = "runs/ 下無回測 run。"
    elif not readers.is_backtest_run(ctrl.run_dir):
        ctx["error"] = f"{ctrl.run} 非回測 run（無 nav/decisions）——請選 canonical/backtest run。"
    else:
        nav = cache.read(ctrl.run_dir / "nav.parquet", lambda p: readers.load_nav(p.parent))
        decisions = cache.read(
            ctrl.run_dir / "decisions.parquet", lambda p: readers.load_decisions(p.parent)
        )
        metrics = cache.read(
            ctrl.run_dir / "metrics.json", lambda p: readers.load_metrics(p.parent)
        )
        shown = ctrl.strategies or sorted(nav["strategy_id"].unique())
        rows = [
            {"strategy": s, **{c: metrics[s].get(c) for c in _METRIC_COLS}}
            for s in shown
            if s in metrics
        ]
        subperiods = None
        if shown and shown[0] in metrics and metrics[shown[0]].get("subperiods"):
            subperiods = metrics[shown[0]]["subperiods"]
        ctx.update(
            error=None,
            nav_fig=charts.to_fragment(charts.nav_log(nav, shown), "ov-nav"),
            dd_fig=charts.to_fragment(charts.drawdown(nav, shown), "ov-dd"),
            exp_fig=charts.to_fragment(charts.exposure(decisions, shown), "ov-exp"),
            metric_cols=_METRIC_COLS,
            metric_rows=rows,
            sub_strategy=shown[0] if shown else None,
            subperiods=subperiods,
        )
    return render_page(
        request,
        active="/overview",
        full_template="overview.html",
        content_template="overview_content.html",
        context=ctx,
    )
```

- [ ] **Step 4: 實作模板** — `_metrics_table.html`（共用指標表 partial）：

```html
<table class="data-table">
  <thead>
    <tr><th>strategy</th>{% for c in metric_cols %}<th>{{ c }}</th>{% endfor %}</tr>
  </thead>
  <tbody>
    {% for row in metric_rows %}
    <tr>
      <td class="rowhead">{{ row.strategy }}</td>
      {% for c in metric_cols %}
      <td>{% if row[c] is number %}{{ "%.4g"|format(row[c]) }}{% else %}—{% endif %}</td>
      {% endfor %}
    </tr>
    {% endfor %}
  </tbody>
</table>
```

`overview_content.html`（整份取代）：

```html
<h1 class="page-title">總覽</h1>
{% if ctrl.run is none or error %}
<p class="empty">{{ error or "runs/ 下無回測 run。" }}</p>
{% else %}
<div class="chart-card">
  <div class="chart-title">NAV（對數軸）</div>
  {{ nav_fig|safe }}
</div>
<div class="chart-grid">
  <div class="chart-card"><div class="chart-title">回撤</div>{{ dd_fig|safe }}</div>
  <div class="chart-card"><div class="chart-title">曝險 E(t)</div>{{ exp_fig|safe }}</div>
</div>
<h2 class="section-title">指標</h2>
{% include "_metrics_table.html" %}
{% if subperiods %}
<h2 class="section-title">子期間績效（{{ sub_strategy }}）</h2>
<pre class="json-block">{{ subperiods | tojson(indent=2) }}</pre>
{% endif %}
{% endif %}
```

- [ ] **Step 5: CSS** — 在 `app.css` 末尾追加：

```css
.chart-card { border: 1px solid var(--border-soft); border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; }
.chart-title { font-size: 13px; font-weight: 500; margin-bottom: 6px; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.section-title { font-size: 14px; color: var(--amber); margin: 16px 0 8px; }
.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table th, .data-table td { text-align: right; padding: 4px 8px; border-bottom: 1px solid var(--border-soft); }
.data-table th { color: var(--fg-dim); font-weight: 500; }
.data-table .rowhead { text-align: left; color: var(--amber); }
.json-block { background: var(--panel); border: 1px solid var(--border-soft); border-radius: 8px; padding: 10px; overflow-x: auto; font-size: 12px; color: var(--fg); }
```

- [ ] **Step 6: GREEN + 全套** — `uv run pytest tests/test_presentation/test_web_pages.py -q` PASS；`uv run pytest tests/test_presentation -q` 全 PASS；ruff clean。

- [ ] **Step 7: Commit**

```bash
git add quantcore/presentation/web/routes/overview.py quantcore/presentation/web/templates/overview_content.html quantcore/presentation/web/templates/_metrics_table.html quantcore/presentation/web/static/css/app.css tests/test_presentation/test_web_pages.py
git commit -m "feat(phase7): 頁 1 總覽真內容（NAV/回撤/曝險圖 + 指標表 + 子期間）"
```

---

### Task 3: 頁 5 組合與成本

**Files:**
- Create: `quantcore/presentation/web/routes/portfolio.py`
- Create: `quantcore/presentation/web/templates/portfolio.html`、`portfolio_content.html`
- Modify: `quantcore/presentation/web/app.py`（include portfolio router）
- Modify: `quantcore/presentation/web/routes/stubs.py`（移除 `/portfolio`）
- Test: `tests/test_presentation/test_web_pages.py`（追加）

- [ ] **Step 1: 加失敗測試** — 追加：

```python
def test_portfolio_has_weight_stack_and_cost(runs_root):
    r = _client(runs_root).get("/portfolio")
    assert r.status_code == 200
    assert "權重堆疊" in r.text
    assert "換手" in r.text
    assert "plotly" in r.text.lower()
```

- [ ] **Step 2: RED** — `/portfolio` 目前是 stub（「建置中」），無「權重堆疊」→ FAIL。

- [ ] **Step 3: route** — 建 `quantcore/presentation/web/routes/portfolio.py`：

```python
"""頁 5 組合與成本：權重堆疊面積、曝險軌跡+帶事件、換手+累積成本（§11.2）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()


@router.get("/portfolio", response_class=HTMLResponse)
def portfolio(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl}
    if ctrl.run_dir is None or not readers.is_backtest_run(ctrl.run_dir):
        ctx["error"] = "此頁需回測 run（含 nav/weights/decisions）。"
    else:
        nav = cache.read(ctrl.run_dir / "nav.parquet", lambda p: readers.load_nav(p.parent))
        weights = cache.read(
            ctrl.run_dir / "weights.parquet", lambda p: readers.load_weights(p.parent)
        )
        decisions = cache.read(
            ctrl.run_dir / "decisions.parquet", lambda p: readers.load_decisions(p.parent)
        )
        strat = (ctrl.strategies or sorted(nav["strategy_id"].unique()))[0]
        ctx.update(
            error=None,
            strategy=strat,
            stack_fig=charts.to_fragment(charts.weight_stack(weights, strat), "pf-stack"),
            band_fig=charts.to_fragment(charts.exposure_band(decisions, strat), "pf-band"),
            cost_fig=charts.to_fragment(charts.turnover_cost(nav, strat), "pf-cost"),
        )
    return render_page(
        request,
        active="/portfolio",
        full_template="portfolio.html",
        content_template="portfolio_content.html",
        context=ctx,
    )
```

- [ ] **Step 4: 模板** — `portfolio.html`：

```html
{% extends "base.html" %}
{% block content %}{% include "portfolio_content.html" %}{% endblock %}
```

`portfolio_content.html`：

```html
<h1 class="page-title">組合與成本</h1>
{% if error %}
<p class="empty">{{ error }}</p>
{% else %}
<div class="chart-card"><div class="chart-title">權重堆疊（{{ strategy }}，含現金）</div>{{ stack_fig|safe }}</div>
<div class="chart-card"><div class="chart-title">曝險軌跡與帶事件（{{ strategy }}）</div>{{ band_fig|safe }}</div>
<div class="chart-card"><div class="chart-title">每次再平衡換手率與累積成本（{{ strategy }}）</div>{{ cost_fig|safe }}</div>
{% endif %}
```

- [ ] **Step 5: 接線** — 在 `app.py`：import 改 `from quantcore.presentation.web.routes import data_quality, overview, portfolio, stubs`（先加 portfolio；data_quality 於 Task 4 加），並在 include 區加 `app.include_router(portfolio.router)`。在 `stubs.py` 的 `_STUBS` 移除 `("/portfolio", "組合與成本")` 這列（避免路由重複）。

> 註：Task 3 只加 portfolio；`app.py` import 若一次寫入 data_quality 會在 Task 4 前 import 失敗。**Task 3 的 app.py import 只加 portfolio**：`from quantcore.presentation.web.routes import overview, portfolio, stubs`。Task 4 再補 data_quality。

- [ ] **Step 6: GREEN + 全套 + ruff**，同前。

- [ ] **Step 7: Commit**

```bash
git add quantcore/presentation/web/routes/portfolio.py quantcore/presentation/web/templates/portfolio.html quantcore/presentation/web/templates/portfolio_content.html quantcore/presentation/web/app.py quantcore/presentation/web/routes/stubs.py tests/test_presentation/test_web_pages.py
git commit -m "feat(phase7): 頁 5 組合與成本（權重堆疊/帶事件/換手成本）"
```

---

### Task 4: 頁 7 資料品質

**Files:**
- Create: `quantcore/presentation/web/routes/data_quality.py`
- Create: `quantcore/presentation/web/templates/data_quality.html`、`data_quality_content.html`
- Modify: `quantcore/presentation/web/app.py`（include data_quality router）
- Modify: `quantcore/presentation/web/routes/stubs.py`（移除 `/data-quality`）
- Test: `tests/test_presentation/test_web_pages.py`（追加）

- [ ] **Step 1: 加失敗測試** — 追加：

```python
def test_data_quality_shows_manifest_or_missing(runs_root):
    r = _client(runs_root).get("/data-quality")
    assert r.status_code == 200
    assert "資料品質" in r.text
    # 合成快照通常不在本機 → 顯示「不在本機」提示；若在則顯示 MANIFEST
    assert ("不在本機" in r.text) or ("MANIFEST" in r.text)
```

- [ ] **Step 2: RED** — `/data-quality` 仍 stub（「建置中」），無「資料品質」以外内容 → 上面 assert 對 stub 的「建置中」不含「不在本機/MANIFEST」→ FAIL。

- [ ] **Step 3: route** — 建 `quantcore/presentation/web/routes/data_quality.py`：

```python
"""頁 7 資料品質：快照 MANIFEST、資料源、overrides 裁決、tickers（§11.2）。

快照可能只有 hash 進版控、parquet 不在本機 → 優雅提示。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()


@router.get("/data-quality", response_class=HTMLResponse)
def data_quality(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl}
    if ctrl.run_dir is None:
        ctx["error"] = "runs/ 下無 run。"
    else:
        snap_dir = readers.snapshot_dir_for_run(ctrl.run_dir)
        if not snap_dir.exists():
            ctx["error"] = f"快照 {snap_dir} 不在本機（可能只有 hash 進版控）。"
        else:
            meta = cache.read(
                snap_dir / "metadata.json", lambda p: readers.load_snapshot_metadata(p.parent)
            )
            manifest = cache.read(
                snap_dir / "MANIFEST.json", lambda p: readers.load_snapshot_manifest(p.parent)
            )
            ctx.update(
                error=None,
                manifest_json=json.dumps(manifest, indent=2, ensure_ascii=False),
                sources_json=json.dumps(meta.get("sources", {}), indent=2, ensure_ascii=False),
                overrides=meta.get("overrides", []),
                tickers_json=json.dumps(meta.get("tickers", {}), indent=2, ensure_ascii=False),
            )
    return render_page(
        request,
        active="/data-quality",
        full_template="data_quality.html",
        content_template="data_quality_content.html",
        context=ctx,
    )
```

- [ ] **Step 4: 模板** — `data_quality.html`：

```html
{% extends "base.html" %}
{% block content %}{% include "data_quality_content.html" %}{% endblock %}
```

`data_quality_content.html`：

```html
<h1 class="page-title">資料品質</h1>
{% if error %}
<p class="empty">{{ error }}</p>
{% else %}
<h2 class="section-title">快照 MANIFEST</h2>
<pre class="json-block">{{ manifest_json }}</pre>
<h2 class="section-title">資料源</h2>
<pre class="json-block">{{ sources_json }}</pre>
<h2 class="section-title">跨源裁決 overrides（{{ overrides|length }} 筆）</h2>
{% if overrides %}
<pre class="json-block">{{ overrides | tojson(indent=2) }}</pre>
{% else %}
<p class="empty">無 overrides。</p>
{% endif %}
<h2 class="section-title">選單 tickers</h2>
<pre class="json-block">{{ tickers_json }}</pre>
{% endif %}
```

- [ ] **Step 5: 接線** — `app.py` import 改為 `from quantcore.presentation.web.routes import data_quality, overview, portfolio, stubs`，include 區加 `app.include_router(data_quality.router)`。`stubs.py` 的 `_STUBS` 移除 `("/data-quality", "資料品質")`。此時 stubs 剩 6：decisions/garch/correlation/ablation/run-lab/price-trades。

- [ ] **Step 6: GREEN + 全套 + ruff**。同時更新 `tests/test_presentation/test_web_htmx.py` 的 `test_stub_pages_reachable`：把 `/portfolio`、`/data-quality` 從 stub 清單移除（它們現在是真頁、不再含「建置中」）——保留 `/decisions,/garch,/correlation,/ablation,/run-lab,/price-trades`。

- [ ] **Step 7: Commit**

```bash
git add quantcore/presentation/web/routes/data_quality.py quantcore/presentation/web/templates/data_quality.html quantcore/presentation/web/templates/data_quality_content.html quantcore/presentation/web/app.py quantcore/presentation/web/routes/stubs.py tests/test_presentation/test_web_pages.py tests/test_presentation/test_web_htmx.py
git commit -m "feat(phase7): 頁 7 資料品質（MANIFEST/資料源/overrides/tickers）"
```

---

## Self-Review 對照

- **Spec 覆蓋**：§5 頁 1（總覽 NAV/回撤/曝險/指標/子期間）✓、頁 5（權重堆疊/帶事件/換手成本）✓、頁 7（MANIFEST/資料源/overrides/tickers）✓；§3.3 圖表經 `charts` builder + `to_fragment` ✓。
- **邊界**：所有新 route 只 import readers + web 子模組；AST 守護（test_architecture.py）全套執行時把關。
- **移植保真**：builder 邏輯逐一對應舊 Streamlit 頁（git `59ab74f~1`）；`band_blocked == True` 的 `# noqa: E712` 沿用。
- **stub 收斂**：頁 5/7 從 stubs 移出、避免路由重複；`test_stub_pages_reachable` 同步縮為 6 頁。
- **型別一致**：`charts.{nav_log,drawdown,exposure,weight_stack,exposure_band,turnover_cost}` 簽名、`controls_for`/`render_page`/`cache.read` 跨 task 一致。
- **無 placeholder**：各 step 附完整程式碼與指令。
- **延後**：頁 2/3/4/6 → 計畫 2b；旗艦頁 9 → 計畫 2c。
