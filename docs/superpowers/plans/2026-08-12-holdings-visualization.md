# 持倉視覺化改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用持倉熱圖取代兩頁的權重堆疊圖，並把「價格與交易」頁頂端升級為 價格+持倉 雙面板，讓「模型總體決策」與「艙位 vs 股價」都讀得清楚。

**Architecture:** 純呈現層改動（不 import 引擎）。在 `charts.py` 新增 `holdings_heatmap`、`price_with_weight` 兩個 Plotly 圖表函式，取代 `weight_stack` 與 `price_with_trades`；路由與模板改接新函式；移除兩個死碼函式。

**Tech Stack:** FastAPI + Jinja2 + HTMX + Plotly（`plotly.graph_objects`、`plotly.subplots`）；pytest + fastapi TestClient。

---

## 背景（實作者須知）

- `charts.py` 已有深色主題 token：`BG/FG/GRID/AMBER/UP/DOWN/BLUE/COLORWAY` 與 `style_dark(fig)`、`to_fragment(fig, div_id)`。新函式沿用，不新增顏色體系。
- `AMBER = "#ff8c1a"`、`UP = "#26a65b"`、`DOWN = "#e0483e"` 已定義於 `charts.py` 檔頭。
- 圖表函式**不 import 引擎**；資料由 `readers` 提供，路由用 `cache.read` 包住。
- 測試 fixture：`tests/test_presentation/conftest.py` 提供 session 級 `runs_root`（含合成 `full`/`bh_spy` run）。`tests/test_presentation/test_web_charts.py` 已有 `_weights_df()`（SPY 0.6 / GLD 0.4，3 天）。
- 執行測試用專案的 venv：`.venv/Scripts/python.exe -m pytest ...`。
- commit 會觸發 ruff / ruff-format pre-commit hook；程式碼須符合格式。

## 檔案結構

| 檔案 | 責任 | 動作 |
|------|------|------|
| `quantcore/presentation/web/charts.py` | Plotly 圖表 + 樣式 | 新增 `HEAT_SCALE`、`WEIGHT_PANEL_ROWS` 常數與 `holdings_heatmap`、`price_with_weight`；移除 `weight_stack`、`price_with_trades` |
| `quantcore/presentation/web/routes/price_trades.py` | 頁 9 路由 | 頂端圖改 `price_with_weight`；堆疊改 `holdings_heatmap` |
| `quantcore/presentation/web/routes/portfolio.py` | 頁 5 路由 | 堆疊改 `holdings_heatmap` |
| `quantcore/presentation/web/templates/price_trades_content.html` | 頁 9 模板 | 區塊標題「持倉隨時間（堆疊）」→「持倉熱圖」 |
| `quantcore/presentation/web/templates/portfolio_content.html` | 頁 5 模板 | 卡標題「權重堆疊」→「持倉熱圖」 |
| `tests/test_presentation/test_web_charts.py` | 圖表單元測試 | 新增熱圖/雙面板測試；移除 `weight_stack`/`price_with_trades` 測試 |
| `tests/test_presentation/test_web_pages.py` | 頁面 smoke 測試 | portfolio 斷言字串「權重堆疊」→「持倉熱圖」 |

---

### Task 1: `holdings_heatmap` 圖表函式

**Files:**
- Modify: `quantcore/presentation/web/charts.py`
- Test: `tests/test_presentation/test_web_charts.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_presentation/test_web_charts.py` 末尾新增（沿用檔內既有 `_weights_df()`）：

