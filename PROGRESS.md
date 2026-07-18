# QuantCore 開發進度追蹤

> 依據 `DEVELOPMENT_GUIDE v1.2.md` §9「開發順序與里程碑」。
> 規則：**每個 Phase 的 AC（驗收條件）不過，不進下一階段。**
> 最後更新：2026-07-13

## 狀態圖例
- ⬜ 未開始 　🟨 進行中 　✅ 完成（AC 通過） 　⛔ 卡關

---

## 總覽

| Phase | 名稱 | 預估工時 | 狀態 |
|-------|------|---------|------|
| 0 | 骨架 | ~數天 | ✅ 完成 |
| 1 | 資料層 | ~1.5 週 | ✅ 完成 |
| 2 | 回測核心（最關鍵） | ~1-2 週 | ✅ 完成 |
| 3 | 訊號與組合層 | ~1 週 | ⬜ 未開始 |
| 4 | 波動率模型與波動目標 | ~1-2 週 | ⬜ 未開始 |
| 5 | DCC 與 ERC | ~1 週 | ⬜ 未開始 |
| 6 | 手刻 GARCH（學習里程碑） | ~2-3 週 | ⬜ 未開始 |
| 7 | Dashboard 與研究報告 | ~2.5 週 | ⬜ 未開始 |

**總時程**：約 3-3.5 個月業餘時間。Phase 0-2 建議暑假密集完成。

---

## Phase 0 — 骨架　✅

repo 初始化、pydantic config、pytest + CI、pre-commit（ruff/black）、目錄結構。
套件管理採 **uv**（Python 3.12）。Remote：https://github.com/Sugerpi/QuantSystem

### 任務
- [x] 建立 git repo
- [x] 建立 §2.1 模組目錄結構（`quantcore/` 下 config/data/models/signals/portfolio/backtest/experiments/presentation，含 `__init__.py`）
- [x] `pyproject.toml`（uv、依賴、ruff/black/pytest 設定集中一處）
- [x] `config/schema.py`（pydantic 型別化 config，`extra=forbid` + 跨欄位驗證）
- [x] `config/default.yaml`（規格 §7.2）
- [x] pytest 設定 + dummy test（`tests/test_smoke.py`）+ config 驗證測試（`tests/test_config.py`，7 項全綠）
- [x] pre-commit（ruff lint / ruff-format / 基本 hooks）
  - 2026-07-17 修正：原設定同時掛 black 與 ruff-format，兩者對三元運算子鏈與隱式
    字串串接的換行意見不同，會在每次 commit 互相改寫同一個檔案；且 `.git/hooks/`
    從未 install，故本機無人把關（此項當時的勾只代表設定檔存在）。現已移除 black
    （pre-commit / pyproject dev deps / `[tool.black]` / CI 的 format 檢查一併改為
    ruff format），並實際執行 `uv run pre-commit install`。
- [x] GitHub Actions CI workflow（`.github/workflows/ci.yml`，寫好待 remote 生效）

### AC（驗收條件）
- [x] config 能載入並驗證 `default.yaml`（已本地驗證）
- [x] CI 綠燈跑 dummy test — 已 push 至 remote，GitHub Actions **首次執行成功（conclusion: success）**；本地 `uv run pytest` 7 項全綠、ruff/black 乾淨

**Phase 0 完成。** 可進入 Phase 1（資料層）。

---

## Phase 1 — 資料層　✅

Provider 介面、yfinance/Tiingo/TwelveData/FRED adapters、快照建立與 hash、NYSE 日曆、驗證規則、跨源交叉驗證（§4.5）。

### 任務
- [x] `data/provider.py`（DataProvider Protocol，§4.1）
- [x] `providers/yfinance_adapter.py`（primary；adj_close 改為自建決定性調整，見下）
- [x] `providers/tiingo_adapter.py`（validation；含 429 退避與 token 遮蔽）
- [x] `providers/stooq_adapter.py`（arbiter，**預留**：免金鑰端點已被 JS 反爬封鎖，未併入）
- [x] `providers/twelvedata_adapter.py`（**實際第三源仲裁**，取代失效的 Stooq）
- [x] `providers/fred_adapter.py`（DTB3，keyless）
- [x] `data/calendar.py`（NYSE，exchange_calendars；起始界 1990 涵蓋 2005）
- [x] `data/adjust.py`（自 close+股息 back-adjust，決定性含息調整）
- [x] `data/hashing.py`（canonical hash，守 AC-4）
- [x] `data/snapshot.py`（建立/載入/hash 驗證 + CLI，§4.2）
- [x] `data/validation.py`（§4.3 五項檢查）
- [x] `data/crosssource.py`（跨源交叉驗證 + 三源仲裁，§4.5）

