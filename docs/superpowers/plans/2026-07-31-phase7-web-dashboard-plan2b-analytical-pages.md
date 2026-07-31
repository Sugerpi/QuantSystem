# Phase 7 Web Dashboard 重製 — 計畫 2b：分析型頁 2/3/4/6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development 或 executing-plans。Steps 用 `- [ ]`。用量上限期間可由控制者 inline 執行；TDD 不變。

**Goal:** 頁 2 決策解剖（AC① UI 六層）、頁 3 GARCH、頁 4 相關結構、頁 6 消融，從 stub 換成真內容。

**Architecture:** 薄路由 + 胖 charts；頁內互動控制（決策日/資產/指標選擇）用 `<form method="get">` 帶 run/strat（`onchange` 自動提交、full GET，cache 快），非逐控制 HTMX。移植自退役 Streamlit 頁（git `59ab74f~1`）。§2.2 邊界不變。

**Tech Stack:** FastAPI/Jinja2/Plotly/pandas/numpy/scipy、pytest（TestClient）、ruff。

前置：計畫 2a 完成（charts 有 nav_log/drawdown/exposure/weight_stack/exposure_band/turnover_cost；頁 1/5/7 真內容；`_metrics_table.html`、圖表/表格 CSS）。設計見 spec §5。

分支：`feature/phase7a-dashboard`。

慣例同 2a：每頁 `pageX.html`（extends base，include content）+ `pageX_content.html`（HTMX 片段）+ route 用 `render_page`；圖以 `to_fragment` 嵌入。頁內選擇控制放在 content 片段內的 `<form method="get">`，含 `<input type="hidden" name="run">`、`<input type="hidden" name="strat">` 保住全域狀態，select/slider `onchange="this.form.submit()"`。

---

## 共用：控制列 partial `_page_controls.html`

**File:** Create `quantcore/presentation/web/templates/_page_controls.html`

```html
<form method="get" class="page-controls">
  <input type="hidden" name="run" value="{{ ctrl.run or '' }}">
  <input type="hidden" name="strat" value="{{ ctrl.strategies | join(',') }}">
  {% block pcontrols %}{% endblock %}
</form>
```

> 因 Jinja include 無法帶 block，改為各頁 content 直接內嵌 `<form method="get">` + hidden run/strat（見各頁模板）。此 partial 僅作參考；實作各頁自帶 form。

---

### Task 1: charts.py 加 2b 用 builder

**Files:** Modify `quantcore/presentation/web/charts.py`；Test `tests/test_presentation/test_web_charts.py`

- [ ] **Step 1: 加失敗測試**（追加）：

```python
def test_momentum_bar_highlights_selected():
    fig = charts.momentum_bar({"SPY": 0.3, "GLD": 0.1, "TLT": 0.2}, ["SPY", "TLT"])
    assert len(fig.data) == 1
    bar = fig.data[0]
    assert list(bar.x) == ["SPY", "TLT", "GLD"]  # 由高到低
    assert bar.marker.color[0] == charts.UP and bar.marker.color[2] != charts.UP


def test_heatmap_basic():
    fig = charts.heatmap([[1.0, 0.2], [0.2, 1.0]], ["A", "B"], ["A", "B"], zmin=-1, zmax=1)
    assert fig.data[0].type == "heatmap"
    assert list(fig.data[0].x) == ["A", "B"]


def test_line_series_multi():
    fig = charts.line_series(
        {"omega": ([1, 2], [0.1, 0.2]), "beta": ([1, 2], [0.8, 0.85])}
    )
    assert {t.name for t in fig.data} == {"omega", "beta"}


def test_resid_qq_has_points_and_diagonal():
    import numpy as np

    fig = charts.resid_qq(np.array([-1.0, 0.0, 1.0, 2.0, -0.5]))
    assert len(fig.data) == 2  # 散點 + y=x
    assert "y=x" in {t.name for t in fig.data}


def test_resid_acf_lags():
    import numpy as np

    rng = np.random.default_rng(0)
    fig = charts.resid_acf(rng.normal(size=50), lags=10)
    assert fig.data[0].type == "bar"
    assert len(fig.data[0].y) == 10
```

- [ ] **Step 2: RED** — `uv run pytest tests/test_presentation/test_web_charts.py -q` FAIL。

