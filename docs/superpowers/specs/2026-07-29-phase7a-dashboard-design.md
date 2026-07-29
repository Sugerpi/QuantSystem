# Phase 7a — Dashboard 唯讀頁面 + 引擎診斷落盤設計文件

> 規格來源：`DEVELOPMENT_GUIDE v1.2.md` §9（Phase 7）/ §11.1–11.2（Dashboard）/ §6.2（Diagnostics）/ §2.2（依賴方向）。
> 本文件為 brainstorming 定案，作為 writing-plans 的輸入。日期：2026-07-29。
> 前置：Phase 0–6 全部完成（引擎、七策略、GARCH/DCC/ERC、消融機器齊備；快照 `2026-07-16_20ed09` 在本機）。

## 0. 範圍與邊界

Phase 7 = **7a（唯讀頁面 + 引擎診斷落盤，本文件）** + 7b（Run Lab / status.json / 崩潰復原）+ 7c（研究報告）。

7a 交付**唯讀 Streamlit dashboard 的 9 頁**（§11.2 原 8 頁，第 8 頁 Run Lab 在 7a 只放 stub、7b 才建；新增第 9 頁「價格與交易」）+ **引擎端補齊 dashboard 所需但當初未落盤的診斷**（相關矩陣、標準化殘差、`corr_fell_back`、trade blotter）+ **重跑 2 個 canonical run**。

### 7a 的 AC（本段驗收）

- **AC①（本段唯一硬 AC，來自 §9 Phase 7 第一關）**：任選一個歷史決策日，Decision Explorer 六層數字與 `decisions.parquet` 手查逐格一致。
  - 自動化形式：`readers.py` 的六層抽取函數對 fixture run 的 golden 測試。
  - 人工形式：對真實 canonical run 任選一日，六層 vs `decisions.parquet` 手查，寫成文件。
- AC②③（Run Lab 提交回測全程不碰終端機、UI 崩潰重啟 job 狀態無損）**屬 7b，不在本段**。

### 7a 硬邊界

- `presentation/` **永不 import 引擎模組**（§2.2）。只讀 `runs/`、`snapshots/` 的 parquet/JSON。由**架構守護測試**（AST 白名單）把此邊界變成紅綠燈。
- 引擎診斷落盤動到 Phase 5-硬化的決策熱路徑 → **INV-3（Σ 合法）、INV-5（會計恆等式）、INV-6（可重現）改完必須全綠**。
- 新落盤欄位/檔案一律 optional：舊 run 缺 `model_details/` 或 `trades.parquet` 時，對應頁面顯示「本次未儲存」而非崩潰（§11 line 487，斷 `store_details` pickle 舊教訓）。
- 禁用 pickle；序列化一律 parquet/JSON（CLAUDE.md）。
- 任何參數不得出現在 `config/` 以外。

### 已具備、不重做

- `decisions.parquet` 已含 Decision Explorer 六層所需的**全部欄位**（實測驗證，見 §2）：`eligible`/`momentum_scores`/`absmom`/`sigma_hat`/`w_risky`/`sigma_p`/`exposure_raw`/`exposure_applied`/`band_blocked`/`vol_fell_back`/`garch_params`/`target_weights`。
- `nav.parquet`（nav/turnover/cost）、`weights.parquet`（date×strategy×ticker×weight）、`metrics.json`（含子期間 + block bootstrap CI）、`manifest.json`（snapshot_id/git_commit/config_hash，INV-6）。
- 消融：`experiments/ablation.py` 產 `comparison.parquet`（頁 6 直接讀）。
- 快照 `metadata.json`（overrides 裁決清單、跨源差異，頁 7 直接讀）。
- 引擎內部已算出但未落盤的中間值：相關矩陣 `R`（`vol_target_base._build_cov`）、`corr_fell_back`（`CorrelationForecaster`）、per-ticker Δweight（`accounting.turnover` 內部）、標準化殘差（`_collect_std_residuals`）。7a 是**把已算的接出來**，非新計算。

---

## 1. 資料就緒盤點（設計依據）

實測 `runs/2026-07-24_2019_phase4_validation`，逐頁對照「現有 artifact 能畫的 / 缺的」：