```python
def test_holdings_heatmap_orders_by_mean_weight():
    fig = charts.holdings_heatmap(_weights_df(), "full")
    assert len(fig.data) == 1
    hm = fig.data[0]
    assert hm.type == "heatmap"
    assert list(hm.y) == ["SPY", "GLD"]  # 平均權重 0.6 > 0.4 → 排前
    assert hm.zmin == 0.0
    assert len(hm.z) == 2 and len(hm.z[0]) == 3  # (n_ticker, n_date)


def test_holdings_heatmap_single_ticker_ok():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=2, freq="D"),
            "strategy_id": "bh_spy",
            "ticker": "SPY",
            "weight": [1.0, 1.0],
        }
    )
    fig = charts.holdings_heatmap(df, "bh_spy")
    assert fig.data[0].type == "heatmap"
    assert list(fig.data[0].y) == ["SPY"]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.venv/Scripts/python.exe -m pytest tests/test_presentation/test_web_charts.py::test_holdings_heatmap_orders_by_mean_weight -v`
Expected: FAIL，`AttributeError: module 'quantcore.presentation.web.charts' has no attribute 'holdings_heatmap'`

- [ ] **Step 3: 實作 `holdings_heatmap`**

在 `charts.py` 的 `COLORWAY` 常數下方新增模組常數：

```python
HEAT_SCALE = [[0.0, "#000000"], [0.15, "#241a08"], [0.5, "#ff8c1a"], [1.0, "#ffe1b0"]]
```

在 `charts.py` 移除 `weight_stack` 的位置（Task 4 才刪；此處先新增函式，放檔案任意合適處，例如 `heatmap` 附近）新增：

```python
def holdings_heatmap(weights: pd.DataFrame, strategy: str) -> go.Figure:
    """持倉熱圖：每檔一列、時間為橫軸、色深=權重。

    列序按整段平均權重降序（資料驅動，無硬寫 ticker→類別對照）；y 軸反轉使最高者置頂。
    CASH 依其平均權重自然定位。取代舊 weight_stack 的堆疊面積（多資產下撞色、無直接標籤）。
    """
    w = weights[weights["strategy_id"] == strategy]
    wide = w.pivot_table(
        index="date", columns="ticker", values="weight", fill_value=0.0
    ).sort_index()
    order = list(wide.mean().sort_values(ascending=False).index)
    wide = wide[order]
    zmax = float(wide.to_numpy().max()) if wide.size else 1.0
    fig = go.Figure(
        go.Heatmap(
            z=wide.to_numpy().T,
            x=wide.index,
            y=order,
            zmin=0.0,
            zmax=zmax,
            colorscale=HEAT_SCALE,
            colorbar=dict(title="w", outlinewidth=0),
            hovertemplate="%{y} · %{x|%Y-%m-%d} · w=%{z:.1%}<extra></extra>",
        )
    )
    fig.update_yaxes(autorange="reversed")
    return style_dark(fig)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `.venv/Scripts/python.exe -m pytest tests/test_presentation/test_web_charts.py::test_holdings_heatmap_orders_by_mean_weight tests/test_presentation/test_web_charts.py::test_holdings_heatmap_single_ticker_ok -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add quantcore/presentation/web/charts.py tests/test_presentation/test_web_charts.py
git commit -m "feat(presentation): holdings_heatmap 持倉熱圖（列序按平均權重）"
```

---

### Task 2: `price_with_weight` 雙面板圖表函式

**Files:**
- Modify: `quantcore/presentation/web/charts.py`
- Test: `tests/test_presentation/test_web_charts.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_presentation/test_web_charts.py` 末尾新增：

```python
def test_price_with_weight_dual_panel_keeps_customdata():
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
    wser = pd.Series(
        [0.5, 0.6, 0.6, 0.7],
        index=pd.date_range("2020-01-01", periods=4, freq="D"),
    )
    fig = charts.price_with_weight(price, tr, wser, "SPY")
    names = {t.name for t in fig.data}
    assert "SPY price" in names
    assert "SPY w" in names
    buy = next(t for t in fig.data if t.name.endswith("buy"))
    assert buy.customdata is not None  # 保住點擊跳決策解剖契約
    wtrace = next(t for t in fig.data if t.name == "SPY w")
    assert wtrace.yaxis == "y2"  # 權重面積在下列


