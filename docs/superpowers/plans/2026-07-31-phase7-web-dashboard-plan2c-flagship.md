# Phase 7 Web Dashboard 重製 — 計畫 2c：旗艦頁 9 價格與交易 Implementation Plan

> **For agentic workers:** subagent-driven-development 或 executing-plans。用量上限期間由控制者 inline 執行；TDD 不變。

**Goal:** 頁 9 價格與交易（旗艦）從 stub 換成四元件真內容：① 選定標的 adj_close 走勢 + 買賣進出場標記（點標記跳決策解剖）② 標的持有列表（點切換）③ 成交明細 blotter（分頁/篩選 + 對帳）④ 持倉隨時間堆疊。完成後唯讀 dashboard 8/9 頁真內容（頁 8 Run Lab 為 7b stub）。

**Architecture:** 薄路由；`charts.price_with_trades` builder；頁內控制用 GET 表單（標的 ?tk、blotter 篩 ?ftk、分頁 ?page）；點價格標記經 app.js `plotly_click` → 導覽 `/decisions?...&ddate=`（decisions route 新增 ddate→didx 對應）。資料：`trades.parquet`（Δw/fill/cost）、`weights.parquet`（持倉）、快照 `prices.parquet`（adj_close）。§2.2 邊界不變。

**Tech Stack:** FastAPI/Jinja2/Plotly/pandas、pytest、ruff。前置：計畫 2a/2b 完成。分支 `feature/phase7a-dashboard`。舊頁邏輯：git `59ab74f~1:.../pages/9_Price_Trades.py`。

---

### Task 1: charts.price_with_trades builder + decisions route 支援 ?ddate

**Files:** Modify `charts.py`、`routes/decisions.py`；Test `test_web_charts.py`。

- [ ] **Step 1: 測試**（test_web_charts.py 追加）：

```python
def test_price_with_trades_line_and_marks():
    import pandas as pd

    price = pd.Series(
        [100.0, 101.0, 102.0, 103.0],
        index=pd.date_range("2020-01-01", periods=4, freq="D"),
    )
    tr = pd.DataFrame(
        {
            "execution_date": pd.to_datetime(["2020-01-02", "2020-01-04"]),
            "side": ["buy", "sell"],
            "fill_price": [101.0, 103.0],
        }
    )
    fig = charts.price_with_trades(price, tr, "SPY")
    names = {t.name for t in fig.data}
    assert "SPY price" in names
    assert any("buy" in n for n in names) and any("sell" in n for n in names)
    buy = next(t for t in fig.data if t.name.endswith("buy"))
    assert buy.customdata is not None  # 供點擊跳決策
```

- [ ] **Step 2: RED**。

- [ ] **Step 3: charts.price_with_trades**（charts.py 檔末）：

```python
def price_with_trades(price, trades_tk, ticker: str) -> go.Figure:
    """單一標的 adj_close 折線 + 買賣進出場標記（marker customdata=execution_date ISO）。

    price 為該檔 adj_close Series（index=date）；trades_tk 為該檔交易（execution_date/side/fill_price）。
    有 price 時標記 y 取當日 adj_close（reindex，缺值 NaN 不拋錯）；否則取 fill_price。
    """
    fig = go.Figure()
    has_price = price is not None and len(price) > 0
    if has_price:
        fig.add_trace(go.Scatter(x=price.index, y=price.values, name=f"{ticker} price", mode="lines"))
    for side, sym, col in (("buy", "triangle-up", UP), ("sell", "triangle-down", DOWN)):
        ts = trades_tk[trades_tk["side"] == side]
        if ts.empty:
            continue
        y = price.reindex(ts["execution_date"]).to_numpy() if has_price else ts["fill_price"].to_numpy()
        cd = [pd.Timestamp(d).date().isoformat() for d in ts["execution_date"]]
        fig.add_trace(
            go.Scatter(
                x=ts["execution_date"], y=y, mode="markers", name=f"{ticker} {side}",
                marker=dict(symbol=sym, size=10, color=col), customdata=cd,
            )
        )
    return style_dark(fig)
```

- [ ] **Step 4: decisions route 支援 ?ddate**（`routes/decisions.py`：在算出 `dates` 後、`didx` 之前插入 ddate 對應）。把
```python
    dates = list(sub["decision_date"])
    try:
        didx = int(request.query_params.get("didx", len(dates) - 1))
    except ValueError:
        didx = len(dates) - 1
```
改為：
```python
    dates = list(sub["decision_date"])
    ddate_q = request.query_params.get("ddate")
    if ddate_q:
        want = pd.Timestamp(ddate_q)
        le = [i for i, d in enumerate(dates) if pd.Timestamp(d) <= want]
        didx = le[-1] if le else 0
    else:
        try:
            didx = int(request.query_params.get("didx", len(dates) - 1))
        except ValueError:
            didx = len(dates) - 1
```