| # | 頁面 | 現有 artifact 足夠 | 缺、需引擎補落盤 |
|---|------|------|------|
| 1 | 總覽 | nav / metrics.json / weights / decisions.exposure_applied（E(t)） | — |
| 2 | 決策解剖 | **六層全備**（見 §2） | — |
| 3 | GARCH | 參數軌跡 (ω,α,β,ν)、persistence、fallback（`garch_params`/`vol_fell_back`）；QLIKE/MZ-R² 在 `runs/vol_eval/` | **標準化殘差 QQ/ACF**（殘差未存）；已實現波動 proxy 由快照報酬 readers 端算 |
| 4 | 相關結構 | 幾乎沒有 | **DCC/EWMA 相關矩陣、corr time series、corr_fell_back 全未存**（Phase 5a I-1 明確延到 Phase 7） |
| 5 | 組合與成本 | weights（堆疊面積）、band_blocked（帶事件）、nav.turnover/cost | — |
| 6 | 消融 | ablation `comparison.parquet` | — |
| 7 | 資料品質 | 快照 `metadata.json`（MANIFEST/overrides/跨源） | — |
| 8 | Run Lab | — | **7b（本段只 stub）** |
| 9 | **價格與交易（新增）** | 快照 `adjusted_close`；交易可由 weights diff 近似 | **精確成交 blotter**（fill price/逐筆成本/漂移後量，需引擎吐 `trades.parquet`） |

**結論**：AC①（頁 2）完全靠現有 artifact；頁 3/4/9 需引擎補落盤。使用者定案採**補落盤 + 重跑**（非優雅退化），故 7a 含引擎端工作。

---

## 2. Decision Explorer 六層 ↔ `decisions.parquet` 對照（AC① 依據）

| 層 | §11.2 內容 | 來源欄位 | 備註 |
|----|-----------|---------|------|
| (a) | point-in-time 合格選單（未合格灰顯標原因） | `eligible`（JSON list） | 「原因」由 readers 對照全選單推導 |
| (b) | 動量分數長條圖，前 K 高亮 | `momentum_scores`（全合格資產）+ `selected` | |
| (c) | 絕對動量 pass/fail，fail 配額流向現金 | `absmom`（JSON dict bool） | |
| (d) | 每檔 GARCH σ̂（含上一決策日對照） | `sigma_hat`（**年化純量**）+ 讀前一決策列 | **21 步曲線不在此頁**（純量 + 前次對照即滿足；逐步曲線屬頁 3） |
| (e) | inverse-vol 權重 → σ̂_p → `E=clip(σ*/σ̂_p,...)` 真實數字展開，標示是否被帶擋 | `w_risky`/`sigma_p`/`exposure_raw`/`exposure_applied`/`band_blocked` | 公式由 readers 用真實數字重演 |
| (f) | 最終目標權重 vs 漂移後現況、預期換手與成本 | `target_weights` + `weights.parquet`（漂移後）+ `nav.turnover/cost` | |

> 設計決定（層 d）：§11.2 字面提「GARCH 21 步 σ̂」，但 `decisions.parquet` 只存年化純量 σ̂。**21 步逐步曲線歸頁 3（GARCH 檢視），Decision Explorer 層 d 只呈現年化 σ̂ + 上一決策日對照**——避免為單頁重跑引擎多吐逐步預測。AC① 手查的是這些純量，仍成立。

---

## 3. 引擎端診斷落盤（區塊 A）

**原則（§6.2）**：dashboard 要看什麼，引擎在決策當下就記錄什麼；per-decision 的量隨 run 累積落盤，per-asset 靜態診斷 run 結束時落盤。

### 3.1 `Diagnostics` 加兩個 optional 欄位

`quantcore/backtest/strategies/vol_target_base.py` 的 `Diagnostics`：

```python
corr_matrix: pd.DataFrame | None = None   # label-aligned R（僅算 R 的策略；K=1 退化可 None）
corr_fell_back: bool | None = None        # DCC (a,b) QMLE 是否退回 fixed_ab（鏡射 vol_fell_back）
```

- `_build_cov` 把已算的 `R` 與 `self._corr.fell_back` 傳出 → `_exposure_decision` 填入 `Diagnostics`。
- **M-1 順手處理**（Phase 5a holistic review）：`vol_target_base.decide` SELECTION 分支的 `self._cache=state` 賦值移到相關步驟（可 raise）之後。

### 3.2 `decisions.parquet` 加一欄 `corr_fell_back: bool`

- 鏡射既有 `vol_fell_back`，了結 Phase 5a I-1（DCC fallback 可稽核性死路）。頁 4 用它標記退回點。
- `tracking.py` 序列化 Diagnostics 時多寫此欄。

