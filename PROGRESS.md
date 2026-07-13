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
| 0 | 骨架 | ~數天 | ⬜ 未開始 |
| 1 | 資料層 | ~1.5 週 | ⬜ 未開始 |
| 2 | 回測核心（最關鍵） | ~1-2 週 | ⬜ 未開始 |
| 3 | 訊號與組合層 | ~1 週 | ⬜ 未開始 |
| 4 | 波動率模型與波動目標 | ~1-2 週 | ⬜ 未開始 |
| 5 | DCC 與 ERC | ~1 週 | ⬜ 未開始 |
| 6 | 手刻 GARCH（學習里程碑） | ~2-3 週 | ⬜ 未開始 |
| 7 | Dashboard 與研究報告 | ~2.5 週 | ⬜ 未開始 |

**總時程**：約 3-3.5 個月業餘時間。Phase 0-2 建議暑假密集完成。

---

## Phase 0 — 骨架　⬜

repo 初始化、pydantic config、pytest + CI、pre-commit（ruff/black）、目錄結構。

### 任務
- [ ] 建立 git repo　←　*本次已完成 git init*
- [ ] 建立 §2.1 模組目錄結構（`quantcore/` 下 config/data/models/signals/portfolio/backtest/experiments/presentation）
- [ ] `config/schema.py`（pydantic 型別化 config）
- [ ] `config/default.yaml`（規格 §7.2 範例）
- [ ] pytest 設定 + 一個 dummy test
- [ ] pre-commit（ruff / black）
- [ ] GitHub Actions CI

### AC（驗收條件）
- [ ] CI 綠燈跑一個 dummy test
- [ ] config 能載入並驗證 `default.yaml`

---

## Phase 1 — 資料層　⬜

Provider 介面、yfinance/Tiingo/Stooq/FRED adapters、快照建立與 hash、NYSE 日曆、驗證規則、跨源交叉驗證（§4.5）。

### 任務
- [ ] `data/provider.py`（DataProvider Protocol，§4.1）
- [ ] `providers/yfinance_adapter.py`（primary）
- [ ] `providers/tiingo_adapter.py`（validation）
- [ ] `providers/stooq_adapter.py`（arbiter）
- [ ] `providers/fred_adapter.py`（DTB3）
- [ ] `data/calendar.py`（NYSE，exchange_calendars）
- [ ] `data/snapshot.py`（建立/載入/hash 驗證，§4.2）
- [ ] `data/validation.py`（§4.3 五項檢查）
- [ ] 跨源交叉驗證流程（§4.5）

### AC
- [ ] `snapshot create` 產出完整快照
- [ ] 總報酬驗證通過
- [ ] 跨源日報酬比對全選單通過（或差異已裁決記於 overrides）
- [ ] 同日重建兩次快照 hash 相同
- [ ] `tests/test_data/` 全綠

---

## Phase 2 — 回測核心（全案最關鍵階段）　⬜

事件時鐘、PointInTimeView、engine、accounting、成本、metrics（先不含 bootstrap）。策略只做 `bh_spy` 與 `ew_menu`。

### 任務
- [ ] `backtest/clock.py`（事件時鐘：交易日/決策日/執行日，§1.2）
- [ ] `backtest/ptview.py`（PointInTimeView，結構性防 look-ahead，INV-1）
- [ ] `backtest/engine.py`（主迴圈，§6.1）
- [ ] `backtest/accounting.py`（NAV、漂移、現金計息、成本，§6.1/INV-5）
- [ ] `backtest/strategy.py`（Strategy 介面 + strategy_id，§6.2）
- [ ] `backtest/metrics.py`（Sharpe/Sortino/MaxDD/Calmar/turnover）
- [ ] `bh_spy`、`ew_menu` 策略
- [ ] INV-1/2/5/6 測試

### AC
- [ ] INV-1/2/5/6 測試全綠
- [ ] 三日手算 golden case 逐日吻合
- [ ] `bh_spy` 年化報酬與外部來源（portfoliovisualizer）對 SPY 同期吻合（成本/計息差異範圍內）— 端到端體檢

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
- 2026-07-13：建立進度追蹤文件；完成 git init、`.claude/`、`CLAUDE.md`、`.gitignore`。Phase 0 中「建立 git repo」子項完成，其餘待辦。
