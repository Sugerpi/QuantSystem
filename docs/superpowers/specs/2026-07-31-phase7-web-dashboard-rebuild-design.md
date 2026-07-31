# Phase 7（重製）— Web Dashboard 重製設計文件（FastAPI + Jinja2 + HTMX + Plotly）

> 規格來源：`DEVELOPMENT_GUIDE v1.2.md` §9（Phase 7）/ §11.1–11.3（Dashboard / Run Lab）/ §2.2（依賴方向）/ §6.2（Diagnostics）。
> 本文件為 brainstorming 定案，作為 writing-plans 的輸入。日期：2026-07-31。
> 前置：Phase 0–6 全部完成；Phase 7a 唯讀 Streamlit dashboard 9 頁已完成、AC① 達成（分支 `feature/phase7a-dashboard`）。
> **本文件取代 Phase 7a 的 Streamlit 展示層**（`app.py` + `pages/` + Streamlit `controls.py`），改用伺服器渲染的 Web 前端。**引擎、快照、`runs/` 產物、`readers.py`、Phase 7a 計畫 1 的引擎診斷落盤一律不動。**

---

## 0. 背景與問題陳述

Phase 7a 的唯讀 dashboard 用 Streamlit 實作。使用者實測後，四類問題並存：

1. **會崩潰／功能壞**：一個例外整頁掛（如「開啟即崩潰」——側欄預設選到非回測 run 就 `FileNotFoundError`）。
2. **醜／不專業**：Streamlit 預設版面與樣式天花板，做不出使用者要的專業 quant dashboard 樣子。
3. **慢／卡頓**：每次切頁、拉 slider、選 run 都整頁重跑、重讀 parquet。
4. **難改**：想調版面或行為時，被 Streamlit 的抽象綁死，難以精準控制 HTML/CSS。

使用者定案：**整層換掉 Streamlit 展示層**，改用能完全控制外觀的 Web 前端；深色 Bloomberg 終端風；**「價格與交易」頁為旗艦頁，功能最完整**。

### 0.1 明確不做的事（範圍護欄）

- **不上資料庫**。`runs/` 下的 parquet/JSON 是引擎輸出、被 INV-6（`(config, snapshot_hash, git_commit)` 決定輸出）與 content hash 鎖定的**唯一真相來源**。引入 DB 等於多一個真相來源 + `runs/`→DB 同步層 = 新 bug 面。展示層繼續**直接讀檔**。此決策明確記錄在案。
- **不動引擎、快照、`runs/` 產物格式、`readers.py`**。爆炸半徑限縮在 `presentation/` 的展示層。
- **不改回測科學結論**，不重跑回測（除非落盤格式需要——本次不需要）。
- **不做多人／登入／雲端部署**。localhost 單人；demo 時使用者自行反向代理。

---

## 1. 架構決策與取捨（為何是 FastAPI + Jinja2 + HTMX + Plotly）

### 1.1 硬約束先收斂選項

- **必須有 Python 後端**：§11.3 Run Lab 要以 subprocess 啟動回測、追 `status.json` 心跳、崩潰復原（CLAUDE.md：`presentation/` 啟動回測只能以 subprocess 呼叫引擎 CLI）。純靜態 HTML/CSS/JS 做不到 → 一定有 Python 伺服器。
- **§2.2 行程邊界**：`presentation/` 永不 import 引擎，只讀 `runs/`、`snapshots/`，啟動回測只走 subprocess。此邊界對新前端**原封保留**，由 AST 架構守護測試強制。
- **使用者無前端背景**：維護成本要低，盡量留在 Python，避免自建 JS build 工具鏈。

### 1.2 三方案（brainstorming 已定案 A）

- **方案 A（採用）— FastAPI + Jinja2 + HTMX + Plotly（伺服器渲染）**：後端 Python，頁面真 HTML 模板（外觀全可控），互動用 HTMX（點一下只換一小塊 HTML 片段、幾乎不寫 JS），圖表續用 Plotly（沿用 Phase 7a 圖表邏輯）。原生支援 Run Lab（subprocess + SSE 進度）。95% 程式碼仍是 Python。
- **方案 B（補充，非主線）— 純 Python 產生自足靜態 HTML 報告**：零伺服器、可寄送、好看，但做不到 Run Lab 與伺服器互動。**保留給 7c 研究報告輸出**，不當完整 dashboard 替代。
- **方案 C（否決）— FastAPI JSON API + React/Vue SPA**：外觀最強但需維護整套 JS 前端 + node/vite build，對無前端背景者維護成本最高、localhost 單人殺雞用牛刀。