- [ ] **Step 3: 實作**（charts.py 檔末追加；`import numpy as np` 加到 import 區，isort 順序：numpy 在 pandas 前）：

```python
def momentum_bar(scores: dict[str, float], selected: list[str]) -> go.Figure:
    """動量分數長條，selected（前 K）以綠色高亮、其餘灰。"""
    items = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    sel = set(selected or [])
    colors = [UP if k in sel else "#6a6a62" for k, _ in items]
    fig = go.Figure(
        go.Bar(x=[k for k, _ in items], y=[v for _, v in items], marker_color=colors)
    )
    return style_dark(fig)


def heatmap(z, x, y, *, zmin=None, zmax=None, colorscale="Viridis") -> go.Figure:
    """通用熱圖（相關矩陣 / 敏感度）。"""
    fig = go.Figure(
        go.Heatmap(z=z, x=list(x), y=list(y), zmin=zmin, zmax=zmax, colorscale=colorscale)
    )
    return style_dark(fig)


def line_series(named: dict[str, tuple]) -> go.Figure:
    """多條命名折線；named[name] = (x, y)。"""
    fig = go.Figure()
    for name, (xs, ys) in named.items():
        fig.add_trace(go.Scatter(x=list(xs), y=list(ys), name=name, mode="lines"))
    return style_dark(fig)


def resid_qq(samples: np.ndarray) -> go.Figure:
    """標準化殘差 QQ（vs 常態）+ y=x 對角。"""
    from scipy import stats

    s = np.sort(np.asarray(samples, dtype=float))
    n = len(s)
    theo = stats.norm.ppf((np.arange(1, n + 1) - 0.5) / n)
    fig = go.Figure(go.Scatter(x=theo, y=s, mode="markers", name="樣本"))
    lim = [float(min(theo.min(), s.min())), float(max(theo.max(), s.max()))]
    fig.add_trace(go.Scatter(x=lim, y=lim, mode="lines", name="y=x"))
    fig.update_layout(xaxis_title="理論分位", yaxis_title="樣本分位")
    return style_dark(fig)


def resid_acf(samples: np.ndarray, lags: int = 20) -> go.Figure:
    """標準化殘差 ACF 長條。"""
    s = np.asarray(samples, dtype=float)
    s0 = s - s.mean()
    denom = float(np.dot(s0, s0)) or 1.0
    k = min(lags, len(s0) - 1)
    acf = [float(np.dot(s0[:-i], s0[i:]) / denom) for i in range(1, k + 1)]
    fig = go.Figure(go.Bar(x=list(range(1, k + 1)), y=acf))
    fig.update_layout(xaxis_title="lag")
    return style_dark(fig)
```

- [ ] **Step 4: GREEN + ruff**；`uv run pytest tests/test_presentation/test_web_charts.py -q`。

- [ ] **Step 5: Commit** — `git commit -m "feat(phase7): charts—動量長條/熱圖/多線/殘差 QQ·ACF builder"`

---

### Task 2: 頁 2 決策解剖（AC① UI 六層）

**Files:** Create `routes/decisions.py`、`templates/decisions.html`、`decisions_content.html`；Modify `app.py`（include）、`stubs.py`（移除 /decisions）、`test_web_htmx.py`（stub 清單移除 /decisions）、`test_web_pages.py`（+測試）。

- [ ] **Step 1: 加失敗測試**（test_web_pages.py 追加）：

```python
def test_decisions_six_layers(runs_root):
    r = _client(runs_root).get("/decisions")
    assert r.status_code == 200
    for lbl in ["(a)", "(b)", "(c)", "(d)", "(e)", "(f)"]:
        assert lbl in r.text
    assert "目標權重" in r.text
```

- [ ] **Step 2: RED**（/decisions 現為 stub）。

- [ ] **Step 3: route** `routes/decisions.py`：

