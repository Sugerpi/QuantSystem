# 持倉視覺化改版 — 設計文件

- 日期：2026-08-12
- 範圍：`quantcore/presentation/web`（呈現層，不 import 引擎）
- 動機：計畫外改進。「價格與交易」頁的持倉隨時間堆疊圖（`weight_stack`）在 `full`
  策略下有 20 檔 + CASH，而 `COLORWAY` 只有 6 色會循環撞色，加上堆疊面積僅靠圖例對照、
  無直接標籤，導致「哪條帶是哪檔」讀不出來；且該圖完全沒有股價，看不出「艙位變化 vs 股價」
  的關係。

## 目標

1. 用**持倉熱圖**取代堆疊面積，把「模型總體決策（輪動）」呈現清楚，消除撞色與標籤問題。
2. 新增**單標的 價格+持倉 雙面板**，直接呈現「股價走勢 vs 組合在該檔的權重」的時間對齊關係。

## 非目標（YAGNI）

- 熱圖點列切換標的、群組分隔線、ticker→類別對照表 config 化：先不做。
- KPI 卡、其他頁面配色、其他頁面版面：不動。
- 保留 `weight_stack`：兩處都不再使用，移除以免死碼。

## 架構邊界（沿用 CLAUDE.md）

- 所有改動限於 `presentation/`，不 import 引擎，只讀 `runs/`、`snapshots/` 產物。
- 新圖表函式放 `charts.py`，沿用既有深色主題 token（`BG/FG/GRID/UP/DOWN/AMBER`）。
- 新增的樣式常數（色階停點、`row_heights`）為呈現層樣式，與現有 `COLORWAY/margins`
  同類，放 charts.py 模組常數；非 CLAUDE.md 所指「策略魔術數字」。

## 元件設計

### A. `charts.holdings_heatmap(weights, strategy) -> go.Figure`

取代 `weight_stack`。

- 輸入：`weights` 長格式 DataFrame（date, strategy_id, ticker, weight）、`strategy` 字串。
- 處理：
  - 篩該策略 → `pivot_table(index=date, columns=ticker, values=weight, fill_value=0.0)`
    並 `sort_index()`（沿用原 `weight_stack` 的 pivot 慣例）。
  - 列順序：**按整段平均權重降序**排序欄（資料驅動，無硬寫對照表）。universe 換標的
    亦不需改程式。CASH 依其平均權重自然定位。
- 圖形：`go.Heatmap`
  - `z` = 寬表轉置（列=ticker、欄=date）、`x` = 日期、`y` = 排序後 ticker 清單。
  - `colorscale` = 黑→琥珀漸層（模組常數 `HEAT_SCALE`，例：
    `[[0,"#000000"],[0.15,"#241a08"],[0.5,"#ff8c1a"],[1,"#ffe1b0"]]`）。
  - `zmin=0`、`zmax=float(wide.values.max())`。
  - `colorbar(title="w")`。
  - `hovertemplate = "%{y} · %{x|%Y-%m-%d} · w=%{z:.1%}<extra></extra>"`。
  - y 軸 `autorange="reversed"`（平均權重最高者排最上）。
- 套 `style_dark`。

### B. `charts.price_with_weight(price, trades_tk, weight_series, ticker) -> go.Figure`

取代價格與交易頁頂端的 `price_with_trades`。

- 輸入：
  - `price`：該檔 adj_close Series（index=date）或 None（沿用 `price_with_trades` 慣例）。
  - `trades_tk`：該檔交易（execution_date/side/fill_price）。
  - `weight_series`：該檔在組合中的權重 Series（index=date）；缺則傳空/0 序列。
  - `ticker`：字串。
- 圖形：`plotly.subplots.make_subplots(rows=2, cols=1, shared_xaxes=True,
  row_heights=WEIGHT_PANEL_ROWS)`，`WEIGHT_PANEL_ROWS=[0.62,0.38]` 為模組常數。
  - 上列（row=1）：價格線 + 買▲(UP,triangle-up)/賣▼(DOWN,triangle-down)標記。
    - **保留 marker 的 `customdata`**（execution_date ISO 字串），維持「點標記跳決策解剖」。
      有 `price` 時標記 y 取 `price.reindex(execution_date)`；否則取 `fill_price`
      （沿用 `price_with_trades` 既有邏輯）。
  - 下列（row=2）：`weight_series` 面積（`fill="tozeroy"`），琥珀色。`rangemode="tozero"`。
  - 兩列共用 x 軸，時間對齊。