「換另一個 Python UI 框架（Dash/NiceGUI）」同樣被框架抽象與樣式天花板綁住、壞掉時在 debug 框架——不解決使用者「要能控制 HTML/CSS」的核心訴求，故不採。

### 1.3 各痛點如何被 A 對症

| 痛點 | A 的處理 |
|------|---------|
| 崩潰 | 明確路由 + 每個路由 try/except 回「本次未儲存／此頁不適用」片段；一頁的錯誤不影響其他頁與導覽。 |
| 醜 | 真 HTML/CSS，深色 Bloomberg 主題單一 CSS 檔可控。 |
| 慢 | 後端 `functools.lru_cache` + 檔案 mtime 失效快取讀檔；HTMX 只重繪需要的片段，不整頁重跑。 |
| 難改 | 版面 = 模板 + CSS；行為 = Python 路由。想改哪塊改哪塊。 |

---

## 2. 目標架構

### 2.1 行程邊界（§2.2，維持不變）

```
config ← data ← models ← signals/portfolio ← backtest ← experiments ← presentation
```

`presentation/`（含新 `web/`）**只**：
- 讀 `runs/`、`snapshots/` 的 parquet/JSON（經 `readers.py`）。
- 啟動回測**只以 subprocess 呼叫引擎 CLI**（Run Lab，§11.3）。
- 永不 `import quantcore.{config,data,models,signals,portfolio,backtest,experiments}`。

由既有 AST 架構守護測試（`tests/test_presentation/test_architecture.py`）**擴至新 `web/` 全樹**強制。新增白名單：web 層可 import `fastapi` / `starlette` / `jinja2` / `plotly` / `pandas` / stdlib / `quantcore.presentation.{readers,web.*}`；**引擎模組一律紅燈**。`readers.py` 維持只 import stdlib/pandas/yaml。

### 2.2 目錄結構

```
quantcore/presentation/
  readers.py                 # 不動（資料層，16 純函數）
  web/
    __init__.py
    app.py                   # FastAPI app factory：掛路由、靜態檔、模板引擎、快取
    controls.py              # 全域選擇：從 query string 解析 run/strategy/date（取代 st.session_state）
    charts.py                # Plotly figure builders：收 DataFrame → to_html 片段（純函數，可獨立測）
    cache.py                 # 讀檔快取：以 (path, mtime) 為鍵，包一層 readers
    routes/
      __init__.py            # APIRouter 匯總
      overview.py            # 頁 1
      decisions.py           # 頁 2（AC①）
      garch.py               # 頁 3
      correlation.py         # 頁 4
      portfolio.py           # 頁 5
      ablation.py            # 頁 6
      data_quality.py        # 頁 7
      run_lab.py             # 頁 8（7b）
      price_trades.py        # 頁 9（旗艦）
    templates/
      base.html              # 骨架：左導覽 + 頂部控制列 + {% block content %}
      _sidebar.html
      _controls.html
      overview.html … price_trades.html
      fragments/             # HTMX 局部片段（*.html）
    static/
      css/app.css            # 深色 Bloomberg 主題（單一來源）
      js/htmx.min.js         # 本機 vendored（不依賴外網 CDN）
      js/plotly.min.js       # 本機 vendored
      js/app.js              # 少量膠水：Plotly 點擊事件 → HTMX/導覽
  jobs.py                    # Run Lab：subprocess 啟動 + status.json 合約（7b）
```

**移除**（Streamlit 展示層退役）：`presentation/app.py`（Streamlit 入口）、`presentation/pages/`、`presentation/controls.py`（Streamlit 版）、對應的 `tests/test_presentation/test_app_smoke.py` 與 `test_controls.py`（AppTest 冒煙）。`readers.py` 與其測試保留。

### 2.3 啟動方式

- 舊：`uv run streamlit run quantcore/presentation/app.py`
- 新：`uv run uvicorn quantcore.presentation.web.app:app`（或包一個 `quantcore.presentation.web` 的 `__main__`／CLI；localhost 預設 `127.0.0.1:8000`）。
- `pyproject` 依賴：**移除** `streamlit`；**新增** `fastapi`、`uvicorn[standard]`、`jinja2`。`plotly`/`scipy`/`pandas` 續留。htmx.js/plotly.js 以靜態檔 vendored，不進 Python 依賴。

### 2.4 全域控制列（狀態模型：query string，非 session）