- [ ] **Step 5: GREEN + ruff + Commit** — `git commit -m "feat(phase7): charts.price_with_trades + decisions 支援 ?ddate 對應"`

---

### Task 2: 頁 9 route + 模板（四元件）+ app.js 點擊跳決策

**Files:** Create `routes/price_trades.py`、`templates/price_trades.html`、`price_trades_content.html`；Modify `app.py`、`stubs.py`、`static/js/app.js`、`static/css/app.css`、`test_web_htmx.py`、`test_web_pages.py`。

- [ ] **Step 1: 測試**（test_web_pages.py 追加）：

```python
def test_price_trades_flagship(runs_root):
    r = _client(runs_root).get("/price-trades")
    assert r.status_code == 200
    assert ("價格與進出場" in r.text) or ("本次未儲存" in r.text)
```

（合成 fixture 若有 trades.parquet → 四元件；否則優雅提示。真 run 才有完整資料。）

- [ ] **Step 2: RED**（/price-trades 現為 stub）。

- [ ] **Step 3: route** `routes/price_trades.py`：

```python
"""頁 9 價格與交易（旗艦）：走勢+進出場標記、標的持有列表、blotter、持倉堆疊。"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()

_PAGE = 50


def _render(request: Request, ctx: dict) -> HTMLResponse:
    return render_page(
        request, active="/price-trades", full_template="price_trades.html",
        content_template="price_trades_content.html", context=ctx,
    )


@router.get("/price-trades", response_class=HTMLResponse)
def price_trades(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl, "error": None}
    trades = cache.read(ctrl.run_dir, readers.load_trades) if ctrl.run_dir else None
    if trades is None:
        ctx["error"] = "本次未儲存（無 trades.parquet）。"
        return _render(request, ctx)
    strat = (ctrl.strategies or sorted(trades["strategy_id"].unique()))[0]
    tr = trades[trades["strategy_id"] == strat].sort_values("execution_date")
    tickers = sorted(tr["ticker"].unique())
    tk = request.query_params.get("tk") or (tickers[0] if tickers else None)
    if tk not in tickers:
        tk = tickers[0] if tickers else None
    # 價格面板
    snap_dir = readers.snapshot_dir_for_run(ctrl.run_dir)
    panel = readers.load_adj_close_panel(snap_dir) if snap_dir.exists() else None
    price = panel[tk] if (panel is not None and tk in panel.columns) else None
    price_fig = charts.to_fragment(charts.price_with_trades(price, tr[tr["ticker"] == tk], tk), "pt-price")
    # 標的持有列表（最後決策日權重）
    weights = cache.read(ctrl.run_dir / "weights.parquet", lambda p: readers.load_weights(p.parent))
    w = weights[weights["strategy_id"] == strat]
    last_w = (
        w[w["date"] == w["date"].max()].set_index("ticker")["weight"].to_dict() if not w.empty else {}
    )
    ticker_rows = [
        {"ticker": t, "weight": last_w.get(t)} for t in sorted(set(tickers) | set(last_w))
    ]
    # blotter 分頁 + 篩選
    ftk = request.query_params.get("ftk") or ""
    blot = tr[tr["ticker"] == ftk] if ftk else tr
    try:
        page = int(request.query_params.get("page", 0))
    except ValueError:
        page = 0
    npages = max(1, (len(blot) + _PAGE - 1) // _PAGE)
    page = max(0, min(page, npages - 1))
    view = blot.iloc[page * _PAGE : (page + 1) * _PAGE]
    ctx.update(
        strategy=strat, tickers=tickers, tk=tk, price_fig=price_fig,
        ticker_rows=ticker_rows,
        stack_fig=charts.to_fragment(charts.weight_stack(weights, strat), "pt-stack"),
        blot_cols=list(tr.columns), blot_rows=view.to_dict("records"),
        ftk=ftk, page=page, npages=npages, n_trades=len(tr),
    )
    return _render(request, ctx)
```

- [ ] **Step 4: 模板** `price_trades.html`（extends+include）；`price_trades_content.html`：