### 3.3 `model_details/correlation.parquet`（新一級子目錄）

- 長格式：`decision_date, strategy_id, ticker_i, ticker_j, corr`。
- 只有算 R 的策略寫（`full`/`full_erc`）；`voltarget_only` K=1（R=[[1]]）略。
- `tracking.py` 在寫盤時把每決策的 `corr_matrix` 攤平累積。
- 頁 4 熱圖 + 時間滑桿 + 任選資產對時間序列的唯一來源。

### 3.4 `model_details/residuals.parquet`

- 格式：`strategy_id, ticker, date, std_resid`（run 內可能含多個波動目標策略如 full、full_erc，同一 ticker 的殘差須以 strategy_id 區分）。
- **粒度定案**：run 結束時，每檔資產寫其**最後一次 GARCH refit** 的標準化殘差時間序列（靜態 per-asset 診斷，QQ/ACF 一份即足；不逐 refit 存，避免檔案膨脹 = YAGNI）。
- 由 runner 於 run 結束時從 forecaster 最終狀態取（引擎端，可 import 模型層）。頁 3 QQ/ACF 來源。

### 3.5 `trades.parquet`（trade blotter，run 根目錄一級 artifact）

- 格式：`execution_date, strategy_id, ticker, drifted_weight, target_weight, delta_weight, side, notional, fill_price, shares, cost`。
  - `delta_weight = target − drifted`（`turnover()` 內部已算，接出而非重算）
  - `side = buy if delta_weight>0 else sell`
  - `notional = delta_weight · NAV(執行日)`；`fill_price = 執行日 adj_close`；`shares = notional / fill_price`
  - `cost = |delta_weight| · NAV · per_side_bps / 1e4`（逐筆分攤，總和 = 該次 `nav.cost`）
- 機制：`accounting` 加一個回 per-ticker Δweight 明細的函數（或 `apply_costs` 附帶回明細），engine 執行日組裝 blotter 列（engine 有 drifted/target/NAV/執行日 + view 的 adj_close）。
- **只有實際再平衡（`execute=True`）的執行日寫**；band-blocked（log-only）不產交易。

### 3.6 誠實驗證閘門（對帳測試，符合「重視誠實驗證」）

- `Σ|delta_weight| == nav.turnover`（逐再平衡，容差內）。
- `Σ cost == nav.cost`（逐再平衡）。
- blotter 與既有聚合量對不上即紅燈——把「blotter 接得對」變成結構保證，非靠肉眼。
- INV-5（會計恆等式）不得因接出 Δweight 明細而改變 NAV 遞推：`turnover`/`apply_costs` 的**回傳語意增量式擴充、既有數值不變**，由既有 INV-5 測試守 + 變異測試確認。

---

## 4. Canonical run（區塊 B）

頁 4 要「DCC vs EWMA 疊圖」，一個 run 只有一個 `corr_model`。

- **定案（B1）**：真實快照 `2026-07-16_20ed09` 全期各跑一次 `corr_model=dcc` 與 `=ewma`，**每個 run 含全 7 策略**（runner 預設；`corr_model` 只影響 `full`/`full_erc`）。頁 4 用**全域控制列的多選 run** 疊 `full` 兩模型的相關——直接用 §11.2 既有多選比較機制。
- 否決 B2（單 run 同存兩份 R）：污染「引擎只記錄驅動決策的東西」原則、多算一份。
- 成本：~167s(dcc)+~51s(ewma)≈4 分鐘（比照 Phase 5a 效能側寫，可接受）。
- 這 2 個 run 同時餵頁 1/2/3/5/9；頁 6 讀既有 ablation `comparison.parquet`；頁 7 讀快照 `metadata.json`。

---

## 5. presentation 架構（區塊 C）

嚴守 §2.2。四個檔 + pages 子目錄：

### 5.1 `presentation/readers.py`（胖、TDD 的核心層）

- 純函數，把 `runs/`、`snapshots/` 的 parquet/JSON 載入並解析成 tidy DataFrame / typed dict。
- 所有 JSON 字串欄（`target_weights`/`eligible`/`momentum_scores`/`absmom`/`sigma_hat`/`w_risky`/`garch_params`/`vol_fell_back`）在此一次解開。
- 缺 `model_details/`、`trades.parquet` 回 `None` → 頁面顯示「本次未儲存」。
- **Decision Explorer 六層抽取函數的 golden 測試 = AC① 的自動化形式**（fixture run + 手算期望值，鎖死六層數字）。
- 只 import stdlib/pandas/pyarrow；**不 import `quantcore.{backtest,models,signals,portfolio,experiments,data}`**。