- 套 `style_dark`。

### 相容性：決策解剖點擊跳頁

`static/js/app.js` 的 `wirePriceClick` 抓 `#pt-price-wrap` 內第一個 `.plotly-graph-div`、
綁 `plotly_click`、讀 `customdata`。改用雙面板後仍是**單一 graph div**、標記仍帶 `customdata`，
故互動不需改 app.js。（實作後需人工驗證點擊仍跳對日期。）

### C. 移除 `weight_stack`

`holdings_heatmap` 取代其兩處用途後，`weight_stack` 成死碼 → 移除函式與其對應測試。

## 接線改動

| 檔案 | 改動 |
|------|------|
| `web/routes/price_trades.py` | `price_fig` 改呼叫 `price_with_weight`，需從已載入的 `weights` 取該檔（`tk`）權重序列傳入；`stack_fig` 改呼叫 `holdings_heatmap(weights, strat)`。 |
| `web/routes/portfolio.py` | `stack_fig` 改呼叫 `holdings_heatmap(weights, strat)`。 |
| `web/templates/price_trades_content.html` | 「持倉隨時間（堆疊，…）」區塊標題改為「持倉熱圖（…）」。頂端價格圖區塊不改結構（仍 `#pt-price-wrap` 包 `price_fig`）。 |
| `web/templates/portfolio_content.html` | 「權重堆疊（…，含現金）」卡標題改為「持倉熱圖（…）」。 |
| `web/charts.py` | 新增 `holdings_heatmap`、`price_with_weight` 與模組常數 `HEAT_SCALE`、`WEIGHT_PANEL_ROWS`；移除 `weight_stack`。 |

price_trades 路由取權重序列的方式：route 已 `cache.read` 載入 `weights` 並 `w = weights[
weights.strategy_id==strat]`；由 `w.pivot`（或篩 `w[w.ticker==tk]` 對齊日期）取 `tk` 的
權重序列。實作時以現有 pivot 結果取欄，避免重複讀檔。

## 資料流（改版後，價格與交易頁）

```
GET /price-trades?run=…&focus=…&tk=…
  → routes/price_trades.py
      readers.load_trades / load_weights / load_adj_close_panel（皆經 cache）
      price_series = panel[tk]；weight_series = weights_wide[tk]
      charts.price_with_weight(price_series, trades_tk, weight_series, tk) → 上圖片段
      charts.holdings_heatmap(weights, strat)                            → 熱圖片段
  → templates/price_trades_content.html 直接嵌入片段
```

readers 層無需新增函式（`load_weights`、`load_adj_close_panel`、`load_trades` 已足夠）。

## 測試計畫

- 新增 `holdings_heatmap` 單元測試：
  - 回傳含單一 `Heatmap` trace；`y` 為按平均權重降序的 ticker 清單；`z` 形狀 = (n_ticker, n_date)；`zmin=0`。
  - 空/單標的策略（如 bh_spy）不炸。
- 新增 `price_with_weight` 單元測試：
  - 上列有價格線與（有交易時）買/賣標記；買/賣標記帶 `customdata`（ISO 日期字串），保住跳頁契約。
  - `price=None` 時以 `fill_price` 定位標記、不炸。
  - 下列有權重面積 trace。
- 更新既有測試：移除/改寫引用 `weight_stack` 的測試；確認引用 `price_with_trades` 之處已改。
- 兩頁路由 smoke test：`/price-trades`、`/portfolio` 對 canonical run 回 200 且含熱圖 div。
- 人工驗證（實作後）：點上圖買/賣標記仍跳對應日期的決策解剖頁。

## 驗收條件（AC）

1. 「價格與交易」「組合與成本」兩頁的堆疊圖皆換為持倉熱圖，`full` 策略下每檔一列、
   標籤清楚、無撞色。
2. 「價格與交易」頁頂端為價格+持倉雙面板，時間軸對齊；點價格圖買/賣標記仍跳決策解剖頁。
3. `weight_stack` 已移除，無殘留引用。
4. 既有前端測試全綠；新圖表函式有對應測試。