```python
"""頁 2 決策解剖（AC① UI）：六層垂直瀑布，讀 readers.decision_layers。

決策日以 query param ?didx=N 選（預設最後一個）。
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()


@router.get("/decisions", response_class=HTMLResponse)
def decisions(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl, "error": None}
    if ctrl.run_dir is None or not readers.is_backtest_run(ctrl.run_dir):
        ctx["error"] = "此頁需回測 run（含 decisions）。"
        return render_page(
            request, active="/decisions", full_template="decisions.html",
            content_template="decisions_content.html", context=ctx,
        )
    dec = cache.read(ctrl.run_dir / "decisions.parquet", lambda p: readers.load_decisions(p.parent))
    strat = (ctrl.strategies or sorted(dec["strategy_id"].unique()))[0]
    sub = dec[dec["strategy_id"] == strat].sort_values("decision_date")
    if sub.empty:
        ctx["error"] = f"{strat} 無決策紀錄。"
        return render_page(
            request, active="/decisions", full_template="decisions.html",
            content_template="decisions_content.html", context=ctx,
        )
    dates = list(sub["decision_date"])
    try:
        didx = int(request.query_params.get("didx", len(dates) - 1))
    except ValueError:
        didx = len(dates) - 1
    didx = max(0, min(didx, len(dates) - 1))
    ddate = dates[didx]
    layer = readers.decision_layers(ctrl.run_dir, strat, ddate)
    prev = sub[sub["decision_date"] < ddate]
    prev_sigma = (
        readers.decision_layers(ctrl.run_dir, strat, prev["decision_date"].iloc[-1]).sigma_hat
        if not prev.empty
        else None
    )
    mom_fig = None
    if layer.momentum_scores:
        mom_fig = charts.to_fragment(
            charts.momentum_bar(layer.momentum_scores, layer.selected or []), "dec-mom"
        )
    sigma_rows = None
    if layer.sigma_hat:
        sigma_rows = [
            {"ticker": t, "sigma": v, "sigma_prev": (prev_sigma or {}).get(t)}
            for t, v in layer.sigma_hat.items()
        ]
    ctx.update(
        strategy=strat,
        dates=[pd.Timestamp(d).date().isoformat() for d in dates],
        didx=didx,
        ddate=pd.Timestamp(ddate).date().isoformat(),
        layer=layer,
        mom_fig=mom_fig,
        sigma_rows=sigma_rows,
        exposure={
            "sigma_p": layer.sigma_p,
            "exposure_raw": layer.exposure_raw,
            "exposure_applied": layer.exposure_applied,
            "band_blocked": bool(layer.band_blocked),
        }
        if layer.sigma_p is not None
        else None,
    )
    return render_page(
        request, active="/decisions", full_template="decisions.html",
        content_template="decisions_content.html", context=ctx,
    )
```

- [ ] **Step 4: 模板** `decisions.html`：

```html
{% extends "base.html" %}
{% block content %}{% include "decisions_content.html" %}{% endblock %}
```

`decisions_content.html`：

```html
<h1 class="page-title">決策解剖</h1>
{% if error %}
<p class="empty">{{ error }}</p>
{% else %}
<form method="get" class="page-controls">
  <input type="hidden" name="run" value="{{ ctrl.run or '' }}">
  <input type="hidden" name="strat" value="{{ ctrl.strategies | join(',') }}">
  <label class="ctl">決策日
    <input type="range" name="didx" min="0" max="{{ dates|length - 1 }}" value="{{ didx }}"
           onchange="this.form.submit()">
  </label>
  <span class="ident">{{ strategy }} · {{ ddate }} · event={{ layer.event }} · exec={{ layer.execution_date }}</span>
</form>

<h2 class="section-title">(a) point-in-time 合格選單</h2>
<p>{{ layer.eligible | join(", ") }}</p>

<h2 class="section-title">(b) 動量分數（前 K 高亮）</h2>
{% if mom_fig %}{{ mom_fig|safe }}{% else %}<p class="empty">本策略無動量層。</p>{% endif %}

<h2 class="section-title">(c) 絕對動量 pass/fail</h2>
{% if layer.absmom %}
<table class="data-table"><thead><tr><th>ticker</th><th>pass</th></tr></thead><tbody>
{% for t, v in layer.absmom.items() %}<tr><td class="rowhead">{{ t }}</td><td>{{ v }}</td></tr>{% endfor %}
</tbody></table>
{% else %}<p class="empty">—</p>{% endif %}

<h2 class="section-title">(d) 波動 σ̂（年化，vs 上一決策日）</h2>
{% if sigma_rows %}
<table class="data-table"><thead><tr><th>ticker</th><th>σ̂</th><th>σ̂(前)</th></tr></thead><tbody>
{% for row in sigma_rows %}<tr><td class="rowhead">{{ row.ticker }}</td>
<td>{{ "%.4g"|format(row.sigma) }}</td>
<td>{% if row.sigma_prev is number %}{{ "%.4g"|format(row.sigma_prev) }}{% else %}—{% endif %}</td></tr>{% endfor %}
</tbody></table>
{% else %}<p class="empty">—</p>{% endif %}

<h2 class="section-title">(e) 曝險：E = clip(σ*/σ̂_p)</h2>
{% if exposure %}
<pre class="json-block">{{ exposure | tojson(indent=2) }}</pre>
{% if layer.w_risky %}
<table class="data-table"><thead><tr><th>ticker</th><th>w_risky</th></tr></thead><tbody>
{% for t, v in layer.w_risky.items() %}<tr><td class="rowhead">{{ t }}</td><td>{{ "%.4g"|format(v) }}</td></tr>{% endfor %}
</tbody></table>{% endif %}
{% else %}<p class="empty">本策略無曝險層。</p>{% endif %}

<h2 class="section-title">(f) 目標權重（含 CASH）</h2>
<table class="data-table"><thead><tr><th>ticker</th><th>target</th></tr></thead><tbody>
{% for t, v in layer.target_weights.items() %}<tr><td class="rowhead">{{ t }}</td><td>{{ "%.4g"|format(v) }}</td></tr>{% endfor %}
</tbody></table>
{% endif %}
```