### 5.2 `presentation/app.py`

- Streamlit 入口 + 全域控制列（`st.sidebar`：run 多選、策略選擇器、日期範圍），`st.session_state` 承載跨頁選擇。

### 5.3 `presentation/pages/`（一頁一檔，Streamlit multipage）

- 薄：呼叫 readers + 畫圖（Plotly：NAV 對數疊圖、瀑布、熱圖、QQ）。零前端程式碼。
- 頁 8 Run Lab 在 7a 只放 stub（顯示「Phase 7b」）。

### 5.4 依賴

- 新增 dev/presentation 依賴：`streamlit`、`plotly`、`statsmodels`（ACF；或自算）。集中於 `pyproject.toml`。

---

## 6. 測試策略

1. **`readers.py` TDD**：含 Decision Explorer 六層 golden（= AC① 自動化）、缺 model_details/trades 的「本次未儲存」路徑、JSON 欄解析、blotter/price-panel 讀取。
2. **引擎落盤 TDD**：`corr_matrix`/`corr_fell_back`/`trades` 落盤正確（合成迷你 run）；§3.6 對帳測試；INV-3/5/6 重跑全綠；變異測試確認新欄位不改既有數值。
3. **頁面 smoke**：`streamlit.testing.v1.AppTest` 對 fixture run 渲染每頁不拋例外。
4. **架構守護測試**：AST 檢查 `presentation/` 只 import 白名單，絕不 import 引擎模組——§2.2 邊界紅綠燈化。

---

## 7. 建置順序（依賴序，每步 TDD、綠了才下一步）

1. **引擎診斷落盤**（§3）：`Diagnostics` 欄位 → `tracking`/`decisions.parquet` 的 `corr_fell_back` → `model_details/correlation.parquet` → `model_details/residuals.parquet` → `accounting`/engine 的 `trades.parquet` + §3.6 對帳測試 → **INV-3/5/6 重跑全綠**。
2. **重跑 2 個 canonical run**（§4，dcc/ewma，全 7 策略），確認新 artifact 齊備。
3. **`readers.py`**（§5.1，含 Decision Explorer golden = **AC① 自動化**）。
4. **`app.py` + 全域控制列 + 架構守護測試**（§5.2、§6.4）。
5. **頁面**：先 1/2/5（資料全備）→ 3/4（吃 model_details）→ 9（價格與交易，吃 blotter+快照）→ 6（ablation）→ 7（資料品質）；頁 8 stub。
6. **AC① 人工手查**：對 canonical run 任選一決策日，Decision Explorer 六層 vs `decisions.parquet` 逐格吻合，寫成文件（`docs/phase7a-ac1-handcheck.md`）。

---

## 8. 與規格的差異（明列，供 review）

1. **7a 含引擎端落盤**（非純展示層）：§9 把 Phase 7 描述為 dashboard，但頁 3/4/9 所需診斷（相關矩陣、殘差、blotter）Phase 4/5 引擎未落盤。使用者定案採「補落盤 + 重跑」而非優雅退化，故引擎端工作納入 7a。了結 Phase 5a I-1（`corr_fell_back`）。
2. **新增第 9 頁「價格與交易」**：§11.2 列 8 頁，第 9 頁為研究報告陳述需要而擴充（使用者明述「終究需要好的方法陳述結果、圖表最適合」）。
3. **`trades.parquet` 為新一級 artifact**：§7.2 檔案合約原無 blotter；為頁 9 精確成交而加，放 run 根目錄（與 weights 同級，非 model_details——blotter 是一級結果非深掘細節）。
4. **Decision Explorer 層 d 只呈現年化 σ̂ + 前次對照**（非 21 步曲線）：逐步曲線歸頁 3，避免為單頁重跑引擎（見 §2 備註）。
5. **順手處理 Phase 5a M-1**（`self._cache` 賦值位置）。M-2（`rolling_correlation` 半死碼）/M-3（cadence 四捨五入註解）視 7a 觸及範圍順手或留 backlog。

---

*Phase 7a design — 2026-07-29。brainstorming 定案，待 writing-plans 展開為實作計畫。*