### AC
- [x] `snapshot create` 產出完整快照 → `snapshots/2026-07-16_20ed09`（20 檔，2005-01-03→2026-07-15）
- [x] 總報酬驗證通過（§4.3）
- [x] 跨源日報酬比對全選單通過（三源仲裁；345 筆裁決記於 metadata.json overrides）
- [x] 同日重建兩次快照 hash 相同（build#1 == build#2 == `2026-07-16_20ed09`）
- [x] `tests/test_data/` 全綠（`uv run pytest` 77 項通過）

### Phase 1 實作備忘（與原規劃的差異）
- **§4.5 第三源**：規格指定 Stooq，但其免金鑰 CSV 端點現已被 JS 反爬封鎖、`pandas-datareader` 亦移除 Stooq 支援。改用 **Twelve Data**（免費金鑰，`.env` 的 `TWELVEDATA_API_KEY`）為實際仲裁源；Stooq adapter 保留為預留介面。
- **DBC 移除**：DBC（廣義商品 ETF）2008 崩盤期資料三源（yfinance/Tiingo/TwelveData）彼此皆不一致、§4.5 無法認證，故自 v1 menu 移除（21→20 檔）。日後有可信商品源再加回。
- **決定性含息調整**：yfinance 的 `Adj Close` 每次抓取會以浮點微差（~1e-6）重算，破壞 AC-4。改為存穩定的原始 `close` + 自建 `adjusted_close`（僅股息，yfinance close 已拆分調整），使快照位元級可重現。
- **首份真實快照 3 源用量**：yfinance（primary，免費）+ Tiingo（validation，免費金鑰，50 req/hr）+ Twelve Data（arbiter，免費金鑰，8 req/min 節流）+ FRED（DTB3，keyless）。

---

## Phase 2 — 回測核心（全案最關鍵階段）　✅

事件時鐘、PointInTimeView、engine、accounting、成本、metrics（先不含 bootstrap）。策略只做 `bh_spy` 與 `ew_menu`。

### 任務
- [x] `backtest/clock.py`（事件時鐘：交易日/決策日/執行日，§1.2；決策日錨點見備忘）
- [x] `backtest/ptview.py`（PointInTimeView，建構時實體切片並凍結，INV-1）
- [x] `backtest/engine.py`（主迴圈；順序損益→漂移→執行→決策，見備忘）
- [x] `backtest/accounting.py`（NAV、漂移、現金計息、成本，§6.1/INV-5）
- [x] `backtest/strategy.py`（Strategy 介面 + strategy_id；`decide(view, event)`，見備忘）
- [x] `backtest/strategies/`（`bh_spy.py`、`ew_menu.py`，子套件）
- [x] `backtest/metrics.py`（Sharpe/Sortino/MaxDD/Calmar/turnover，不含 bootstrap）
- [x] `portfolio/selection.py`（point-in-time 合格性；Phase 3 於此加排序/取 K）
- [x] `experiments/tracking.py`（run 目錄、manifest identity/created_at、決定性寫檔）
- [x] `experiments/runner.py`（單次實驗 pipeline + CLI）
- [x] INV-1/2/5/6 測試（合成迷你快照，CI 可跑）

> 原任務清單只列 `backtest/` 六檔，未列 `experiments/` 與 `portfolio/selection.py`。
> 但 AC 的 INV-6 隱含 run 落地（§2.1 屬 experiments/），故一併納入。

### AC
- [x] INV-1/2/5/6 測試全綠（合成迷你快照）
- [x] 三日手算 golden case 逐日吻合（`test_accounting.py::test_three_day_golden_case`）
- [x] `bh_spy` 年化報酬與外部來源吻合 — 引擎自身對快照 SPY 含息總報酬精確到 **0.0000 bps/年**
      （自執行日、apples-to-apples）；對 portfoliovisualizer 差 7.40 bps/年，由引擎外資料源差異
      主導。詳見 `docs/phase2-bh-spy-external-check.md`。**此 AC 為本機閘門**（快照 gitignore，CI 無快照）