- [ ] **Step 5: 接線** — `app.py` import 加 decisions、include；`stubs.py` `_STUBS` 移除 `("/decisions", "決策解剖")`；`test_web_htmx.py` stub 清單移除 `/decisions`。

- [ ] **Step 6: CSS**（app.css 追加）：

```css
.page-controls { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.page-controls input[type="range"] { vertical-align: middle; }
.page-controls select { background: var(--panel-2); color: var(--fg); border: 1px solid var(--border); border-radius: 4px; padding: 3px 6px; font-family: var(--mono); }
```

- [ ] **Step 7: GREEN 全套 + ruff + Commit** — `git commit -m "feat(phase7): 頁 2 決策解剖（AC① UI 六層瀑布）"`

---

### Task 3: 頁 3 GARCH

**Files:** Create `routes/garch.py`、`templates/garch.html`、`garch_content.html`；Modify `app.py`、`stubs.py`、`test_web_htmx.py`、`test_web_pages.py`。

- [ ] **Step 1: 加失敗測試**：

```python
def test_garch_page_renders(runs_root):
    r = _client(runs_root).get("/garch")
    assert r.status_code == 200
    assert "GARCH 參數軌跡" in r.text or "無 GARCH 參數" in r.text
    assert "fallback" in r.text.lower() or "無 GARCH" in r.text
```

- [ ] **Step 2: RED**。

- [ ] **Step 3: route** `routes/garch.py`：