Streamlit 用 `st.session_state`；Web 版改用 **URL query string** 承載全域選擇——好處：可分享/加書籤、HTMX 片段天然帶參數、無隱藏狀態。

- `?run=<name>&strat=full,mom_ivol&from=2010-01-01&to=2020-12-31`
- `web/controls.py` 純函數 `parse_controls(query_params, runs_root) -> Controls`（含預設：無 `run` 時選最新的**回測** run，比照 Phase 7a 的 `is_backtest_run` 防呆，不落到 vol_eval/ablation）。可獨立單元測試（不需起伺服器）。
- 頂部控制列每頁共用（`_controls.html`）；換 run/策略 → HTMX `hx-get` 當前頁、只換內容區。

---

## 3. 前端互動模型（HTMX + Plotly，最少 JS）

### 3.1 頁面載入

- 每頁一個 GET 路由回**整頁**（`base.html` + 該頁 `{% block content %}`）。
- 左導覽點擊 = 一般 `<a href>`（整頁換），或 `hx-get` + `hx-target="#content"` 只換內容區（更快、不閃）。採後者，導覽列與控制列不重繪。

### 3.2 局部互動（HTMX 片段）

「換 ticker、拉日期、切策略、翻 blotter 頁」等 = `hx-get` 一個 `/fragments/...` 路由，回一小塊 HTML（含新的 Plotly div），`hx-target` 換掉對應區塊。**不整頁重跑**。

### 3.3 圖表（Plotly，伺服器產生）

- `charts.py` 收 DataFrame → `plotly.graph_objects.Figure` → `fig.to_html(include_plotlyjs=False, full_html=False, div_id=...)` 回片段。plotly.js 由 `base.html` 一次載入（vendored）。
- 圖表互動（縮放/hover/圖例開關）走 Plotly 客戶端，零後端往返。
- 深色主題：`charts.py` 統一套一個 Bloomberg 風 Plotly template（黑底、格線 `#1c1c1c`、字色 `#d8d8d3`、琥珀 accent、漲綠 `#26a65b`/跌紅 `#e0483e`），集中一處定義。

### 3.4 跨圖表事件（旗艦頁需要）

- Plotly `plotly_click` 事件 → `app.js` 極少量膠水：讀點擊點的 `customdata`（如決策日）→ `htmx.ajax('GET', '/decisions/fragment?...', ...)` 或導覽跳頁。
- 這是唯一需要手寫 JS 的地方，約數十行、集中在 `app.js`。

---

## 4. 深色 Bloomberg 主題（`static/css/app.css`）

單一 CSS 檔，CSS 變數集中定義（呼應「無魔術數字散落」精神，樣式 token 單一來源）：

- 底/面板：`--bg:#000`、`--panel:#0a0a0a`、`--panel-2:#121212`、`--border:#2a2a2a`、`--border-soft:#1f1f1f`。
- 文字：`--fg:#d8d8d3`、`--fg-dim:#8a8a82`、`--fg-faint:#5a5a52`。
- Accent：`--amber:#ff8c1a`（品牌/選中/表頭）。
- 語意：`--up:#26a65b`、`--down:#e0483e`、`--blue:#3a6ea5`、`--gold:#e8b64a`。
- 字體：數字/表格一律等寬（`ui-monospace, Menlo, monospace`）；標題可用系統 sans。
- 密度高、格線細、留白克制——終端機感。
- **深色為唯一主題**（使用者指定 Bloomberg 風）；不做亮色切換（YAGNI；日後要再加）。

---

## 5. 九頁內容規格

原則：**薄路由、胖 `readers`/`charts`**。頁面內容沿用 Phase 7a 已驗證的資料對照（§1 資料就緒盤點、§2 六層對照仍有效），只換渲染層。缺 artifact（舊 run 無 `trades.parquet`/`model_details/`）→ 片段回「本次未儲存」，不崩潰。非回測 run（無 `nav`）→ nav 類頁回「此頁需回測 run」。