```html
<h1 class="page-title">價格與交易</h1>
{% if error %}<p class="empty">{{ error }}</p>{% else %}
<div class="pt-grid">
  <div>
    <h2 class="section-title">價格與進出場（{{ tk }}）</h2>
    <form method="get" class="page-controls">
      <input type="hidden" name="run" value="{{ ctrl.run or '' }}">
      <input type="hidden" name="strat" value="{{ ctrl.strategies | join(',') }}">
      <label class="ctl">標的 <select name="tk" onchange="this.form.submit()">{% for t in tickers %}<option value="{{ t }}" {% if t==tk %}selected{% endif %}>{{ t }}</option>{% endfor %}</select></label>
      <span class="ident">點綠▲/紅▼ 標記跳該日決策解剖</span>
    </form>
    <div id="pt-price-wrap">{{ price_fig|safe }}</div>
  </div>
  <div class="pt-side">
    <div class="chart-title">標的 · 現持有 w</div>
    {% for row in ticker_rows %}
    <a class="pt-tick {% if row.ticker==tk %}active{% endif %}"
       href="/price-trades?run={{ ctrl.run }}&strat={{ ctrl.strategies | join(',') }}&tk={{ row.ticker }}"
       hx-get="/price-trades?run={{ ctrl.run }}&strat={{ ctrl.strategies | join(',') }}&tk={{ row.ticker }}"
       hx-target="#content" hx-push-url="true">
      <span>{{ row.ticker }}</span>
      <span>{% if row.weight is number %}{{ "%.3f"|format(row.weight) }}{% else %}—{% endif %}</span>
    </a>
    {% endfor %}
  </div>
</div>

<h2 class="section-title">持倉隨時間（堆疊，{{ strategy }}）</h2>
<div class="chart-card">{{ stack_fig|safe }}</div>

<h2 class="section-title">成交明細 blotter · {{ strategy }} · {{ n_trades }} 筆</h2>
<form method="get" class="page-controls">
  <input type="hidden" name="run" value="{{ ctrl.run or '' }}">
  <input type="hidden" name="strat" value="{{ ctrl.strategies | join(',') }}">
  <input type="hidden" name="tk" value="{{ tk }}">
  <label class="ctl">篩標的 <select name="ftk" onchange="this.form.submit()"><option value="">（全部）</option>{% for t in tickers %}<option value="{{ t }}" {% if t==ftk %}selected{% endif %}>{{ t }}</option>{% endfor %}</select></label>
  <span class="ident">第 {{ page + 1 }} / {{ npages }} 頁</span>
</form>
<div style="overflow-x:auto"><table class="data-table"><thead><tr>{% for c in blot_cols %}<th>{{ c }}</th>{% endfor %}</tr></thead><tbody>
{% for row in blot_rows %}<tr>{% for c in blot_cols %}<td>{% if row[c] is number %}{{ "%.4g"|format(row[c]) }}{% else %}{{ row[c] }}{% endif %}</td>{% endfor %}</tr>{% endfor %}
</tbody></table></div>
{% endif %}
```

- [ ] **Step 5: app.js**（追加 plotly_click → 跳決策）：

```javascript
document.body.addEventListener("htmx:afterSwap", wirePriceClick);
document.addEventListener("DOMContentLoaded", wirePriceClick);
function wirePriceClick() {
  var wrap = document.getElementById("pt-price-wrap");
  if (!wrap) return;
  var gd = wrap.querySelector(".plotly-graph-div");
  if (!gd || gd._ptWired) return;
  gd._ptWired = true;
  gd.on("plotly_click", function (e) {
    var p = e.points && e.points[0];
    if (!p || p.customdata == null) return;
    var params = new URLSearchParams(window.location.search);
    var run = params.get("run") || "";
    var strat = params.get("strat") || "";
    var url = "/decisions?run=" + encodeURIComponent(run) + "&strat=" + encodeURIComponent(strat) + "&ddate=" + encodeURIComponent(p.customdata);
    window.location.href = url;
  });
}
```

- [ ] **Step 6: CSS**（app.css 追加）：

```css
.pt-grid { display: grid; grid-template-columns: 1fr 168px; gap: 12px; }
.pt-side { border: 1px solid var(--border-soft); border-radius: 8px; padding: 8px; max-height: 460px; overflow-y: auto; }
.pt-tick { display: flex; justify-content: space-between; gap: 6px; padding: 4px 6px; font-size: 12px; color: var(--fg-dim); text-decoration: none; border-radius: 4px; }
.pt-tick:hover { background: var(--panel-2); color: var(--fg); }
.pt-tick.active { background: #141008; color: var(--amber); border-left: 2px solid var(--amber); }
```

- [ ] **Step 7: 接線** — app.py import/include price_trades；stubs `_STUBS` 移除 `/price-trades`（剩 /run-lab 一個）；test_web_htmx.py stub 清單剩 `/run-lab`。

- [ ] **Step 8: GREEN 全套 + ruff + Commit** — `git commit -m "feat(phase7): 頁 9 價格與交易旗艦（走勢+進出場/標的列表/blotter/持倉堆疊/點標記跳決策）"`

---

## Self-Review 對照

- **Spec §6 四元件**：主價格面板 + 進出場標記 + 點擊跳決策 ✓、標的持有列表（點切換）✓、blotter（分頁/篩選）✓、持倉堆疊 ✓。
- **click→decision**：marker customdata=execution_date，app.js 導覽 `/decisions?ddate=`，decisions route ddate→最後 ≤ 該日的決策。
- **邊界**：route 只 import readers + web；AST 守護把關。
- **stub 收斂**：/price-trades 移出，stubs 只剩 /run-lab（7b）。
- **移植保真**：價格+標記+blotter 對應舊頁；新增標的列表/持倉堆疊/點擊跳決策（旗艦強化，spec §6）。
```
