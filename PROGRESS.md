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
| 3 | 訊號與組合層 | ~1 週 | ✅ 完成 |
| 4 | 波動率模型與波動目標 | ~1-2 週 | 🟨 進行中（4a + 4b 完成，4c 待做） |
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

## Phase 3 — 訊號與組合層　✅

動量、絕對動量、選擇、inverse-vol（波動率暫用 63 日滾動標準差）、`mom_only` 與 `mom_ivol` 策略。

### 任務
- [x] `signals/momentum.py`（12-1 橫斷面 + 絕對動量，純函數，§1.3/§1.4）
- [x] `portfolio/selection.py`（排序、取 K、平手規則、point-in-time 合格性）
- [x] `portfolio/weighting.py`（inverse-vol）
- [x] Diagnostics 落盤（§6.2，decisions.parquet）
- [x] `mom_only`、`mom_ivol` 策略

### AC
- [x] 消融跑得動並產出比較表
- [x] 決策 diagnostics 完整落盤

### Phase 3 實作備忘（與原規劃的差異）
1. **`vol_model` 暫設 `rolling_std`**：規格 §7.2 config 範例為 `garch_arch`，但 Phase 3 尚無 GARCH。新增 `rolling_std`（63 日滾動標準差，`risk.vol_window`）作為 inverse-vol 的波動來源；`default.yaml` 暫設 `vol_model: rolling_std`，Phase 4 GARCH 到位後翻回 `garch_arch`。vol 派發對未實作模型丟 `NotImplementedError`（誠實失敗）。
2. **順手建 `sixty_forty`**：§6.3 有此基準但原不在 Phase 3 任務清單；因與訊號層無關且極便宜，一併建立，讓消融比較表多一個傳統配置基準。
3. **絕對動量回看窗沿用 `momentum_lookback`**：§1.4「過去 252 日」與 §1.3 動量同窗，故不新增參數（不套 skip）。
4. **新增 config 約束 `vol_window + 1 ≤ max(min_history_days, momentum_lookback+1)`**：保證任何入選資產都算得出滾動波動窗（入選資產至少有該根數 bar），於 config 載入時失敗而非回測中途。
5. **消融引擎（`experiments/ablation.py`）為通用引擎**：收「策略清單 + 一次動一參數的參數格」，跟得上多少策略跑多少（Phase 3 為 bh_spy/ew_menu/sixty_forty/mom_only/mom_ivol 五支；voltarget_only/full 待 Phase 4 GARCH）。單格 config 驗證失敗只記錄並略過、不拖垮整批；輸出 `comparison.parquet` + `manifest.json`（snapshot_id/git_commit/config_hash，INV-6 provenance）。
6. **`momentum_scores` diagnostic 記全體合格資產**（§6.2「不只前 K」），`sigma_hat`/`w_risky` 於 mom_ivol 填、mom_only 的 `sigma_hat` 為 None；Phase 4 才有的曝險欄（sigma_p/exposure_*/band_blocked）維持 None。

### 最終 holistic review 後修正（merge 前）
- **絕對動量 DTB3 對齊交易日曆**：final review 抓到 `absolute_momentum` 原本直接取 DTB3 末 lookback 筆原始觀測，但 DTB3 為 FRED 聯邦營業日索引、與 NYSE 交易日曆不同步，導致 tbill hurdle 窗與資產報酬窗只共用端點；且窗內若有 NaN 會使 `tbill_cum=NaN`、全部資產靜默轉現金。已改為比照 `engine._daily_rates` 把 DTB3 reindex 到交易日軸並 ffill/bfill，並對「交易日不足」與「窗內全 NaN」誠實拋錯。此缺陷因合成 fixture 的 rates 與 prices 同曆、恆為常數而被逐 task review 遮蔽，僅整體審視可見。

---

## Phase 4 — 波動率模型與波動目標　🟨

依 brainstorming 切三段：**4a 波動率模型層**（✅）、**4b 曝險+策略接線**、4c bootstrap + 七策略消融。
4b 再切兩段：**4b-1 基礎模組**（exposure/covariance/VolForecaster，✅）、**4b-2 策略+engine 接線**（✅）。
設計/計畫文件見 `docs/superpowers/specs/` 與 `docs/superpowers/plans/` 的 `phase4a-*` / `phase4b1-*` / `phase4b2-*`。