| # | 頁 | 內容（沿用 Phase 7a） | 資料來源 |
|---|----|------|------|
| 1 | 總覽 | KPI 卡（Sharpe/MaxDD/Calmar/年化波動）、NAV 對數疊圖、回撤、曝險 E(t)、子期間分解 | `nav`/`metrics.json`/`decisions.exposure_applied` |
| 2 | 決策解剖（**AC①**） | 六層瀑布（a 合格→b 動量→c absmom→d σ̂→e 曝險展開→f 目標權重），讀 `decision_layers` | `decisions.parquet`（六層全備）+ `weights`/`nav` |
| 3 | GARCH | (ω,α,β,ν) 參數軌跡、persistence α+β、fallback 頻率、QLIKE/MZ-R² 表、殘差 QQ+ACF | `decisions.garch_params`/`vol_fell_back`、`runs/vol_eval/`、`model_details/residuals` |
| 4 | 相關結構 | 相關矩陣熱圖（時間滑桿）、資產對相關序列、DCC vs EWMA 疊圖（頁內第二 run） | `model_details/correlation.parquet` |
| 5 | 組合與成本 | 權重堆疊面積、曝險帶事件（band_blocked）、換手/成本 | `weights`/`decisions.band_blocked`/`nav.turnover,cost` |
| 6 | 消融 | 指標表、敏感度熱圖、配對 bootstrap CI（含 0 與否） | `comparison.parquet`/`bootstrap.parquet` |
| 7 | 資料品質 | MANIFEST、資料源、overrides 裁決、tickers | 快照 `MANIFEST.json`/`metadata.json` |
| 8 | 回測工作台（**7b**） | 見 §7 | Run Lab jobs + `status.json` |
| 9 | 價格與交易（**旗艦**） | 見 §6 | `trades`/`weights`/`decisions`/ 快照 `prices` |

> 沿用 Phase 7a backlog（誠實記錄，仍延）：頁 3「條件波動 vs 已實現波動 proxy 疊圖」、「手刻 vs arch parity 對照頁籤」（後者卡引擎未落盤 parity artifact）。本次重製不承諾這兩項；重製完成後再議。

---

## 6. 旗艦頁 — 價格與交易（頁 9）完整規格

目標（使用者原話）：**完整看到模型在回測期間每一天做了什麼 + 每個標的怎麼走**。四元件：

### 6.1 主價格面板
- 選定標的的 `adj_close` 折線（快照 `prices.parquet`，`readers.load_adj_close_panel`）。
- 疊上**只屬於這檔**的成交標記：買進綠 ▲、賣出紅 ▼，標在該檔實際成交日（`trades.parquet` 篩該 ticker）。
- 標記帶 `customdata=決策日`；**點標記 → 跳頁 2 決策解剖該日**（§3.4），把「走勢」接到「那天為何這樣做」。
- 支援日期範圍縮放（Plotly 內建 + 控制列 `from/to`）。

### 6.2 右側標的列表
- 全 20 檔，各顯示「目前選定日的持有權重」長條（`weights.parquet`）；未持有灰掉。
- 點任一檔 → `hx-get` 主面板片段換成該檔（只換左側面板）。
- 頂部含 CASH 佔比。

### 6.3 成交明細（Blotter）
- 逐筆成交表：`DATE / TICKER / SIDE(BUY綠·SELL紅) / Δw / FILL / COST(bps)`，等寬密排。
- 依 ticker、日期範圍篩（HTMX 片段）；分頁（後端 slice，避免一次吐 25k 列）。
- 常駐顯示對帳保證 `Σ|Δw|＝turnover ✓`、`Σcost＝cost ✓`（Phase 7a 已做到逐執行日零誤差的誠實閘門，直接呈現）。

### 6.4 持倉隨時間堆疊帶
- 整個回測期「何時持有哪些資產」的堆疊面積全景（`weights.parquet`）；點某時段可連動主面板日期。

**資料全部現成**：`trades.parquet`（Phase 7a 計畫 1 落盤，~25,800 筆/run，已對帳）、`weights.parquet`、`decisions.parquet`、快照 `prices.parquet`。**引擎不動。**

---

## 7. Run Lab（頁 8，7b）— subprocess + status.json + 崩潰復原

沿用 §11.3 合約，用 Web 實作（比 Streamlit 更自然）：

- **提交**：表單（選 base config + 覆寫參數）→ POST → `jobs.py` 以 **subprocess** 起引擎 CLI（`python -m quantcore.experiments.runner ...`，**非 import**）。回 job id。
- **status.json 合約**：job 目錄下 `status.json`（`state`=queued/running/done/failed、`pct`、`stage`、`started_at`、`heartbeat_at`、`run_dir`、`error`）。引擎 CLI 定期寫心跳（引擎端最小改動：一個 status writer，屬 7b 引擎工作）。
- **進度**：頁面 `hx-get` 輪詢 `status.json`，或 SSE 推送，畫進度條。
- **崩潰復原（AC③）**：狀態**只**存 `status.json`（檔案），UI 行程無狀態。UI 重啟後掃 job 目錄重建列表；running job 由 `heartbeat_at` 逾時判定存活。**杜絕記憶體內 job 狀態**。
- **AC②**：從頁面提交新 config 並完整跑完，全程不碰終端機。