```python
"""頁 3 GARCH：參數軌跡、fallback 頻率、QLIKE/MZ-R²、殘差 QQ/ACF。

資產以 ?tk=、殘差資產以 ?rtk= 選（預設第一個）。
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()


def _param_rows(sub: pd.DataFrame) -> list[dict]:
    rows = []
    for _, r in sub.iterrows():
        gp = r["garch_params"]
        if not gp:
            continue
        for t, p in gp.items():
            if p:
                rows.append(
                    {"date": r["decision_date"], "ticker": t, **p, "persistence": p["alpha"] + p["beta"]}
                )
    return rows


@router.get("/garch", response_class=HTMLResponse)
def garch(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl, "error": None}
    if ctrl.run_dir is None or not readers.is_backtest_run(ctrl.run_dir):
        ctx["error"] = "此頁需回測 run（含 decisions）。"
        return render_page(request, active="/garch", full_template="garch.html",
                           content_template="garch_content.html", context=ctx)
    dec = cache.read(ctrl.run_dir / "decisions.parquet", lambda p: readers.load_decisions(p.parent))
    strat = (ctrl.strategies or sorted(dec["strategy_id"].unique()))[0]
    sub = dec[dec["strategy_id"] == strat].sort_values("decision_date")
    prows = _param_rows(sub)
    param_fig = None
    tickers: list[str] = []
    if prows:
        pt = pd.DataFrame(prows)
        tickers = sorted(pt["ticker"].unique())
        tk = request.query_params.get("tk") or tickers[0]
        if tk not in tickers:
            tk = tickers[0]
        tp = pt[pt["ticker"] == tk].sort_values("date")
        named = {c: (tp["date"], tp[c]) for c in ("omega", "alpha", "beta", "nu", "persistence")}
        param_fig = charts.to_fragment(charts.line_series(named), "g-param")
        ctx["tk"] = tk
    ctx["param_tickers"] = tickers
    ctx["param_fig"] = param_fig
    # fallback 頻率
    fb = []
    for _, r in sub.iterrows():
        for t, v in (r["vol_fell_back"] or {}).items():
            fb.append({"ticker": t, "fb": bool(v)})
    fb_fig = None
    if fb:
        fbdf = pd.DataFrame(fb).groupby("ticker")["fb"].mean().reset_index()
        fb_fig = charts.to_fragment(
            charts.heatmap([list(fbdf["fb"])], list(fbdf["ticker"]), ["fallback 比例"],
                           zmin=0, zmax=1, colorscale="Reds"),
            "g-fb",
        )
    ctx["fb_fig"] = fb_fig
    # QLIKE/MZ-R²
    ve = readers.load_vol_eval(ctrl.runs_root / "vol_eval")
    ctx["vol_eval_rows"] = ve.to_dict("records") if ve is not None else None
    ctx["vol_eval_cols"] = list(ve.columns) if ve is not None else None
    # 殘差 QQ/ACF
    resid = readers.load_residuals(ctrl.run_dir)
    qq_fig = acf_fig = None
    resid_tickers: list[str] = []
    if resid is not None and not resid.empty:
        rs = resid[resid["strategy_id"] == strat] if "strategy_id" in resid.columns else resid
        resid_tickers = sorted(rs["ticker"].unique())
        if resid_tickers:
            rtk = request.query_params.get("rtk") or resid_tickers[0]
            if rtk not in resid_tickers:
                rtk = resid_tickers[0]
            s = rs[rs["ticker"] == rtk]["std_resid"].dropna().to_numpy()
            if len(s) > 1:
                qq_fig = charts.to_fragment(charts.resid_qq(s), "g-qq")
                acf_fig = charts.to_fragment(charts.resid_acf(s, lags=20), "g-acf")
            ctx["rtk"] = rtk
    ctx["resid_tickers"] = resid_tickers
    ctx["qq_fig"] = qq_fig
    ctx["acf_fig"] = acf_fig
    ctx["strategy"] = strat
    return render_page(request, active="/garch", full_template="garch.html",
                       content_template="garch_content.html", context=ctx)
```

- [ ] **Step 4: 模板** `garch.html`（extends+include，同慣例）；`garch_content.html`：

```html
<h1 class="page-title">GARCH 檢視</h1>
{% if error %}<p class="empty">{{ error }}</p>{% else %}
<h2 class="section-title">GARCH 參數軌跡與 persistence</h2>
{% if param_fig %}
<form method="get" class="page-controls">
  <input type="hidden" name="run" value="{{ ctrl.run or '' }}">
  <input type="hidden" name="strat" value="{{ ctrl.strategies | join(',') }}">
  <label class="ctl">資產
    <select name="tk" onchange="this.form.submit()">
      {% for t in param_tickers %}<option value="{{ t }}" {% if t == tk %}selected{% endif %}>{{ t }}</option>{% endfor %}
    </select>
  </label>
</form>
{{ param_fig|safe }}
{% else %}<p class="empty">本策略/此 run 無 GARCH 參數（EWMA 或非波動目標策略）。</p>{% endif %}

<h2 class="section-title">GARCH fallback 頻率（vol_fell_back）</h2>
{% if fb_fig %}{{ fb_fig|safe }}{% else %}<p class="empty">—</p>{% endif %}

<h2 class="section-title">QLIKE / MZ-R²（GARCH vs EWMA）</h2>
{% if vol_eval_rows %}
<table class="data-table"><thead><tr>{% for c in vol_eval_cols %}<th>{{ c }}</th>{% endfor %}</tr></thead><tbody>
{% for row in vol_eval_rows %}<tr>{% for c in vol_eval_cols %}<td>{% if row[c] is number %}{{ "%.4g"|format(row[c]) }}{% else %}{{ row[c] }}{% endif %}</td>{% endfor %}</tr>{% endfor %}
</tbody></table>
{% else %}<p class="empty">本次未儲存（無 runs/vol_eval/）。</p>{% endif %}

<h2 class="section-title">標準化殘差 QQ / ACF</h2>
{% if qq_fig %}
<form method="get" class="page-controls">
  <input type="hidden" name="run" value="{{ ctrl.run or '' }}">
  <input type="hidden" name="strat" value="{{ ctrl.strategies | join(',') }}">
  {% if tk %}<input type="hidden" name="tk" value="{{ tk }}">{% endif %}
  <label class="ctl">殘差資產
    <select name="rtk" onchange="this.form.submit()">
      {% for t in resid_tickers %}<option value="{{ t }}" {% if t == rtk %}selected{% endif %}>{{ t }}</option>{% endfor %}
    </select>
  </label>
</form>
<div class="chart-grid"><div class="chart-card">{{ qq_fig|safe }}</div><div class="chart-card">{{ acf_fig|safe }}</div></div>
{% else %}<p class="empty">本次未儲存（無 model_details/residuals）。</p>{% endif %}
{% endif %}
```