### 任務
- [x] `models/volatility/base.py`（縮放 template method，INV-4 單一出口）
- [x] `models/volatility/garch_arch.py`（arch 套件 GARCH(1,1)-t，解析多步）
- [x] `models/volatility/ewma.py`（RiskMetrics λ=0.94，消融基線 + GARCH fallback）
- [x] 多步波動預測（H=21，§1.6 Step 1；`annualized_forecast_vol`）
- [x] QLIKE / MZ-R² 評估（§5.4；`models/volatility/eval.py` + walk-forward 驅動）
- [x] `portfolio/exposure.py`（波動目標 + 更新帶，唯一曝險出口，§1.6）— 4b-1
- [x] `models/covariance.py`（過渡滾動相關 Σ=D·R·D，INV-3）— 4b-1（規格未列，`full` 的 σ̂_p 需要）
- [x] `VolForecaster` refit/filter + 有上界滾動窗（§5.2）— 4b-1
- [x] `voltarget_only`、`full` 策略、`mom_ivol` 遷移 GARCH、engine log-only 接線 — 4b-2
- [ ] block bootstrap（stationary，§6.4）— 4c

### AC
- [ ] **已實現波動落 σ*（10%）±2%（條件化重定義，設計 4b-2 §7）**：`voltarget_only`（無 absmom）全期量、落 8-12%（波動目標乾淨測）；`full` 僅在 absmom 大致全過期間量、落 8-12%（隔離波動目標層，因 absmom 轉現金會正確壓低危機期波動、全期量不公平）— 實際量測 4c
- [x] **GARCH vs EWMA 的 QLIKE 比較表產出**（4a 達成：GARCH QLIKE 20/20 檔勝 EWMA）
- [ ] 七策略消融全表產出 — 4c

### Phase 4a 實作備忘（與原規劃的差異，詳見設計文件 §6）
1. **QLIKE/MZ-R² 放 `models/volatility/eval.py` 而非 §5.4 字面的 `metrics.py`**：依賴方向（models 不得依賴 backtest）。
2. **新增 config `risk.ewma_lambda`（0.94）/ `risk.forecast_horizon`（21）**：§7.2 未列 λ 與 H，避免魔術數字。
3. **多步預測用 arch analytic forecast（閉式解析遞迴，非模擬）**：決定性（INV-6）。
4. **GARCH 失敗（不收斂 / α+β≥1 / 非有限）退回 EWMA + 標記**（`fit_volatility`，非拋錯中斷、非沿用舊參數）：兼顧誠實（可審計 fallback 頻率）與回測可完成。真實快照 walk-forward 共 241 次 fallback（HYG 最高 ~55%），fallback 機制無崩潰。
5. **4a 只建模型層，未碰 engine/策略**；`mom_ivol` 仍用 rolling_std，待 4b 遷移。
6. **EWMA 為 IGARCH（α+β=1），豁免 base 的 α+β<1 平穩性檢查**（旗標 `enforce_stationarity`）。

### Phase 4a 過程中補強（review 抓到）
- **補建缺席的 INV-4 守護測試 `tests/test_invariants/test_garch_conventions.py`**：CLAUDE.md 不變量表列它為 INV-4 守護，但此前檔案不存在——INV-4 一直無測試守護，至此補上（含 mutation-style 的「平穩性檢查有牙齒」測試與 ÷100² 還原測試）。
- GARCH 標準化殘差保留 DatetimeIndex（供 Phase 5 DCC 按日期對齊）；`fit_volatility` fallback 契約明述僅涵蓋 fit-time；walk-forward 比較表對零變異窗與非退化 fit 例外穩健（單格失敗不丟整表）。