> 7b 需要引擎端補一個 `status.json` 心跳 writer（subprocess 內），這是唯一的引擎端新增，且在 `experiments/` CLI 層、不違反依賴方向。

---

## 8. 錯誤處理、效能、可靠性

- **錯誤隔離**：每個路由/片段 try/except；資料缺 → 語意化片段（「本次未儲存」「此頁需回測 run」「查無此決策日」），HTTP 200 + 提示，不 500、不整站掛。真正的損壞（回測 run 缺 nav）仍誠實顯示錯誤（比照 `is_backtest_run` docstring：不掩蓋損壞）。
- **效能**：`cache.py` 以 `(path, mtime)` 為鍵 `lru_cache` 包 `readers`，重複讀同一 run 不重讀 parquet；HTMX 只換片段。Blotter 後端分頁。大圖（NAV 全期）可降採樣（決定性、不影響科學數字，只影響像素）。
- **無外網**：htmx.js/plotly.js vendored 本機；符合「不直連網路」精神（雖該規則主要指回測資料）。

---

## 9. 測試策略（取代 Streamlit AppTest）

- **架構守護（紅綠燈）**：擴 `test_architecture.py` 的 AST 掃描至 `web/` 全樹——引擎 import 一律紅燈；`readers.py` 維持只 stdlib/pandas/yaml。保留 Phase 7a 抓到的 bypass 修正（`from quantcore import backtest` 展開 `PKG.NAME`）。
- **純函數單元測試**：`web/controls.py`（query 解析 + 預設回測 run 防呆）、`charts.py`（figure 結構/資料對映）、`cache.py`（mtime 失效）——不需起伺服器。
- **路由整合測試**：FastAPI `TestClient`（starlette/httpx），對 fixture run 斷言各頁 GET 200、含關鍵數字、缺 artifact 回優雅片段、非回測 run 回提示、HTMX 片段正確。**移植 Phase 7a 的「開啟即崩潰」回歸**（預設不選 vol_eval）與 **AC① golden**（`decision_layers` 六層對上獨立解析）。
- **AC① 保持**：頁 2 對真實 `canonical_ewma`/full/2016-04-06 六層 11 項 vs `decisions.parquet` 逐格一致（Phase 7a `docs/phase7a-ac1-handcheck.md` 的手查於新 UI 重驗一次）。
- 全套 `uv run pytest` 綠、`requires_snapshot` 本機閘門照跑、ruff 乾淨、INV-3/5/6 不受影響（未動引擎）。

---

## 10. 交付切段（供 writing-plans 切計畫）

建議三段（各自 spec→plan→實作→review，比照歷來 Phase）：

- **計畫 1 — Web 地基**：`pyproject` 換依賴、`web/app.py` factory、`base.html` 骨架（左導覽 + 頂部控制列）、`app.css` 深色 Bloomberg 主題、`controls.py`（query 解析）、`cache.py`、`charts.py` Plotly 深色 template、擴 AST 架構守護、vendored htmx/plotly、`TestClient` 冒煙。**退役 Streamlit `app.py`/`pages/`/`controls.py` 與其測試。**
- **計畫 2 — 九頁唯讀（含旗艦頁 9）**：頁 1–7、9 內容移植 + 旗艦頁 9 四元件 + 跨圖表點擊事件；頁 8 先 stub。AC① 於頁 2 重驗（自動 golden + 人工手查）。
- **計畫 3 — Run Lab（7b）**：`jobs.py` subprocess + `status.json` 合約 + 引擎端心跳 writer + 崩潰復原；AC②③。
- （7c 研究報告沿用方案 B 靜態 HTML 輸出，獨立於本重製，之後另議。）

AC 對映：**AC①** 於計畫 2 保持；**AC②③** 於計畫 3 達成。三者皆為 §9 Phase 7 原 AC，不因換前端而改變。

---

## 11. 待決／已決事項

- **已決**：不上 DB（§0.1）；深色單一主題（§4）；狀態走 query string（§2.4）；Streamlit 退役（§2.2）；旗艦頁四元件（§6）。
- **待使用者確認（spec review 時）**：計畫切段是否照 §10 三段；頁 8 Run Lab 是否確定納入本次重製（或先只做唯讀 8 頁 + 頁 8 stub、7b 之後再做）。