- [ ] **Step 5: 接線 + CSS（已於 Task 2 加）+ GREEN + ruff + Commit** — `git commit -m "feat(phase7): 頁 3 GARCH（參數軌跡/fallback/QLIKE·MZ-R²/殘差 QQ·ACF）"`

---

### Task 4: 頁 4 相關結構

**Files:** Create `routes/correlation.py`、`templates/correlation.html`、`correlation_content.html`；Modify `app.py`、`stubs.py`、`test_web_htmx.py`、`test_web_pages.py`。

- [ ] **Step 1: 加失敗測試**：

```python
def test_correlation_page_renders(runs_root):
    r = _client(runs_root).get("/correlation")
    assert r.status_code == 200
    assert ("相關矩陣熱圖" in r.text) or ("本次未儲存" in r.text)
```

（合成 fixture 的 full/full_erc 若有 correlation.parquet 顯示熱圖；否則優雅提示。）

- [ ] **Step 2: RED**。

- [ ] **Step 3: route** `routes/correlation.py`：

```python
"""頁 4 相關結構：相關矩陣熱圖（時間 ?cidx）、資產對序列（?ti、?tj）、第二 run 疊圖（?r2）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()


@router.get("/correlation", response_class=HTMLResponse)
def correlation(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl, "error": None}
    corr = cache.read(ctrl.run_dir, readers.load_correlation) if ctrl.run_dir else None
    if corr is None or corr.empty:
        ctx["error"] = "本次未儲存（無 model_details/correlation；僅 full/full_erc 有相關矩陣）。"
        return render_page(request, active="/correlation", full_template="correlation.html",
                           content_template="correlation_content.html", context=ctx)
    strat = (ctrl.strategies or sorted(corr["strategy_id"].unique()))[0]
    csub = corr[corr["strategy_id"] == strat]
    dates = sorted(csub["decision_date"].unique())
    try:
        cidx = int(request.query_params.get("cidx", len(dates) - 1))
    except ValueError:
        cidx = len(dates) - 1
    cidx = max(0, min(cidx, len(dates) - 1))
    mat = readers.correlation_matrix_at(csub, strat, dates[cidx])
    tickers = sorted(mat.index)
    ti = request.query_params.get("ti") or (tickers[0] if tickers else None)
    tj = request.query_params.get("tj") or (tickers[1] if len(tickers) > 1 else tickers[0])
    if ti not in tickers:
        ti = tickers[0]
    if tj not in tickers:
        tj = tickers[min(1, len(tickers) - 1)]
    pair = csub[(csub["ticker_i"] == ti) & (csub["ticker_j"] == tj)].sort_values("decision_date")
    named = {f"{ti}-{tj}": (pair["decision_date"], pair["corr"])}
    others = [r["name"] for r in readers.list_runs(ctrl.runs_root) if r["name"] != ctrl.run]
    r2 = request.query_params.get("r2")
    if r2 and r2 in others:
        c2 = readers.load_correlation(ctrl.runs_root / r2)
        if c2 is not None and not c2.empty:
            s2 = (ctrl.strategies or sorted(c2["strategy_id"].unique()))[0]
            p2 = c2[(c2["strategy_id"] == s2) & (c2["ticker_i"] == ti) & (c2["ticker_j"] == tj)].sort_values("decision_date")
            named[r2] = (p2["decision_date"], p2["corr"])
    ctx.update(
        strategy=strat,
        dates=[str(d)[:10] for d in dates],
        cidx=cidx,
        heat_fig=charts.to_fragment(
            charts.heatmap(mat.values, list(mat.columns), list(mat.index), zmin=-1, zmax=1, colorscale="RdBu"),
            "c-heat",
        ),
        tickers=tickers,
        ti=ti,
        tj=tj,
        pair_fig=charts.to_fragment(charts.line_series(named), "c-pair"),
        others=others,
        r2=r2 or "",
    )
    return render_page(request, active="/correlation", full_template="correlation.html",
                       content_template="correlation_content.html", context=ctx)
```