### Phase 4b-1 實作備忘（與原規劃的差異，詳見設計文件 `phase4b1-*` §4）
1. **過渡 `covariance.py` 用滾動樣本相關**：DCC（§5.3）為 Phase 5，4b 先以樣本相關填 R；`build_covariance`/`portfolio_vol` 介面穩定，Phase 5 只換 R 來源。INV-3 靠「投影 R 為合法 PSD 相關 → Σ=D·R·D」自然同時成立（對稱/PSD/對角線=個別變異數）。
2. **新增 config `risk.garch_window`（1000）+ 有上界滾動窗**：§5.2 只給估計下限未給上限；展開窗會使後期 refit 成本 O(t) 膨脹（回測+消融爆炸）。改為尾端 `garch_window` 根的滾動窗，成本恆 O(cap)。回測起點仍由動量 warmup 決定、不受 cap 影響（2008 恆在內）。
3. **`VolForecaster` 有狀態、refit/filter 分離**（§5.2）：refit 昂貴（MLE，選擇日）、filter 便宜（arch `fix()` 固定參數濾波，曝險檢查日），4c 消融格點約快 5×。有狀態比照 bh_spy，引擎每 run 新建，不破 INV-6。
4. **帶只作用於曝險檢查日**（選擇日傳 `e_current=None`）：§1.7 表格把帶列於曝險檢查日；選擇日完整重算、換手內生。

### Phase 4b-1 過程中補強（review 抓到）
- **補建缺席的 INV-3 守護測試 `tests/test_invariants/test_covariance_valid.py`**（與 INV-4 同：CLAUDE.md 早列為守護、檔案卻不存在。含 mutation-style：移除 PSD 投影即紅燈，已實測驗證有牙齒）。
- `build_covariance` 出口拒絕非有限 R（零變異窗）+ tickers 長度校驗；GARCH `arch_model` 規格單一來源（`_build_arch_model`）+ filter 補 horizon/非有限守護；`VolForecaster` 快取改 dataclass。
- **整體 holistic review 抓到跨模組 seam 隱患並結構性修掉**：covariance 三函數原靠「未強制的 ticker 順序約定」黏合，且 **INV-3 守護對錯配是盲的**（R_ii=1 使置換後 Σ 對角線/PSD 仍成立、給假信心）；已改為 **label-aligned（R/Σ 為 pd.DataFrame，依 label 對齊）**，並讓 `portfolio_vol` 對「w_risky 有但 cov 未涵蓋」的資產拋錯（否則 σ̂_p 低估、曝險過高）——ticker 錯配與風險低估自此結構上不可能。趁 4b-2 尚無 call site 修掉，blast radius 僅測試。
- **待 4b-2 處理的呼叫端契約**：`VolForecaster` 快取不過期，正確性依賴呼叫端每次重選都 `refit`；4b-2 整合測試須驗「重選後 filter 不吃到 stale 參數」。

### Phase 4b-2 實作備忘（與原規劃的差異，詳見設計文件 `phase4b2-*` §9）
1. **engine `Decision.execute` 旗標 + log-only decision**：§6.1 無此概念，但 §1.7「帶內不動作」與 §6.2「band_blocked 落盤」需並存——不執行卻要記診斷。engine 分離「落診斷」與「執行」；band-blocked 曝險檢查回 `execute=False`（記 band_blocked/sigma_p/exposure_*、不 rebalance、權重續漂移）。變異測試鎖住。
2. **`vol_fell_back`/`garch_params` 決策當下落盤**（`Diagnostics` 兩新欄 + `VolForecaster.last_params`）：dashboard page-3 的 GARCH 參數軌跡與 fallback 頻率所需，於決策當下記入 `decisions.parquet`，Phase 7 讀取而非重跑（§6.2）。修正 4b-1 備忘「留 Phase 7」與此原則的矛盾。
3. **新增 config `risk.corr_window`（252）**：§1.6 的 Σ 需相關 R，窗長規格未列；252 偏穩定、≫ top_k 保 R 滿秩。可消融 {126,252}。
4. **σ*±2% AC 條件化**（見上方 AC）：`voltarget_only` 全期乾淨測、`full` 僅在 absmom 大致全過期間量。因 absmom 轉現金會正確壓低危機期波動、全期量不公平。實際量測 4c。
5. **`mom_ivol` 遷移到 GARCH σ̂**（VolForecaster，與 full 同估計器）：使 full vs mom_ivol 消融只差曝險層（apples-to-apples）。`mom_ivol` 不再支援 rolling_std。
6. **`vol_model` 預設翻 `garch_arch`**：GARCH(1,1)-t 轉正為生產路徑（§5.2）。`rolling_std` 的 `estimate_annualized_vol` 路徑仍在但無策略使用。