def test_price_with_weight_no_price_uses_fill():
    tr = pd.DataFrame(
        {
            "execution_date": pd.to_datetime(["2020-01-02"]),
            "side": ["buy"],
            "fill_price": [101.0],
        }
    )
    wser = pd.Series([0.5, 0.6], index=pd.date_range("2020-01-01", periods=2, freq="D"))
    fig = charts.price_with_weight(None, tr, wser, "SPY")
    buy = next(t for t in fig.data if t.name.endswith("buy"))
    assert list(buy.y) == [101.0]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.venv/Scripts/python.exe -m pytest tests/test_presentation/test_web_charts.py::test_price_with_weight_dual_panel_keeps_customdata -v`
Expected: FAIL，`AttributeError: ... has no attribute 'price_with_weight'`

- [ ] **Step 3: 實作 `price_with_weight`**

在 `charts.py` 檔頭 import 區下方（或既有 import 附近）確保有：

```python
from plotly.subplots import make_subplots
```

在 `COLORWAY` 下方新增模組常數：

```python
WEIGHT_PANEL_ROWS = [0.62, 0.38]
```

新增函式：

```python
def price_with_weight(price, trades_tk, weight_series, ticker: str) -> go.Figure:
    """單標的 價格+持倉 雙面板（取代 price_with_trades）。

    上列：adj_close 折線 + 買▲/賣▼ 標記（marker customdata=execution_date ISO，供點擊跳
    決策解剖——app.js 抓同一 graph div 不需改）。有 price 時標記 y 取當日 adj_close
    （reindex，缺值 NaN 不拋錯）；price 為 None 時取 fill_price。
    下列：組合對該檔權重（面積，tozeroy）。兩列共用時間軸。
    """
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=WEIGHT_PANEL_ROWS,
        vertical_spacing=0.04,
    )
    has_price = price is not None and len(price) > 0
    if has_price:
        fig.add_trace(
            go.Scatter(
                x=price.index, y=price.to_numpy(), name=f"{ticker} price", mode="lines"
            ),
            row=1,
            col=1,
        )
    for side, sym, col in (("buy", "triangle-up", UP), ("sell", "triangle-down", DOWN)):
        ts = trades_tk[trades_tk["side"] == side]
        if ts.empty:
            continue
        y = (
            price.reindex(ts["execution_date"]).to_numpy()
            if has_price
            else ts["fill_price"].to_numpy()
        )
        cd = [pd.Timestamp(d).date().isoformat() for d in ts["execution_date"]]
        fig.add_trace(
            go.Scatter(
                x=ts["execution_date"],
                y=y,
                mode="markers",
                name=f"{ticker} {side}",
                marker=dict(symbol=sym, size=10, color=col),
                customdata=cd,
            ),
            row=1,
            col=1,
        )
    if weight_series is not None and len(weight_series) > 0:
        fig.add_trace(
            go.Scatter(
                x=weight_series.index,
                y=weight_series.to_numpy(),
                name=f"{ticker} w",
                mode="lines",
                line=dict(width=0.5, color=AMBER),
                fill="tozeroy",
            ),
            row=2,
            col=1,
        )
    fig.update_yaxes(title="價格", row=1, col=1)
    fig.update_yaxes(title="權重", row=2, col=1, rangemode="tozero")
    return style_dark(fig)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `.venv/Scripts/python.exe -m pytest tests/test_presentation/test_web_charts.py::test_price_with_weight_dual_panel_keeps_customdata tests/test_presentation/test_web_charts.py::test_price_with_weight_no_price_uses_fill -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add quantcore/presentation/web/charts.py tests/test_presentation/test_web_charts.py
git commit -m "feat(presentation): price_with_weight 價格+持倉雙面板"
```

---

### Task 3: 路由與模板接新圖表

**Files:**
- Modify: `quantcore/presentation/web/routes/price_trades.py`
- Modify: `quantcore/presentation/web/routes/portfolio.py`
- Modify: `quantcore/presentation/web/templates/price_trades_content.html:28`
- Modify: `quantcore/presentation/web/templates/portfolio_content.html:5`

- [ ] **Step 1: price_trades 路由改接**