- [ ] **Step 4: 模板** `correlation.html`（慣例）；`correlation_content.html`：

```html
<h1 class="page-title">相關結構</h1>
{% if error %}<p class="empty">{{ error }}</p>{% else %}
<h2 class="section-title">相關矩陣熱圖（{{ strategy }}）</h2>
<form method="get" class="page-controls">
  <input type="hidden" name="run" value="{{ ctrl.run or '' }}">
  <input type="hidden" name="strat" value="{{ ctrl.strategies | join(',') }}">
  <input type="hidden" name="ti" value="{{ ti }}"><input type="hidden" name="tj" value="{{ tj }}">
  <label class="ctl">決策日
    <input type="range" name="cidx" min="0" max="{{ dates|length - 1 }}" value="{{ cidx }}" onchange="this.form.submit()">
  </label>
  <span class="ident">{{ dates[cidx] }}</span>
</form>
{{ heat_fig|safe }}

<h2 class="section-title">資產對相關時間序列</h2>
<form method="get" class="page-controls">
  <input type="hidden" name="run" value="{{ ctrl.run or '' }}">
  <input type="hidden" name="strat" value="{{ ctrl.strategies | join(',') }}">
  <input type="hidden" name="cidx" value="{{ cidx }}">
  <label class="ctl">i <select name="ti" onchange="this.form.submit()">{% for t in tickers %}<option value="{{ t }}" {% if t==ti %}selected{% endif %}>{{ t }}</option>{% endfor %}</select></label>
  <label class="ctl">j <select name="tj" onchange="this.form.submit()">{% for t in tickers %}<option value="{{ t }}" {% if t==tj %}selected{% endif %}>{{ t }}</option>{% endfor %}</select></label>
  <label class="ctl">疊第二 run
    <select name="r2" onchange="this.form.submit()">
      <option value="">（不疊）</option>
      {% for o in others %}<option value="{{ o }}" {% if o==r2 %}selected{% endif %}>{{ o }}</option>{% endfor %}
    </select>
  </label>
</form>
{{ pair_fig|safe }}
{% endif %}
```

- [ ] **Step 5: 接線 + GREEN + ruff + Commit** — `git commit -m "feat(phase7): 頁 4 相關結構（熱圖時間滑桿/資產對序列/第二 run 疊圖）"`

---

### Task 5: 頁 6 消融

**Files:** Create `routes/ablation.py`、`templates/ablation.html`、`ablation_content.html`；Modify `app.py`、`stubs.py`、`test_web_htmx.py`、`test_web_pages.py`。

- [ ] **Step 1: 加失敗測試**：

```python
def test_ablation_page_renders(runs_root):
    r = _client(runs_root).get("/ablation")
    assert r.status_code == 200
    assert ("指標表" in r.text) or ("無消融表" in r.text)
```

- [ ] **Step 2: RED**。

- [ ] **Step 3: route** `routes/ablation.py`：