### Phase 2 實作備忘（與原規劃的差異，共 8 處，詳見設計文件 §10）
1. **迴圈順序**：§6.1 伪代碼「執行→損益」在回看報酬慣例下與 §1.2 損益歸屬矛盾（新權重會賺到生效前的報酬）。以 §1.2 為準：損益→漂移→執行→決策。由 `test_execution_lag.py` 的行為測試鎖死（變異測試確認：改回 §6.1 順序即紅燈）。
2. **run 目錄命名** `YYYY-MM-DD_HHMM_<label>`：§7.1 範例含單一策略名，但一 run 涵蓋多策略。
3. **具體策略置於 `backtest/strategies/` 子套件**：§2.1 只給了介面 `strategy.py`。
4. **AC-3 為本機閘門**：`snapshots/` gitignore，CI 無真實快照；用 `requires_snapshot` marker 自動 skip。
5. **新增 `tests/test_backtest/`、`test_portfolio/`、`test_experiments/`**：§8 測試樹未列。
6. **決策日錨定於 warmup 結束後第一個交易日**：§1.7 只給間隔未給起點。
7. **`Strategy.decide(view, event)`**：§6.2 的 `decide(view)` 無法分辨選擇日/曝險檢查日（§1.7）。
8. **`nav.parquet` 增 `turnover`/`cost` 欄**：§6.4 年化換手率與成本拖累、§11.2 第 5 頁需要。

### Phase 2 過程中的 repo 整理（非計畫內，但必要）
- **formatter 統一為 ruff format，移除 black**：原本 pre-commit 同時掛 black 與 ruff-format、CI 跑 `black --check`，兩者對三元運算子鏈與隱式字串串接的換行意見不同，會互相改寫同一檔案。且 `.git/hooks/` 從未 install。已移除 black（pre-commit/pyproject/CI 一併改為 ruff format）並實際執行 `pre-commit install`。

### 最終 code review 後修正（merge 前）
- **#1 依賴反向**：`portfolio/selection.py` 原 import `backtest.ptview.PointInTimeView`，違反 `portfolio ← backtest`。改為 `eligible_assets` 收 point-in-time 價格切片 DataFrame，portfolio 不再依賴 backtest 型別。
- **#2 INV-6 位元比對脆弱**：改為 manifest 存 `content_hashes`（canonical_hash，設計文件 §5.3），INV-6 比內容而非 parquet 位元組（pyarrow 升級不誤觸紅燈）+ `assert_frame_equal` 補列序守護。
- **#3 metrics.json 可吐非法 `NaN`**：`_json_safe` 把非有限浮點換 null（供 presentation 嚴格 parser）。

---

## Phase 3 — 訊號與組合層　⬜

動量、絕對動量、選擇、inverse-vol（波動率暫用 63 日滾動標準差）、`mom_only` 與 `mom_ivol` 策略。

### 任務
- [ ] `signals/momentum.py`（12-1 橫斷面 + 絕對動量，純函數，§1.3/§1.4）
- [ ] `portfolio/selection.py`（排序、取 K、平手規則、point-in-time 合格性）
- [ ] `portfolio/weighting.py`（inverse-vol）
- [ ] Diagnostics 落盤（§6.2，decisions.parquet）
- [ ] `mom_only`、`mom_ivol` 策略

### AC
- [ ] 消融跑得動並產出比較表
- [ ] 決策 diagnostics 完整落盤

---

## Phase 4 — 波動率模型與波動目標　⬜

`garch_arch`、`ewma`、多步預測、曝險模組與更新帶、`voltarget_only` 與 `full` 策略、QLIKE 評估、block bootstrap。

### 任務
- [ ] `models/volatility/base.py`（縮放 template method，INV-4）
- [ ] `models/volatility/garch_arch.py`（arch 套件 GARCH(1,1)-t）
- [ ] `models/volatility/ewma.py`（RiskMetrics λ=0.94，消融基線）
- [ ] 多步波動預測（H=21，§1.6 Step 1）
- [ ] `portfolio/exposure.py`（波動目標 + 更新帶，唯一曝險出口，§1.6）
- [ ] QLIKE / MZ-R² 評估（§5.4）
- [ ] block bootstrap（stationary，§6.4）
- [ ] `voltarget_only`、`full` 策略