在 `routes/price_trades.py` 的 `price_trades()` 內：先把 `weights` 載入移到價格圖之前，並用 wide 取該檔權重序列。將現行「載入 panel/price 到 price_fig」段（約 76–92 行）改為：

```python
    snap_dir = readers.snapshot_dir_for_run(ctrl.run_dir)
    panel = readers.load_adj_close_panel(snap_dir) if snap_dir.exists() else None
    price = panel[tk] if (panel is not None and tk in panel.columns) else None

    weights = cache.read(ctrl.run_dir / "weights.parquet", lambda p: readers.load_weights(p.parent))
    w = weights[weights["strategy_id"] == strat]
    w_wide = w.pivot_table(
        index="date", columns="ticker", values="weight", fill_value=0.0
    ).sort_index()
    weight_tk = w_wide[tk] if tk in w_wide.columns else None
    price_fig = charts.to_fragment(
        charts.price_with_weight(price, tr[tr["ticker"] == tk], weight_tk, tk), "pt-price"
    )

    last_w = w_wide.iloc[-1].to_dict() if not w_wide.empty else {}
    ticker_rows = [
        {"ticker": t, "weight": last_w.get(t)} for t in sorted(set(tickers) | set(last_w))
    ]
```

註：此段取代原本的 `price_fig`（用 `price_with_trades`）、原本第二次載入 `weights` 與 `last_w`/`ticker_rows` 的計算，合併為一次 pivot。刪掉原檔中重複的 `weights = cache.read(...)`、`w = ...`、`last_w = ...`、`ticker_rows = ...` 幾行，避免重複載入。

- [ ] **Step 2: price_trades 的 stack_fig 改熱圖**

在同函式 `ctx.update(...)` 內，將：

```python
        stack_fig=charts.to_fragment(charts.weight_stack(weights, strat), "pt-stack"),
```

改為：

```python
        stack_fig=charts.to_fragment(charts.holdings_heatmap(weights, strat), "pt-stack"),
```

- [ ] **Step 3: portfolio 路由改熱圖**

在 `routes/portfolio.py` 的 `ctx.update(...)` 內，將：

```python
            stack_fig=charts.to_fragment(charts.weight_stack(weights, strat), "pf-stack"),
```

改為：

```python
            stack_fig=charts.to_fragment(charts.holdings_heatmap(weights, strat), "pf-stack"),
```

- [ ] **Step 4: 模板標題改字**

`templates/price_trades_content.html` 第 28 行：

```html
<h2 class="section-title">持倉隨時間（堆疊，{{ strategy }}）</h2>
```

改為：

```html
<h2 class="section-title">持倉熱圖（{{ strategy }}）</h2>
```

`templates/portfolio_content.html` 第 5 行卡標題：

```html
<div class="chart-card"><div class="chart-title">權重堆疊（{{ strategy }}，含現金）</div>{{ stack_fig|safe }}</div>
```

改為：

```html
<div class="chart-card"><div class="chart-title">持倉熱圖（{{ strategy }}）</div>{{ stack_fig|safe }}</div>
```

- [ ] **Step 5: 更新 portfolio 頁面 smoke 斷言**

`tests/test_presentation/test_web_pages.py` 的 `test_portfolio_has_weight_stack_and_cost` 內：

```python
    assert "權重堆疊" in r.text
```

改為：

```python
    assert "持倉熱圖" in r.text
```

- [ ] **Step 6: 執行頁面測試確認通過**

Run: `.venv/Scripts/python.exe -m pytest tests/test_presentation/test_web_pages.py -v`
Expected: all passed（含 `test_portfolio_has_weight_stack_and_cost`、`test_price_trades_flagship`）

- [ ] **Step 7: Commit**

```bash
git add quantcore/presentation/web/routes/price_trades.py quantcore/presentation/web/routes/portfolio.py quantcore/presentation/web/templates/price_trades_content.html quantcore/presentation/web/templates/portfolio_content.html tests/test_presentation/test_web_pages.py
git commit -m "feat(presentation): 兩頁堆疊圖改熱圖、價格圖改雙面板"
```