```python
"""頁 6 消融：指標表、敏感度熱圖（?metric）、配對 bootstrap CI 表。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()

_METRICS = ("sharpe", "calmar", "max_drawdown", "annualized_return")


@router.get("/ablation", response_class=HTMLResponse)
def ablation(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl, "error": None}
    comp = cache.read(ctrl.run_dir, readers.load_comparison) if ctrl.run_dir else None
    if comp is None:
        ctx["error"] = "本 run 無消融表（comparison.parquet）——請選一個消融 run。"
        return render_page(request, active="/ablation", full_template="ablation.html",
                           content_template="ablation_content.html", context=ctx)
    metric = request.query_params.get("metric", "sharpe")
    if metric not in _METRICS:
        metric = "sharpe"
    piv = comp.pivot_table(index="cell_label", columns="strategy_id", values=metric)
    bs = readers.load_bootstrap(ctrl.run_dir)
    ctx.update(
        comp_cols=list(comp.columns),
        comp_rows=comp.to_dict("records"),
        metrics=_METRICS,
        metric=metric,
        heat_fig=charts.to_fragment(
            charts.heatmap(piv.values, list(piv.columns), list(piv.index), colorscale="Viridis"),
            "ab-heat",
        ),
        bs_cols=list(bs.columns) if bs is not None else None,
        bs_rows=bs.to_dict("records") if bs is not None else None,
    )
    return render_page(request, active="/ablation", full_template="ablation.html",
                       content_template="ablation_content.html", context=ctx)
```

- [ ] **Step 4: 模板** `ablation.html`（慣例）；`ablation_content.html`：

```html
<h1 class="page-title">消融比較</h1>
<p class="empty" style="margin-bottom:8px">提示：敏感度表用於檢驗穩健性，不是用來挑最好的一格。</p>
{% if error %}<p class="empty">{{ error }}</p>{% else %}
<h2 class="section-title">指標表</h2>
<div style="overflow-x:auto"><table class="data-table"><thead><tr>{% for c in comp_cols %}<th>{{ c }}</th>{% endfor %}</tr></thead><tbody>
{% for row in comp_rows %}<tr>{% for c in comp_cols %}<td>{% if row[c] is number %}{{ "%.4g"|format(row[c]) }}{% else %}{{ row[c] }}{% endif %}</td>{% endfor %}</tr>{% endfor %}
</tbody></table></div>

<h2 class="section-title">敏感度熱圖（cell × 策略）</h2>
<form method="get" class="page-controls">
  <input type="hidden" name="run" value="{{ ctrl.run or '' }}">
  <input type="hidden" name="strat" value="{{ ctrl.strategies | join(',') }}">
  <label class="ctl">指標 <select name="metric" onchange="this.form.submit()">{% for m in metrics %}<option value="{{ m }}" {% if m==metric %}selected{% endif %}>{{ m }}</option>{% endfor %}</select></label>
</form>
{{ heat_fig|safe }}

<h2 class="section-title">配對 bootstrap CI（full vs 消融版）</h2>
{% if bs_rows %}
<div style="overflow-x:auto"><table class="data-table"><thead><tr>{% for c in bs_cols %}<th>{{ c }}</th>{% endfor %}</tr></thead><tbody>
{% for row in bs_rows %}<tr>{% for c in bs_cols %}<td>{% if row[c] is number %}{{ "%.4g"|format(row[c]) }}{% else %}{{ row[c] }}{% endif %}</td>{% endfor %}</tr>{% endfor %}
</tbody></table></div>
{% else %}<p class="empty">本 run 無 bootstrap.parquet。</p>{% endif %}
{% endif %}
```

- [ ] **Step 5: 接線 + GREEN + ruff + Commit** — `git commit -m "feat(phase7): 頁 6 消融（指標表/敏感度熱圖/配對 bootstrap CI）"`

---

## Self-Review 對照

- **Spec §5 覆蓋**：頁 2 六層（a–f，AC① UI）✓、頁 3（參數軌跡/fallback/QLIKE·MZ-R²/殘差 QQ·ACF）✓、頁 4（熱圖時間滑桿/資產對序列/第二 run 疊圖）✓、頁 6（指標表/敏感度熱圖/bootstrap CI）✓。
- **移植保真**：對應舊 Streamlit 頁（git `59ab74f~1`）；互動由 Streamlit widget → query-param GET 表單。
- **邊界**：新 route 只 import readers + web；AST 守護把關。
- **stub 收斂**：4 頁移出 stubs、`test_web_htmx.py` 同步；完成後 stubs 剩 2（/run-lab、/price-trades）。
- **charts builder**：momentum_bar/heatmap/line_series/resid_qq/resid_acf（Task 1，TDD）。
- **無 placeholder**：各 step 附完整程式碼。
- **延後**：旗艦頁 9 → 計畫 2c。
```