### AC
- [ ] `full` 已實現波動率落在 σ*（10%）± 2% 內
- [ ] GARCH vs EWMA 的 QLIKE 比較表產出
- [ ] 七策略消融全表產出

---

## Phase 5 — DCC 與 ERC　⬜

DCC（含參數 walk-forward 重估開關）、ERC 權重選項。

### 任務
- [ ] `models/correlation/base.py`
- [ ] `models/correlation/dcc.py`（DCC(1,1)，兩步 QMLE，PSD 內部封裝）
- [ ] `models/correlation/ewma_corr.py`（消融基線）
- [ ] `models/covariance.py`（Σ = D·R·D + PSD 投影，唯一出口，INV-3）
- [ ] ERC 權重選項（`portfolio/weighting.py`）

### AC
- [ ] DCC vs EWMA 消融結論明確寫入報告（「無顯著貢獻」也是合格結論）

---

## Phase 6 — 手刻 GARCH（學習里程碑）　⬜

`garch_own.py`：t 分配 log-likelihood、變異數遞迴、數值優化、多步預測。

### 任務
- [ ] `models/volatility/garch_own.py`（手刻 GARCH(1,1)-t、L-BFGS-B）
- [ ] parity test（vs arch，§5.2）
- [ ] 推導筆記（技術寫作樣本）

### AC
- [ ] parity test 通過（參數相對誤差 <1%、21 步預測 <0.5%）→ 轉正為預設 `vol_model`

---

## Phase 7 — Dashboard 與研究報告　⬜

7a 唯讀頁面、7b Run Lab、7c 最終研究報告。

### 任務
- [ ] 7a：8 個頁面（總覽/決策解剖/GARCH/相關結構/組合成本/消融/資料品質，§11.2）
- [ ] `presentation/app.py`（Streamlit 入口）
- [ ] `presentation/readers.py`（runs/、snapshots/ 唯讀載入）
- [ ] 7b：`presentation/jobs.py`（Run Lab、subprocess、status.json 合約，§11.3）
- [ ] 7c：最終研究報告（以消融表為骨架）

### AC
- [ ] Decision Explorer 六層數字與 decisions.parquet 手查一致
- [ ] 從 Run Lab 提交新 config 並完整跑完回測，全程不碰終端機
- [ ] UI 行程強制終止再重啟後，運行中 job 狀態與進度無損

---

## 變更紀錄
- 2026-07-13：建立進度追蹤文件；完成 git init、`.claude/`、`CLAUDE.md`、`.gitignore`。
- 2026-07-13：Phase 0 骨架完成（uv 環境、§2.1 目錄樹、pydantic config schema + default.yaml、pytest 7 項全綠、ruff/black、pre-commit、CI workflow）。
- 2026-07-13：push 至 remote（github.com/Sugerpi/QuantSystem），GitHub Actions CI 首次執行成功。**Phase 0 全部 AC 達成 ✅**。
- 2026-07-16：Phase 1 資料層完成——provider 介面、四 adapters（yfinance/Tiingo/TwelveData/FRED）、NYSE 日曆、決定性 hash、§4.3 五項驗證、§4.5 三源仲裁、決定性含息調整、快照 CLI。首份真實快照 `snapshots/2026-07-16_20ed09`（20 檔）建立；tests/test_data 全綠（77 項）。過程中：Stooq 失效改用 Twelve Data、移除 DBC、將 yfinance 抖動 adj 改為自建決定性調整以達成 AC-4。**Phase 1 全部 AC 達成 ✅**。
- 2026-07-18：Phase 2 回測核心完成——事件時鐘、PointInTimeView、accounting、engine、metrics、兩 benchmark 策略、experiments run 落地與 CLI。INV-1/2/5/6 由合成迷你快照鎖死（CI 可跑，以變異測試確認各 INV 有牙齒）；三日手算 golden case 通過；AC-3 端到端體檢——引擎自身對快照 SPY 含息總報酬精確到 0.0000 bps/年，對 portfoliovisualizer 差 7.40 bps/年（資料源差異主導）。全套 135 項綠（含 2 項本機快照測試）。8 處規格偏離見上方備忘。過程中整理：formatter 統一為 ruff format 並移除互相衝突的 black、實際安裝 pre-commit hook。最終 code review（opus）抓到 3 項並於 merge 前修正（依賴反向、INV-6 位元比對脆弱、metrics NaN），詳見上方備忘。**Phase 2 全部 AC 達成 ✅**。