---

### Task 4: 移除死碼 `weight_stack` 與 `price_with_trades`

此時兩函式已無任何路由引用（Task 3 已全數改接）。移除函式與其單元測試。

**Files:**
- Modify: `quantcore/presentation/web/charts.py`
- Modify: `tests/test_presentation/test_web_charts.py`

- [ ] **Step 1: 確認無殘留引用**

Run: `git grep -n "weight_stack\|price_with_trades" -- quantcore/ tests/`
Expected: 只剩 `charts.py` 的函式定義與 `test_web_charts.py` 的兩個測試（`test_weight_stack_one_trace_per_ticker`、`test_price_with_trades_line_and_marks`）。若 `routes/` 仍有命中，回 Task 3 補改。

- [ ] **Step 2: 移除函式與測試**

在 `charts.py` 刪除 `def weight_stack(...)` 整個函式與 `def price_with_trades(...)` 整個函式。
在 `tests/test_presentation/test_web_charts.py` 刪除 `test_weight_stack_one_trace_per_ticker` 與 `test_price_with_trades_line_and_marks` 兩個測試函式。

- [ ] **Step 3: 執行圖表測試確認通過**

Run: `.venv/Scripts/python.exe -m pytest tests/test_presentation/test_web_charts.py -v`
Expected: all passed，無 `weight_stack`/`price_with_trades` 相關項

- [ ] **Step 4: Commit**

```bash
git add quantcore/presentation/web/charts.py tests/test_presentation/test_web_charts.py
git commit -m "refactor(presentation): 移除死碼 weight_stack / price_with_trades"
```

---

### Task 5: 全前端測試 + 架構守護 + 人工驗證

**Files:** 無（僅驗證）

- [ ] **Step 1: 跑整個 presentation 測試套件**

Run: `.venv/Scripts/python.exe -m pytest tests/test_presentation/ -v`
Expected: all passed（特別留意 `test_architecture.py` 架構守護、`test_web_pages.py`、`test_web_charts.py`）

- [ ] **Step 2: 人工驗證雙面板互動（啟動 dashboard）**

Run:
```bash
.venv/Scripts/python.exe -m uvicorn quantcore.presentation.web.app:app --port 8000
```
瀏覽 `http://localhost:8000/price-trades?run=2026-07-29_2347_canonical_dcc&focus=full`，確認：
1. 頂端為 價格+持倉 雙面板、時間軸對齊；點價格圖 買▲/賣▼ 標記會跳到該日決策解剖頁。
2. 下方「持倉熱圖」每檔一列、標籤清楚、無撞色。
3. `/portfolio?run=2026-07-29_2347_canonical_dcc&focus=full` 的堆疊卡已變熱圖。

- [ ] **Step 3: 確認驗收條件（AC）全數達成**

對照 spec §驗收條件 1–4 逐項打勾：兩頁堆疊→熱圖、雙面板+跳頁、`weight_stack` 已移除無殘留、測試全綠。

---

## Self-Review 記錄

- **Spec 覆蓋：** 熱圖(§A)→Task 1；雙面板(§B)→Task 2；接線(§接線改動)→Task 3；移除 weight_stack(§C)→Task 4；測試計畫(§測試計畫)→Task 1/2/3/5；AC→Task 5。price_with_trades 移除為計畫對「不留死碼」原則的延伸（spec §C 僅列 weight_stack，已於計畫前言與 Task 4 標明）。
- **Placeholder 掃描：** 無 TBD/TODO；每個 code step 附完整程式碼。
- **型別/命名一致：** `holdings_heatmap(weights, strategy)`、`price_with_weight(price, trades_tk, weight_series, ticker)`、常數 `HEAT_SCALE`、`WEIGHT_PANEL_ROWS` 在各 Task 用法一致；`div_id` 沿用既有 `pt-price`/`pt-stack`/`pf-stack`。