### Phase 4b-2 過程中補強（review 抓到）
- **`VolForecaster.__init__` eager 驗證** spec ∈ {garch_arch, ewma}：非法 vol_model 在策略建構時就 fail-fast，而非回測深處首次 refit 才拋錯。
- `full` 用 `forecast_selected` 共用 helper（消除 refit+診斷三元組在 full/voltarget_only 的重複）；engine log-only 補 `pd.isna` 契約 + log-only→executed 序列覆蓋。
- **backlog（4c 前處理）**：動量選擇序列（eligible→動量→top_k→absmom）現在 `MomentumStrategy.decide` 與 `Full._select_and_weight` 各一份（已加交叉引用註解）——4c 消融跑之前抽 `momentum_select` 共用，確保 full/mom_ivol/mom_only 選擇邏輯結構性一致（消融 apples-to-apples）。GARCH 診斷的 strategy-layer 端到端覆蓋亦待 4c 真實快照跑到。

### Phase 4b-2 邊界
七策略齊備（bh_spy/ew_menu/sixty_forty/mom_only/voltarget_only/mom_ivol/full）、GARCH 為預設 vol 來源、曝險機制與 band 落盤完整。**4c 做 block bootstrap + 七策略消融全表 + σ*±2% 條件式量測 + 子期間分析**，屆時 Phase 4 全部 AC 達成。

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
- 2026-07-20：Phase 3 訊號與組合層完成——12-1 橫斷面動量 + 絕對動量過濾（signals/momentum.py）、select_top_k 排序取 K 字母序平手、inverse-vol/等權/絕對動量轉現金（portfolio/weighting.py）、rolling_std 波動 placeholder（models/volatility/）、mom_only/mom_ivol/sixty_forty 三策略、通用消融引擎（experiments/ablation.py）。AC-1（消融跑得動並產出比較表）與 AC-2（決策 diagnostics 完整落盤）皆達成。全套測試 176 項綠。以 subagent-driven TDD 執行，12 個 task 每個經 spec + code-quality 兩段式 review，最終再做一次整體 holistic review（抓到並修正絕對動量 DTB3 對齊交易日曆的跨模組缺陷，見上方備忘）。6 處規格偏離 + 1 處 review 後修正見上方備忘。**Phase 3 全部 AC 達成 ✅**。
- 2026-07-20：**修 CI 上長期潛伏的快照 skip 缺陷**（Phase 3 PR 首次觸發而暴露）。快照的 `MANIFEST.json`/`metadata.json` 自 Phase 1（commit `6130e59`）起刻意進版控（hash/provenance），但 `prices/rates.parquet` gitignore。舊 `tests/conftest.py` 的 `requires_snapshot` skip 以 `MANIFEST.json` 是否存在判定，故 CI clone（有 manifest、無 parquet）誤判快照存在、不 skip，於 `load_snapshot` 時 `FileNotFoundError`。已改為以 `prices/rates.parquet` 是否齊全判定 skip：CI 缺 parquet 乾淨 skip、本機有全套照跑（AC-3 本機閘門不變）。以「暫時隱藏 parquet 模擬 CI → 2 skipped、還原 → 2 passed」雙向驗證。**訂正**：Phase 2 的「CI 綠燈」紀錄實為此 manifest 提交之前的狀態；自 `6130e59` 起 CI 對 `requires_snapshot` 測試其實一直紅，至此修復。
- 2026-07-22：Phase 3 以 `--no-ff` 合併回 main（remote 先前已由 PR #2 合過同分支，改為對齊 origin/main + cherry-pick 缺的 docs 行，未硬推），並開 `feature/phase4-volatility`。
- 2026-07-22：**Phase 4a 波動率模型層完成**——`VolatilityModel` ABC（base.py，×100 估計/÷100² 還原與 α+β<1 檢查的單一出口，INV-4）、GARCH(1,1)-t via arch（解析多步）、EWMA(λ=0.94)（消融基線 + GARCH fallback）、多步年化聚合、`fit_volatility`（GARCH 失敗退回 EWMA + 標記）、QLIKE/MZ-R² 純函數與 walk-forward 評估驅動。**AC「GARCH vs EWMA QLIKE 比較表」達成**：真實快照 20 檔上 GARCH QLIKE 全面（20/20）勝 EWMA、MZ-R² 17/20 較高；共 241 次 fallback（HYG ~55% 最高）誠實留痕。全套測試 212 項綠。以 subagent-driven TDD 執行 11 個 task，實質程式模組經 spec + code-quality 兩段式 review。**順帶補建缺席已久的 INV-4 守護測試**（`test_garch_conventions.py`——CLAUDE.md 早列它為 INV-4 守護，但檔案一直不存在，INV-4 至此才真正有測試守護）。邊界：未碰 engine/策略，`mom_ivol` 仍用 rolling_std（待 4b 遷移）。6 處規格偏離見上方 Phase 4a 備忘。**4a 完成，Phase 4 尚有 4b（曝險+策略）/4c（bootstrap+消融）**。4a 完成後推 `feature/phase4-volatility` 至 origin 當雲端檢查點。
- 2026-07-22：**Phase 4b-1 基礎模組完成**——`portfolio/exposure.py`（波動目標 + 更新帶，唯一曝險出口；帶只作用於曝險檢查日）、`models/covariance.py`（過渡滾動樣本相關 Σ=D·R·D，投影 R 保 PSD+對角線=個別變異數，INV-3）、`VolForecaster`（refit/filter 分離 + 有上界滾動窗 `garch_window`=1000，成本 O(cap) 不爆炸）、`garch_filter_forecast`（arch `fix()` 固定參數濾波）。全套測試 242 項綠。以 subagent-driven TDD 執行 7 個 task，實質模組經 spec + code-quality 兩段式 review。**順帶補建缺席已久的 INV-3 守護測試**（`test_covariance_valid.py`——與 INV-4 同，CLAUDE.md 早列卻不存在；經 mutation 驗證有牙齒）。過程 review 補強：covariance 出口拒絕非有限 R、GARCH `arch_model` 規格單一來源、filter 補守護、cache 改 dataclass。邊界：未碰 engine/策略，待 4b-2 組裝（含 stale-cache 呼叫端契約）。4 處規格偏離見上方 Phase 4b-1 備忘。
- 2026-07-22：**Phase 4b-2 策略 + engine 接線完成**——engine log-only decision（`Decision.execute`：band-blocked 曝險檢查落診斷不交易，§1.7/§6.2）、`VolTargetStrategy` 曝險機制基底（selection refit / exposure-check filter / build_covariance→portfolio_vol→target_exposure→最終權重）、`voltarget_only`（SPY，波動目標乾淨測）、`full`（動量+inverse-vol+absmom+波動目標，§1.6 Step 3 權重公式）、`mom_ivol` 遷移到 GARCH σ̂（與 full 同估計器，消融 apples-to-apples）、`Diagnostics` 決策當下記 `vol_fell_back`/`garch_params`（§6.2）、config `corr_window`(252) + `vol_model` 預設翻 `garch_arch`（§5.2 GARCH 轉正）。**七策略齊備**。全套測試 270 項綠。以 subagent-driven TDD 執行 12 個 task，實質模組經 spec + code-quality 兩段式 review。過程 review 補強：VolForecaster eager spec 驗證、forecast_selected 共用 helper、log-only pd.isna 契約。**σ*±2% AC 條件化重定義**（voltarget_only 全期 / full 限 absmom 大致全過期間，隔離波動目標層）。6 處規格偏離見上方 Phase 4b-2 備忘。**邊界：4c 做 bootstrap + 七策略消融全表 + σ*±2% 條件式量測**。
