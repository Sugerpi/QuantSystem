# QuantCore 開發進度追蹤

> 依據 `DEVELOPMENT_GUIDE v1.2.md` §9「開發順序與里程碑」。
> 規則：**每個 Phase 的 AC（驗收條件）不過，不進下一階段。**
> 最後更新：2026-07-31

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
| 4 | 波動率模型與波動目標 | ~1-2 週 | ✅ 完成（全 AC 達成） |
| 5 | DCC 與 ERC | ~1 週 | ✅ 完成（5a 相關模型層 + 5b ERC，全 AC 達成）|
| 6 | 手刻 GARCH（學習里程碑） | ~2-3 週 | ✅ 完成（parity 達成；轉正刻意不做，見備忘）|
| 7 | Dashboard 與研究報告 | ~2.5 週 | 🟨 進行中（7a 唯讀 dashboard 9 頁 ✅、AC① 達成；7b Run Lab/7c 報告 待）|

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

## Phase 4 — 波動率模型與波動目標　✅

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
- [x] block bootstrap（stationary block，配對差異檢定，§6.4）— 4c
- [x] 平均曝險、子期間分析、σ*±2% 條件式量測、`momentum_select` 抽取 — 4c

### AC（全部達成 ✅）
- [x] **已實現波動落 σ*（10%）±2%（條件化重定義，設計 4b-2 §7）**：實測（快照 `2026-07-16_20ed09`）——`voltarget_only`（無 absmom）全期實現波動 **9.64%**；`full` 在 absmom 大致全過期間（轉現金比例 ≤10%，4553/5162 日）**9.86%**、嚴格版（=0，4532 日）**9.86%**——皆落 8-12%，波動目標幾乎精準命中 σ*=10%。
- [x] **GARCH vs EWMA 的 QLIKE 比較表產出**（4a 達成：GARCH QLIKE 20/20 檔勝 EWMA）
- [x] **七策略消融全表產出**（4c 達成：baseline 比較表 + `full` vs 各消融版配對 bootstrap CI；§7.3 敏感度全格另跑）

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
- **整體 holistic review 補的消融守護**：抓到「full vs mom_ivol 只差曝險層」這條**橫跨模組的科學不變量原本只靠註解守、無測試**——補了回歸測試 `test_full_and_mom_ivol_share_selection_layer`（同一 view 上兩者 selected/sigma_hat/w_risky 須相等，任一份選擇序列 copy 漂移即紅燈）。並把 `_vol_window_fits_available_history` 約束 gate 在 `vol_model=="rolling_std"`（garch_arch 不用 vol_window，休眠參數不再誤否決合法配置）。
- **backlog（4c 前處理）**：動量選擇序列（eligible→動量→top_k→absmom）現在 `MomentumStrategy.decide` 與 `Full._select_and_weight` 各一份（已加交叉引用註解 + 上述等價回歸測試守）——4c 消融跑之前抽 `momentum_select` 共用，讓一致性由結構而非測試保證。GARCH 診斷的 strategy-layer 端到端覆蓋亦待 4c 真實快照跑到。

### Phase 4b-2 邊界
七策略齊備（bh_spy/ew_menu/sixty_forty/mom_only/voltarget_only/mom_ivol/full）、GARCH 為預設 vol 來源、曝險機制與 band 落盤完整。**4c 做 block bootstrap + 七策略消融全表 + σ*±2% 條件式量測 + 子期間分析**，屆時 Phase 4 全部 AC 達成。

### Phase 4c 實作備忘（與原規劃的差異，詳見設計文件 `phase4c-*` §8）
1. **抽 `momentum_select` 共用**（還 4b-2 backlog）：選標的序列從 `MomentumStrategy.decide` 與 `Full._select_and_weight` 兩份複本抽為單一模組函數——消融 apples-to-apples 由結構保證，非靠測試。等價回歸測試保留為防呆。
2. **stationary block bootstrap 用配對差異檢定**：§6.3 只說「優勢在 CI 下站得住」，未指定做法；對同一組塊索引重抽兩序列取差（非各自 CI 比重疊，後者統計上錯）。RNG 走 `cfg.seed`（INV-6）。
3. **σ*±2% AC 條件化 + 日層級閾值操作化**：`voltarget_only` 全期乾淨測、`full` 在 absmom 轉現金比例 ≤ `absmom_cash_threshold`(0.10) 的日子量。
4. **新增 `stats` config 區塊**（bootstrap/子期間/閾值）；`average_exposure` 補入 metrics（§6.4 列為必附但 Phase 2 未含）；`sharpe` 補 n<2 守護（比照 sortino）。
5. **bootstrap 只對 baseline 格做**（參數格 13×7×1000 過貴，§6.3 驗收只需 baseline 的 full vs 消融版）。

### Phase 4c 實測結果與**誠實科學結論**（快照 `2026-07-16_20ed09`）
- **σ*±2% AC ✅**：`voltarget_only` 全期 9.64%、`full` 閾值 9.86%/嚴格 9.86%——波動目標幾乎精準命中 σ*=10%。σ* AC 的條件化重定義在此快照期間影響甚微（full 兩版皆 9.86%），因波動目標把組合波動穩在 ~10% 不論 absmom 是否介入——但條件化仍是正確的原則性量測。
- **消融全表 ✅ 產出**（baseline，依 Sharpe）：`full` MaxDD **−14.4%（全場最佳）**、Calmar **0.51（全場最高）**（vs mom_ivol −26%/0.39、bh_spy −55%/0.20）——回撤控制明顯較好；平均曝險 full 0.72、voltarget_only 0.67、mom_ivol 0.95。
- **§6.3 誠實結論**：`full` 對**每個**消融版的 Sharpe/Calmar 配對 bootstrap CI **皆含 0**（`excludes_zero=False`）——優勢在 95% 區間下**不顯著**。point estimate 偏向 full（尤其 Calmar/回撤），但 stationary block bootstrap 下未達統計顯著。**這是 §6.3 明言的合格結論**（「無顯著貢獻也是合格、甚至更誠實」）：波動目標層改善回撤（point estimate）、但本樣本期未證明其對風險調整報酬有統計顯著貢獻。§7.3 完整敏感度格的穩健性見下方變更紀錄補記。
- 七策略消融 + σ*±2% 量測以 `requires_snapshot` 本機閘門 `test_phase4_ac.py` 守護（CI 無快照乾淨 skip，比照 Phase 2 AC-3）。

### Phase 4 最終 holistic review 後修正（merge 前）
- **σ*±2% 條件式量測的管轄選擇 off-by-one（AC 頭號交付物的 correctness bug）**：`full_conditional_realized_vol` 原以 `searchsorted(side="right") - 1`（最後一個 exec ≤ 報酬日）決定某報酬日由哪次 selection 治。但引擎 within-day 順序為**損益→漂移→執行→決策**（`engine.py:62,65-69`、docstring 明述刻意把損益排在執行前「以免新權重賺到它生效之前的報酬」）——故某日 t 的報酬由「進入 t 的權重」earned，即 execution_date **嚴格 < t** 的最後一次 selection；t 當日剛執行的新權重要到 t+1 才生效。`≤` 把「執行當日」的報酬錯歸給剛執行的那次選擇。已改 `side="left"`。此缺陷逐 task review 看不到（reader 的 `≤` 自洽、有測試、且與設計 §4「execution_date ≤ 該日」字面一致），僅把 reader 對上引擎的「報酬先於執行」慣例才現形。**AC 閘門 `test_phase4_ac.py` 重跑通過**（559s，`full_threshold` 仍落 σ*±2% 的 8-12%）——修正只重歸屬「每個 selection 邊界一天」的報酬，餘裕寬故不翻盤；量測管轄自此與引擎慣例一致。
  - 附帶：原本隨此 bug 一起交付的「防呆」測試 left/right 都給同一個 count（兩邊界日互相抵消）、**無鑑別力**；已替換為跨邊界錯歸的鑑別性測試（前選失敗、後選通過，焦點日為後選執行日，正確須排除 → `side="right"` 得 3、`side="left"` 得 2），先驗 RED 再修 GREEN。
- **子期間分析（§6.4「子期間分析產出」AC）無消費者**：`subperiod_metrics` 函數建了、測了，卻**沒有任何呼叫端**——AC 名列「產出」但實際沒產出。已接線進 `runner.py`：每策略的 metrics 加一個 `subperiods` 分解（依 `cfg.stats.subperiods` 切年），隨 `metrics.json` 落地、被 INV-6 content hash 自然覆蓋；不動 `write_artifacts` 簽名。新增 `test_runner.py::test_metrics_json_carries_subperiod_analysis`（有資料格帶完整 metrics、空格 `n_days=0`），先驗 RED 再修 GREEN。
- 全套件本機 303 passed / 0 skip（含 `requires_snapshot` 閘門，本機快照有 parquet）。

---

## Phase 5 — DCC 與 ERC　✅（5a + 5b，全 AC 達成）

依 brainstorming 切兩段：**5a 相關模型層**（DCC/EWMA-corr，✅）、**5b ERC 權重**（✅）。
設計/計畫見 `docs/superpowers/specs/2026-07-2{6,7}-phase5{a,b}-*-design.md`、
`docs/superpowers/plans/2026-07-2{6,7}-phase5{a,b}-*.md`。

### 任務
- [x] `models/correlation/base.py`（`normalize_to_correlation`，R 合法性單一出口，INV-3）— 5a
- [x] `models/correlation/dcc.py`（DCC(1,1) 兩步 QMLE，對稱化/shrinkage/正規化內部封裝）— 5a
- [x] `models/correlation/ewma_corr.py`（消融基線）— 5a
- [x] `models/correlation/forecaster.py`（`CorrelationForecaster` refit/filter，鏡射 VolForecaster）— 5a
- [x] `models/covariance.py`（Σ = D·R·D，唯一出口收斂、R 由相關層派發，INV-3）— 5a
- [x] ERC 權重選項（`portfolio/weighting.py` 的 `erc_weights` + `full_erc` 策略）— **5b**

### AC
- [x] **DCC vs EWMA 消融結論明確寫入報告**（見下方 5a 結論）——**5a AC 達成 ✅**
- [x] **ERC vs inverse-vol 消融結論明確寫入報告**（見下方 5b 結論）——**5b AC 達成 ✅**

### Phase 5a 實作備忘（與原規劃的差異，詳見設計文件 §4）
1. **手寫 DCC(1,1)（arch 無 DCC，Python 無可信套件）**：DCC 第二步（(a,b) QMLE + Q_t 遞迴 +
   R 正規化）自寫；單變量 σ_t 仍用 arch（Phase 4）。此為缺替代品、非 Phase 6 手刻里程碑。
   正確性以**合成回收測試**（已知 (a,b) 於 3000 樣本回收，含高持續性 a+b=0.98 邊界 + 雙 seed，
   誤差 <0.005）+ 不變量守護建立信心（無 arch 那樣的 parity 參照）。
2. **標準化殘差複用 VolForecaster**（`last_standardized_residuals` + `garch_filter_residuals`）：
   不讓相關層重跑單變量 GARCH；vol 與 corr 用同一組殘差、一致。
3. **`CorrelationForecaster` refit/filter 鏡射 VolForecaster**：貴的 (a,b) QMLE 每 63 交易日
   （=每 3 次選擇，內部計數器、免日曆、決定性）重估、便宜的 Q_t 遞迴每次決策；Q̄ 每次選擇隨
   輪動資產集重算。fixed 模式（`dcc_refit_interval=0`）用 `dcc_fixed_ab`、永不 QMLE。
4. **`corr_model` 預設翻 `ewma`**（Phase 4 曾誤設 dcc 但從未接線）：依 §5.3「DCC 須先打敗基線」
   紀律，接線後預設用已證 EWMA，DCC 消融勝出才翻。
5. **config**：新增 `dcc_refit_interval`（單鍵收攏 fixed/reestimate）、`dcc_fixed_ab`、
   `dcc_qbar_shrink`（Q̄ shrinkage，原為硬編常數、依 CLAUDE.md 無魔術數字規則移入 config）；
   **移除死參數 `corr_window`**（過渡 rolling 相關退役後無消費端）。
6. **`rolling_correlation` 退役**（Phase 4 過渡 placeholder）；基線改為 EWMA-corr（§5.3）。

### Phase 5a 過程中補強（兩段式 review 抓到並修，8 項）
- **`normalize_to_correlation` 對零變異數對角線塌陷改為拋錯**（原靜默 `d==0→1` 產出 R_ii=0）：
  新 EWMA/DCC 走 `np.cov`、常數欄給 0 逃過 finiteness 檢查 → 靜默腐蝕下游變異數（相對舊 rolling
  經 corrcoef→NaN→拋錯 為安全退步）。誠實失敗，比照 `portfolio_vol`/`inverse_vol`。
- **`DccParams` `eq=False`**：frozen dataclass 含 ndarray 欄位，預設 `__eq__/__hash__` 會拋錯。
- **`estimate_dcc` 加 `fell_back` 觀測信號 + 收窄 `except`**：消融比較 reestimate vs fixed，若重估
  靜默退回 fixed 會使消融失真；且原 `except` 把零變異數/shrink 非法一併吞回（抵銷上一項 hardening）。
- **`CorrelationForecaster` reuse 分支保留 `fell_back`**（否則 2/3 選擇日漏算 fallback）+ cadence
  spy 測試（鎖 fixed-vs-reestimate 命脈）。
- **`dcc_fixed_ab` 拒非有限值**（NaN/inf，比照 estimate_dcc/forecast 的 isfinite 慣例）。
- **整合任務修掉跨模組潛在 bug**：`ticker_returns` 原 `reset_index(drop=True)` → 殘差帶 RangeIndex，
  使 DCC/EWMA 的 `pd.concat` **按位置而非日期對齊**（不同歷史長度資產會靜默錯位、INV-3 驗不到）。
  改 `set_index("date")` 修正（`garch_filter_residuals` docstring 早已聲稱「帶 DatetimeIndex 供 DCC」
  卻為假）。並加 `_collect_std_residuals` 逐檔新鮮度斷言（點名 stale offender）。

### Phase 5a AC 實測與**誠實科學結論**（快照 `2026-07-16_20ed09`，full & voltarget_only）

| 配置 | 策略 | Sharpe | MaxDD | Calmar | 平均曝險 | 實現年化波動 |
|------|------|--------|-------|--------|---------|------------|
| ewma | full | 0.602 | −14.9% | 0.489 | 0.731 | 9.68% |
| dcc-reest | full | 0.591 | −14.9% | 0.486 | 0.734 | 9.75% |
| dcc-fixed | full | 0.600 | −14.8% | 0.497 | 0.738 | 9.84% |
| （任一）| voltarget_only | 0.580 | −24.3% | 0.288 | 0.666 | 9.58% |

- **voltarget_only 三相關模型下完全相同**（K=1 只有 SPY，R=[[1]]）——結構性驗證「相關只在 K>1 有作用」。
- **σ*±2% AC 兩相關模型皆守**：full/voltarget 實現波動全落 8–12%（`test_phase5a_ac.py` 本機閘門，
  ewma/dcc 兩參數皆過）。
- **配對 bootstrap（full：dcc-reest − ewma，§6.3）**：Sharpe 差 −0.011、CI [−0.031, +0.010]、**含 0**；
  Calmar 差 −0.003、CI [−0.040, +0.011]、**含 0**。point estimate 甚至微偏 EWMA。
- **DCC 估計稽核**：`dcc-reest` 全期 82 個 QMLE 重估點僅 **1 次（1.2%）** fell_back 到 fixed_ab——
  DCC 在 98.8% 重估點真的估出 (a,b)，故「無顯著貢獻」反映的是**真實 DCC 估計**、非大量靜默退回 fixed
  的假象（且 dcc-reest 0.591 ≠ dcc-fixed 0.600 兩列有差亦佐證 QMLE 有作用）。
- **§5.3 合格結論**：**DCC 對 EWMA 無統計顯著貢獻**（配對 CI 皆含 0、點估計微偏 EWMA）。
  **v1 出貨用 EWMA（已設為預設），DCC 留作 config/研究選項**。這是規格明言「DCC 沒有顯著貢獻也是
  合格、甚至更誠實」的結論——與 Phase 4c 一致、符合規格「文獻顯示兩者績效差距通常很小」。原因：相關
  只透過 σ̂_p 影響曝險純量，波動目標已把組合波動穩在 ~10%，top-5 籃子的 DCC/EWMA 相關差異不足以
  改變曝險。
- **效能**：profiling 單次 full 回測 ewma 51s / dcc-reest 167s（QMLE 主導）/ dcc-fixed 53s——本機
  AC 閘門可接受（比照 Phase 4 ~559s）。設計 review 提的兩個效能優化（negloglik 內迴圈對角 rescale、
  filter 單次 fix）**經 profiling 確認非必要，不做**（避免臆測性優化）。

### Phase 5a 最終 holistic review（opus）結果與待處理項
六條跨模組接縫逐一追查：refit/filter 節奏鎖步、K=1 退化路徑、「相關只影響 σ̂_p 不影響權重/選擇」
不變量無洩漏、殘差管線端到端決定性（INV-6）四條完全乾淨且有測試佐證；INV-3 守護已擴充至 DCC/EWMA
真實 R 來源。抓到 1 Important + 3 Minor：
- **I-1（Important）DCC `fell_back` 可觀測性死路**：`estimate_dcc` 產生、forecaster 保留，但無
  production 消費端（不進 `Diagnostics`/`decisions.parquet`），使研究結論的 fallback 佔比事後不可
  稽核。**已以實測 1.2%（見上）解決結論的可稽核性**；durable 落盤（`corr_fell_back` → decisions）
  **延到 Phase 7**（相關結構 dashboard 頁才消費，比照 vol_fell_back 當初也是 dashboard 需要才加）；
  `DccParams.fell_back` 已是 ready-to-wire 來源。
- **M-1** `vol_target_base.decide` SELECTION 分支 `self._cache=state` 設於相關步驟（可 raise）之前，
  例外續跑時下個曝險檢查會踩 `filter` 的 assert（實務上首個例外即中止 run、不可達）→ 5b 順手把賦值移後。
- **M-2** `rolling_correlation` 退役後為半死碼（僅測試引用）→ 5b/後續若不用即刪。
- **M-3** `_estimate_every=round(refit_interval/selection_interval)` 對非整數倍以四捨五入近似 →
  docstring 標「建議設為 selection_interval 整數倍」（現 63/21=3 乾淨，有 cadence 測試守）。

### Phase 5a 邊界
相關模型層完整（DCC/EWMA-corr、refit/filter、config 開關、消融結論可稽核）。**5b 做 ERC 權重選項 +
ERC vs inverse-vol 消融**（相關影響「配置」的通道，需優化器 + PSD），並順手處理 M-1~M-3。

### Phase 5b 實作備忘（與原規劃的差異，詳見設計文件 §4）
1. **ERC 走獨立策略 `full_erc` 而非 config 開關**：§5.3 說「作為 config 選項」，但為**不動已 5a-硬化的
   `full` inverse_vol 熱路徑**（ERC 預期無顯著貢獻），改以獨立策略隔離——選策略即選權重方案，語意等價
   且更安全。base 僅純提取 `_build_cov` + `_exposure_decision` 為共用 helper（行為不變，既有測試守）。
2. **`erc_weights` 用循環座標下降（Spinu CCD）而非 scipy 優化器**：長單由正根結構保證、決定性、無優化器
   失敗模式（§5.3「inverse-vol 沒有優化器收斂失敗模式」的精神）；未收斂誠實拋錯（比照 estimate_dcc）。
3. **無新 config 欄位**：ERC 求解器常數（tol/max_iter/暖啟）為演算法常數（比照 DCC `_A_START`）。
4. **`FullErc._select_and_weight` = raise NotImplementedError**：用自有 cov-first decide()，避免 base
   尾段 double-refit 相關預報器（刻意設計）。與 `full` apples-to-apples（同 momentum_select/σ̂/相關/曝險）。

### Phase 5b 過程中補強（兩段式 review 抓到並修）
- **`erc_weights` 單資產守護前置 + CCD 非收斂誠實拋錯**：n==1 短路原繞過對角線>0 檢查；未收斂原靜默回
  最後迭代值（違誠實失敗慣例）。補近奇異 Σ 收斂測試。
- **apples-to-apples 測試改用 K≥3**：**K=2 時 ERC ≡ inverse-vol**（數學事實：解 RC_1=RC_2 + Σw=1 →
  w_i ∝ 1/σ_i，相關項消掉），原 top_k=2 的「權重不同」斷言只靠 ~1e-13 求解器噪音才過、無鑑別力。
  改 K=3（權重實測分歧 ~0.034），並加測試明文鎖住 K=2 恆等式。

### Phase 5b AC 實測與**誠實科學結論**（快照 `2026-07-16_20ed09`，corr_model=ewma）

| 策略 | Sharpe | MaxDD | Calmar | 年化換手 | 平均曝險 |
|------|--------|-------|--------|---------|---------|
| full（inverse-vol）| **0.602** | **−14.9%** | **0.489** | 6.31 | 0.731 |
| full_erc（ERC）| 0.587 | −17.4% | 0.413 | 6.73 | 0.747 |

- **配對 bootstrap（full − full_erc，§6.3）**：Sharpe 差 +0.015、CI [−0.041, +0.071]、**含 0**；
  Calmar 差 +0.076、CI [−0.042, +0.087]、**含 0**。
- **§5.3 合格結論**：**ERC 未打敗 inverse-vol**——point estimate 甚至**微偏 inverse-vol**（full 的
  Sharpe/Calmar 皆較高、ERC 回撤 −17.4% 較差、換手 6.73 較高），但差異不顯著（CI 含 0）。§5.3 明言
  「ERC 必須在消融中打敗 inverse-vol 才轉為預設」——它沒有，故 **v1 續用 inverse-vol（預設不變），
  ERC 留作 `full_erc` 研究/選項策略**。乾淨印證規格「先簡後繁是紀律」「文獻顯示兩者績效差距通常很小」
  ——inverse-vol 更簡單、無優化器/PSD 需求、且在本樣本期點估計上還略勝。
- **附帶觀察**：ERC 讓相關結構首次影響配置本身（inverse-vol 下相關只影響曝險純量），但即便如此
  ERC 仍未勝出——與 5a「DCC 對 EWMA 無顯著貢獻」一致，複雜度在本樣本期均未自證其值。
- 以 `requires_snapshot` 本機閘門 `test_phase5b_ac.py` 守護（full/full_erc 皆跑完整回測 + 配對 bootstrap）。

### Phase 5b 最終 holistic review（opus）結果
六條接縫逐一追查全乾淨：full/full_erc apples-to-apples 結構性成立（同 momentum_select/σ̂/Σ/曝險、
w_risky 不回饋 forecaster 狀態、共用單一 clock、corr 每決策一次不 double-refit）、相關→權重通道正確
（erc_weights 與 σ̂_p 用同一 Σ）、`_select_and_weight` 的 NotImplementedError 經引擎不可達、K=1/absmom
轉現金/band-blocked 邊界皆守、決定性守。無 Critical/Important。三個 Minor：
- **M1（已修）** base docstring 過時（未提 full_erc 覆寫 decide()）→ 已更新。
- **M2（v1 刻意語意）** ERC 下曝險檢查：相關漂移期內只反映在曝險純量、權重到下次選擇才重配（與
  inverse-vol 對稱、pre-existing 曝險設計）。新語意面：相關現在也設權重、但只在選擇節奏——v1 可接受。
- **M3（backlog）** `_ERC_TOL` 為未正規化權重的絕對容差（隨 cov 尺度耦合）；因 build_covariance 單一
  尺度入口而穩定、所有測試（含 ρ=0.98 近奇異、非收斂）皆過，非 live 缺陷。日後可改相對/正規化後容差。

### Phase 5 邊界
**Phase 5 全部 AC 達成 ✅**（DCC vs EWMA、ERC vs inverse-vol 兩消融結論皆明確寫入、皆為 §5.3 合格的
「無顯著貢獻」結論）。v1 生產路徑：**EWMA 相關 + inverse-vol 權重**（兩個簡單基線皆未被進階版打敗）；
DCC 與 ERC 保留為 config/研究選項。可進 Phase 6（手刻 GARCH）。

---

## Phase 6 — 手刻 GARCH（學習里程碑）　✅（parity 達成；轉正刻意不做）

`garch_own.py`：Student-t log-likelihood、變異數遞迴、L-BFGS-B 數值優化、多步解析預測。
以學習為導向的走查式開發（非 subagent）——四零件逐一講解後手寫、以 arch 為 parity 參照。

### 任務
- [x] `models/volatility/garch_own.py`（手刻 GARCH(1,1)-t、L-BFGS-B；四零件：遞迴/likelihood/優化/多步預測）
- [x] parity test（vs arch，§5.2；`tests/test_models/test_garch_parity.py`，本機閘門）
- [x] 推導筆記（技術寫作樣本，使用者自備）
- [x] CI 單元測試（`tests/test_models/test_garch_own.py`，合成資料 + 四零件純函數，快照缺席時仍守）

### AC
- [x] **parity test 通過**（§5.2 標準）——快照 `2026-07-16_20ed09` 19/20 檔（HYG 退化跳過），
      參數 (ω,α,β,ν) 最差相對誤差 **0.0284%**（門檻 1%，~35× 餘裕）、21 步年化波動預測最差 **0.0019%**
      （門檻 0.5%，~260× 餘裕）——手刻版與 arch **數值上幾乎完全等價**。
- [~] **轉正為預設 `vol_model`**：**刻意不做**（見下方誠實結論）。parity 已證等價，但手刻版 8.7× 慢、
      翻預設零數值好處，故保留 `garch_arch` 為預設。AC 的可測核心（parity 正確性）達成；「轉正」為
      規格附帶的學習/履歷 consequence，經量測後由使用者拍板不做。

### Phase 6 實作備忘（與原規劃的差異）
1. **走查式（walk-through）開發、非 subagent-driven**：本 Phase 為學習里程碑，使用者要求逐段看 code
   如何生成。四零件（變異數遞迴 → Student-t likelihood → L-BFGS-B 目標/優化 → 解析多步預測）逐一講解、
   手寫、組進 `GarchOwn(VolatilityModel)`。仍守 TDD：parity test 先 RED → 建檔 → 迭代到 GREEN。
2. **parity 過程抓出兩個真 bug（TDD 的價值）**：(a) σ²_0 種子原用樣本變異數 → EEM 的 ω 差 1.795%（>1%）；
   換成 **arch 的 backcast**（前 min(75,n) 筆殘差平方的 0.94^i 加權平均、優化前算一次固定、
   σ²_0 = ω+(α+β)·backcast）後 ω 降到 <0.01%。(b) L-BFGS-B 預設 `gtol=1e-5` 在參數尺度橫跨兩數量級
   （ω~0.04、β~0.9、ν~8）時，大尺度參數先收斂即過早停手，留 **ν 卡在起始值 8.0**（LQD 差 5.17%）；
   收緊容差（`ftol=1e-12, gtol=1e-8, maxiter=1000, maxfun=20000`）逼優化到底後 ν <0.03%。
3. **數值梯度（非解析梯度）**：依 brainstorming「先數值、之後可選深化解析」。解析梯度為當初延後的學習深度
   加分關卡，未做——若日後要翻預設、需追速度時再補（數值梯度是 8.7× 慢的主因）。
4. **標準化殘差用「原始 scaled return / 條件波動」**（非去均值），刻意與 `garch_arch:64`/`Ewma` 一字不差，
   確保 Phase 5 DCC 的殘差輸入三模型間一致（契約一致 > 局部數學正確）。
5. **平穩性（α+β<1）交給 base 事後檢查**：L-BFGS-B 只吃箱型邊界、無法表達跨參數線性不等式；箱型約束
   α,β∈[0,1) + base 的 `enforce_stationarity` 事後擋（≥1 → GarchDegenerateError → fallback EWMA），
   與 `garch_arch` 同模式、忠於規格「L-BFGS-B」選擇。
6. **`garch_own` 未接進生產派發**（`fit_volatility`/`VolForecaster`）：預設是 arch、且手刻版無便宜 filter
   路徑（arch 的 `fix()` 濾波專屬 arch）。日後若要當 live 研究選項再補 filter，屬後續工。config 的
   `VolModel` Literal 早已含 `garch_own`（Phase 0 placeholder），設它會在 VolForecaster eager 驗證誠實 fail。

### Phase 6 誠實科學結論（快照 `2026-07-16_20ed09`）
- **parity 幾乎完美**：19 檔全參數 <0.03%、預測 <0.002%——手刻 MLE 與 arch 的 C 核心數值等價。
- **效能量測**：手刻版 **617 ms/fit vs arch 71 ms/fit = 8.7× 慢**（純 Python 順序遞迴 + 數值梯度
  vs arch 的編譯核心）。
- **§5.2 結論與決策**：規格 AC 含「parity 後轉正為預設」。但翻預設換來的只是「手刻版即生產路徑」的
  敘事，代價是**每次回測 8.7× 慢、零數值好處**（可證等價）。**使用者拍板不翻**：`garch_arch` 續為
  生產預設（快），`garch_own` 為已 parity 驗證的替代/研究路徑 + 學習成品。學習目標（親手實作並證明
  數值等價）已 100% 達成；「轉正」的效能稅不值得付。日後若要翻預設，先補解析梯度追回速度（見備忘 3）。

### Phase 6 邊界
手刻 GARCH 完整、parity 驗證、CI 覆蓋齊備。預設 vol 路徑不變（`garch_arch`）。可進 Phase 7（Dashboard）——
其 GARCH 頁「手刻 vs arch parity」對照頁籤（§11.2 表列）的資料來源即本 Phase 的 parity 產物。

---

## Phase 7 — Dashboard 與研究報告　🟨

依 brainstorming 定案，7a 切成：**引擎診斷落盤（計畫 1，✅）**、**presentation readers 地基（計畫 2a，✅）**、
**dashboard UI 9 頁（計畫 2b＝2b-1 核心 3 頁 + 2b-2 其餘 5 頁，✅）**。之後 7b Run Lab、7c 研究報告。
設計/計畫見 `docs/superpowers/specs|plans/` 的 `phase7a-*`。**7a 唯讀 dashboard 段完成、AC① 達成。**

### 任務
- [x] **計畫 1 引擎落盤**：`trade_deltas`、`corr_fell_back`/residuals accessor、`Diagnostics` corr_matrix/corr_fell_back 接線（含 5a M-1）、engine trade blotter（`run_strategy` 回 4-tuple）、runner 攤平 correlation/residuals、`write_artifacts` 落盤 `trades.parquet` + `model_details/{correlation,residuals}.parquet`、blotter fill_price 誠實守護
- [x] **計畫 2a readers**：`presentation/readers.py` 16 函數（run 載入 / Decision Explorer 六層 / model_details / 快照 / list_runs）+ AST 架構守護測試（§2.2 紅綠燈）
- [x] **計畫 2b UI**：`presentation/app.py`（st.navigation）+ `controls` 全域控制列 + 9 頁 Streamlit（§11.2 原 8 頁 + 新增頁 9「價格與交易」；頁 8 Run Lab 為 stub）+ AppTest smoke + AC① 人工手查
- [ ] 7b：Run Lab（`presentation/jobs.py`、subprocess、status.json 合約，§11.3）
- [ ] 7c：最終研究報告（以消融表為骨架）

### AC
- [x] **AC① 達成**：自動化——Decision Explorer 六層抽取 golden 測試（`readers.decision_layers` 逐層對上獨立解析的 decisions.parquet；含 null/log-only 路徑）；人工——真實 run `canonical_ewma`/full/2016-04-06 六層 11 項 vs `decisions.parquet` 逐格一致（`docs/phase7a-ac1-handcheck.md`）。頁 2 Decision Explorer 為其 UI 出口。
- [ ] 從 Run Lab 提交新 config 並完整跑完回測，全程不碰終端機（7b）
- [ ] UI 行程強制終止再重啟後，運行中 job 狀態與進度無損（7b）

### Phase 7a 計畫 1 實作備忘（與原規劃的差異）
1. **7a 含引擎端落盤**（非純展示層）：頁 3/4/9 所需診斷（相關矩陣、標準化殘差、blotter）Phase 4/5 引擎未落盤；使用者定案採「補落盤 + 重跑」而非優雅退化。了結 **Phase 5a I-1**（`corr_fell_back` 現 durable 落 `decisions.parquet`）。
2. **新增第 9 頁「價格與交易」**（§11.2 8 頁 + 報告陳述需要擴充）；`trades.parquet` 為新一級 artifact（每執行日 per-ticker 精確成交，由 `accounting.trade_deltas` 接出 + 執行日 adj_close）。
3. **Decision Explorer 層 d 只呈現年化 σ̂ + 前次對照**（非 21 步曲線，逐步曲線歸頁 3）——避免為單頁重跑引擎。
4. **INV-6 content_hashes 只納入 `trades.parquet`**（一級結果、與 nav turnover/cost 對帳）；`model_details/*` 為深掘診斷不進 identity 合約。
5. **對帳誠實閘門**：blotter 逐執行日 `Σ|Δw|==nav.turnover`、`Σcost==nav.cost`（結構保證，測試守）；fill_price 非正有限值誠實拋錯（final review）。

### Phase 7a 計畫 1 實測與驗證（快照 `2026-07-16_20ed09`）
- 重跑 2 canonical run（`corr_model=dcc`/`ewma`，全 8 策略）；**blotter 逐執行日對帳零誤差**（~25,800 筆交易，兩 run）。
- correlation.parquet 僅 `full`/`full_erc`（voltarget K=1 略）；residuals 涵蓋 3 個 vol-target 策略、20 檔。
- **dcc `corr_fell_back` 佔比 1.22%**，獨立重現 Phase 5a 記錄的 1.2% DCC fallback——結論可稽核性由 durable 落盤確立。
- 全套件（含 7 個 `requires_snapshot` AC 閘門）+ INV-3/5/6 綠、ruff 乾淨。opus holistic review 判「ready to merge」（2 Minor：fill_price 守護、`_BPS` 單一來源，皆已修）。

### Phase 7a 計畫 2a 實作備忘
1. **薄頁面、胖 readers**：所有 JSON 欄解析與檔案載入集中 `readers.py`；缺 `trades.parquet`/`model_details/` 回 `None`（§0「本次未儲存」，斷 `store_details` pickle 舊教訓）。
2. **§2.2 邊界紅綠燈化**：AST 架構守護測試掃 `presentation/` 全樹、`readers.py` 只 import stdlib/pandas/yaml——**holistic review 抓到並修掉守護的真實 bypass**（`from quantcore import backtest` 只看 `node.module` 會漏；已展開 `PKG.NAME`），並讓 teeth 測試走真實偵測碼（原為平行 inline 檢查、無鑑別力）。
3. **AC① 自動化**：`DecisionLayers` + `decision_layers` 六層抽取，golden 逐層對上獨立 `json.loads` 的原始 decisions 列（含 executed 與 null/log-only band_blocked 兩路徑）；`decision_layers` 多列誠實拋錯（無靜默 fallback）。
4. 以 subagent-driven TDD 執行 8 個 task，實質模組經 spec + code-quality 兩段式 review + 一次整體 holistic review；23 presentation 測試綠，真實 canonical run 冒煙通過。

### Phase 7a 計畫 2b 實作備忘（dashboard UI 9 頁）
1. **架構**：`st.navigation` 多頁（明確中文標題、取代 auto-`pages/`）+ `controls.render_sidebar` 每頁前執行寫 `st.session_state`；頁面薄——讀 `controls`+`readers`+plotly 畫圖，缺資料 `st.info` 優雅。streamlit 1.59 + plotly + scipy（QQ）。以 `streamlit.testing.v1.AppTest` 冒煙（seed session_state 測單頁）。
2. **9 頁**：1 總覽（NAV 對數疊圖/指標/回撤/曝險/子期間）、2 決策解剖（AC① UI，六層瀑布讀 `decision_layers`）、3 GARCH（參數軌跡/persistence/fallback/QLIKE·MZ-R²/殘差 QQ+ACF）、4 相關結構（熱圖時間滑桿/資產對序列/頁內第二 run 疊 DCC vs EWMA）、5 組合與成本（權重堆疊/曝險帶事件/換手成本）、6 消融（指標表/敏感度熱圖/配對 bootstrap CI）、7 資料品質（MANIFEST/資料源/overrides/tickers）、8 Run Lab（stub→7b）、9 價格與交易（adj_close 折線+買賣標記+blotter）。
3. **AST 架構守護擴至 app/controls/pages**（§2.2）——全 presentation 樹不 import 引擎。以 subagent-driven TDD 執行（2b-1 八 task、2b-2 七 task），實質頁面經 spec + code-quality review + 各段一次 holistic review（2b-1 holistic 實測啟動 Streamlit server HTTP 200 + live 重算 AC① 數字）。
4. **spec review 抓到 §11.2 頁 3 兩缺項（記 backlog）**：條件波動 vs 已實現波動 proxy 疊圖（刻意延，需快照報酬對齊）；「手刻 vs arch parity」對照頁籤（**卡引擎**：parity 結果未落盤 `runs/`，需引擎端先吐 parity artifact 才能做）。
5. **開啟即崩潰 bug 修正（使用者實測抓到）**：側欄預設選字母序最後 run，`runs/vol_eval`（有 manifest、無 nav）排最後 → 總覽頁 `load_nav` 一開就 `FileNotFoundError`。冒煙測試皆明確指定 backtest run、從未走「預設選非回測 run」路徑而漏抓。修：`readers.is_backtest_run`（判有無 nav）+ 頁 1/2/3/5 對非回測 run 優雅提示；側欄預設優先選有 `strategies` 的回測 run（實測預設落 `canonical_ewma`、入口不崩潰）。加回歸測試鎖住。

### Phase 7a backlog（誠實記錄，延 7b/後續）
- 頁 3「條件波動 vs 已實現波動 proxy 疊圖」、「手刻 vs arch parity」對照頁籤（後者需引擎補 parity 落盤）。
- `st.cache_data` 快取讀取路徑（Decision Explorer/相關 slider 每 tick 重讀 parquet）；全域多 run 疊圖（現各頁只讀第一個選中 run，頁 4 以頁內第二 run 選擇器折衷）。
- §11.2 richer：NAV vs benchmarks、指標 bootstrap CI 進總覽、層 a 未合格「灰顯標原因」（需引擎補排除原因欄）、層 c fail→現金流視覺化。
- `use_container_width`→`width`（streamlit 已 deprecate，1.59 仍可用）；頁面 smoke 覆蓋補齊（no-decisions/多 run 分支）。

### Phase 7a 邊界（目前）
引擎診斷落盤 + readers 地基 + **唯讀 dashboard 9 頁完整、AC①（自動化+人工）達成、可 `uv run streamlit run quantcore/presentation/app.py` 啟動**。**尚待 7b Run Lab（引擎端 status.json 心跳 + job runner + subprocess CLI + 崩潰復原，AC②③）、7c 研究報告。** 分支 `feature/phase7a-dashboard` 保留現狀（未併回 main；其下疊著未併的 phase6）。

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
- 2026-07-24：**Phase 4c 完成，Phase 4 全部 AC 達成**——抽 `momentum_select` 共用（消融選擇由結構保證一致）、stationary block bootstrap（配對差異檢定 full vs 消融版，seed 走 config 守 INV-6）、平均曝險、子期間分析（2005-09/2010-19/2020-）、σ*±2% 條件式量測（`vol_target_ac.py` 讀 run 產物、日層級閾值子集）、七策略消融全表 + baseline 配對 bootstrap。全套測試 300 綠（+ `requires_snapshot` 本機 AC 閘門）。以 subagent-driven TDD 執行 10 個 task。**AC 實測**：voltarget_only 全期實現波動 9.64%、full 閾值/嚴格版 9.86%（皆落 σ*=10%±2%）；七策略消融表產出。**誠實科學結論**：full 的 MaxDD −14.4%/Calmar 0.51 為全場最佳（回撤控制明顯較好），但對每個消融版的 Sharpe/Calmar 配對 bootstrap CI 皆含 0（優勢不顯著）——§6.3 明言的合格結論，波動目標層在本樣本期未證明對風險調整報酬有統計顯著貢獻。5 處規格偏離見上方 Phase 4c 備忘。**Phase 4 全部 AC 達成 ✅**，消融結果即研究報告骨架。
- 2026-07-27：Phase 4 併回 main（remote 已由 **PR #3** 合過同分支，比照 Phase 3 對齊 origin/main、未硬推），並開 `feature/phase5-dcc-erc`。
- 2026-07-27：**Phase 5a 相關模型層完成，5a AC 達成**——`models/correlation/`（`normalize_to_correlation` R 合法性單一出口、DCC(1,1) 兩步 QMLE、EWMA-corr 基線、`CorrelationForecaster` refit/filter 鏡射 VolForecaster）、`covariance.py` 唯一出口收斂（R 由相關層依 `corr_model` 派發、`rolling_correlation` 退役）、標準化殘差管線複用 VolForecaster、config 加 `dcc_refit_interval`/`dcc_fixed_ab`/`dcc_qbar_shrink` 並移除死參數 `corr_window`、預設 `corr_model` 翻 `ewma`。全套測試 335 綠（+ `requires_snapshot` 本機 AC 閘門 `test_phase5a_ac.py`）。以 subagent-driven TDD 執行 12 個 task，實質模組經 spec + code-quality 兩段式 review，抓修 8 項實質問題（零變異數靜默腐蝕、frozen dataclass footgun、shrink 魔術數字、DCC 靜默 fallback 無信號、`ticker_returns` RangeIndex 跨模組對齊 bug 等，見上方備忘）。**手寫 DCC 正確性以合成回收測試建立**（已知 (a,b) 於 3000 樣本回收、含高持續性 a+b=0.98 邊界 + 雙 seed，誤差 <0.005；無 arch 那樣的 parity 參照）。**AC 誠實結論**：DCC vs EWMA 消融——full 在 ewma/dcc 下 Sharpe 0.602 vs 0.591、Calmar 0.489 vs 0.486、MaxDD 全 ~−14.9%、實現波動全落 σ*±2%；配對 bootstrap（dcc−ewma）Sharpe/Calmar CI 皆含 0、點估計微偏 EWMA——**DCC 無統計顯著貢獻，v1 出貨用 EWMA（預設）、DCC 留 config/研究選項**（§5.3 明言的合格結論，與 Phase 4c 一致）。voltarget_only（K=1）三相關模型下完全相同，結構性驗證相關只在 K>1 有作用。6 處規格偏離見上方 Phase 5a 備忘。5a 完成後推 `feature/phase5-dcc-erc` 至 origin 當雲端檢查點。
- 2026-07-29：**Phase 6 手刻 GARCH 完成（parity 達成；轉正刻意不做）**——`models/volatility/garch_own.py`
  四零件手刻（變異數遞迴 / 標準化 Student-t log-likelihood / L-BFGS-B 數值優化 / 解析多步預測），繼承
  `VolatilityModel` base、與 `garch_arch` 走同一份契約。以學習為導向的走查式開發（逐段講解 code 生成、
  非 subagent），仍守 TDD（parity test 先 RED → 建檔 → 迭代 GREEN）。**parity 對 arch 幾乎完美**：快照
  `2026-07-16_20ed09` 19/20 檔（HYG 退化跳過），參數 (ω,α,β,ν) 最差 0.0284%（門檻 1%）、21 步預測最差
  0.0019%（門檻 0.5%）。過程中 parity 抓出兩個真 bug 並修（σ²_0 種子改用 arch backcast、ν 卡起始值改收緊
  L-BFGS-B 容差，詳見備忘）。補 CI 單元測試 10 項（合成 + 四零件純函數，快照缺席仍守）。全套 365 綠。
  **效能量測**：手刻版 617 ms/fit vs arch 71 ms/fit = 8.7× 慢。**§5.2 決策**：翻預設換來的只是敘事、代價
  是每次回測 8.7× 慢且零數值好處（可證等價）——**使用者拍板不翻**，`garch_arch` 續為生產預設，`garch_own`
  為已驗證的替代/研究路徑 + 學習成品。學習目標 100% 達成；「轉正」的效能稅不值得付（日後要翻先補解析梯度）。
  6 處規格偏離見上方 Phase 6 備忘。**Phase 6 學習里程碑達成 ✅**。
- 2026-07-27：**Phase 5b ERC 權重完成，Phase 5 全部 AC 達成**——`portfolio/weighting.py` 的 `erc_weights`（等風險貢獻，Spinu 循環座標下降：長單由正根結構保證、決定性、無優化器失敗模式、未收斂誠實拋錯）、獨立策略 `full_erc`（cov-first 自有 decide()，與 `full` apples-to-apples 只差權重層，不動已 5a-硬化的 inverse_vol 熱路徑）、base 純提取 `_build_cov` + `_exposure_decision` 共用 helper（行為不變、corr 每決策一次）。無新 config（ERC 求解器常數為演算法常數）。全套測試 347 綠（+ `requires_snapshot` 本機閘門 `test_phase5b_ac.py`）。以 subagent-driven TDD 執行 6 個 task，實質模組經 spec + code-quality 兩段式 review，抓修 3 項（ERC 單資產守護前置/CCD 非收斂靜默、apples-to-apples 測試 K=2 無鑑別力——**發現 K=2 時 ERC≡inverse-vol 的數學事實**、改 K≥3 並明文鎖住恆等式）。**AC 誠實結論**：ERC vs inverse-vol 消融——full（inverse-vol）Sharpe 0.602/Calmar 0.489/MaxDD −14.9% vs full_erc（ERC）0.587/0.413/−17.4%；配對 bootstrap（full−full_erc）Sharpe/Calmar CI 皆含 0、**點估計微偏 inverse-vol**——**ERC 未打敗 inverse-vol，v1 續用 inverse-vol（預設不變）、ERC 留 `full_erc` 研究/選項**（§5.3 合格結論，印證「先簡後繁是紀律」）。4 處規格偏離見上方 Phase 5b 備忘。**Phase 5 全部 AC 達成 ✅**：v1 生產路徑為 EWMA 相關 + inverse-vol 權重（兩簡單基線皆未被 DCC/ERC 打敗），DCC/ERC 保留為研究選項。
- 2026-07-27：Phase 5 以 `--no-ff` 合併回 main，並開 `feature/phase6-garch-own`（後續 Phase 6、Phase 7a 分支自此鏈上疊代）。
- 2026-07-30：**Phase 7a 計畫 1 引擎診斷落盤完成**（分支 `feature/phase7a-dashboard`）——為 dashboard 頁 3/4/9 補齊 Phase 4/5 引擎未落盤的診斷：`accounting.trade_deltas`（turnover 的 per-ticker 分解，結構化）、`CorrelationForecaster.last_fell_back`/`VolForecaster.all_standardized_residuals`、`Diagnostics` 加 `corr_matrix`/`corr_fell_back` 並 thread 過決策熱路徑（含 Phase 5a M-1 快取移位）、engine **trade blotter**（`run_strategy` 回 4-tuple、5 呼叫端更新）、runner 攤平 correlation/residuals、`write_artifacts` 落盤 `trades.parquet`（進 INV-6 content_hashes）+ `model_details/{correlation,residuals}.parquet`、blotter fill_price 誠實守護。以 subagent-driven TDD 執行 9 個 task + review 修正，實質模組經 spec + code-quality 兩段式 review + opus holistic review（判 ready to merge、2 Minor 已修）。**重跑 2 canonical run（dcc/ewma，全 8 策略）**：blotter 逐執行日 `Σ|Δw|==turnover`/`Σcost==cost` **零誤差**（~25,800 筆）；**dcc `corr_fell_back` 1.22% 獨立重現 Phase 5a 的 1.2%**，了結 5a I-1。全套件（含 7 AC 閘門）+ INV-3/5/6 綠、ruff 乾淨。
- 2026-07-30：**Phase 7a 計畫 2a presentation readers 地基完成**——`presentation/readers.py` 16 個純唯讀函數（run 載入 / **Decision Explorer 六層抽取＝AC① 自動化 golden** / model_details / 快照 / list_runs），缺檔優雅回 `None`；**AST 架構守護測試**把「presentation 永不 import 引擎」（§2.2）紅綠燈化。以 subagent-driven TDD 執行 8 個 task，實質模組經 spec + code-quality 兩段式 review + 一次整體 holistic review——**抓到並修掉守護的真實 bypass**（`from quantcore import backtest` 漏判）與 teeth 測試無鑑別力、`decision_layers` 多列靜默 fallback。23 presentation 測試綠，真實 canonical run 冒煙通過（六層 / 相關矩陣 / 面板皆正確）。**AC① 自動化達成**（人工手查待計畫 2b）。**邊界：計畫 2b 做 app + 9 頁 Streamlit UI + AC① 人工手查。**
- 2026-07-30：**Phase 7a 計畫 2b-1 dashboard 骨架 + 核心 3 頁完成**——`app.py`（st.navigation）+ `controls` 全域控制列 + 頁 1 總覽 / **頁 2 決策解剖（AC① UI，六層瀑布讀 `decision_layers`）** / 頁 5 組合與成本 + 頁 8 Run Lab stub。以驗證過的 streamlit 1.59 API（st.navigation/st.Page/AppTest）為準；AST 架構守護擴至 app/controls/pages。以 subagent-driven TDD 執行 8 個 task + holistic review（**實測啟動 Streamlit server HTTP 200 + live 重算 AC① 數字**，抓修守護 bypass 已見 2a、多 run 標籤過度承諾）。**AC① 人工手查達成**（`docs/phase7a-ac1-handcheck.md`：真實 `canonical_ewma`/full/2016-04-06 六層 11 項 vs `decisions.parquet` 逐格一致，含 band-blocked/log-only 路徑）。
- 2026-07-31：**Phase 7a 計畫 2b-2 dashboard 其餘 5 頁完成 → 唯讀 dashboard 9 頁齊備**——頁 3 GARCH（參數軌跡/persistence/fallback/QLIKE·MZ-R²/殘差 QQ+ACF）、頁 4 相關結構（熱圖時間滑桿/資產對序列/頁內第二 run 疊 DCC vs EWMA）、頁 6 消融（指標表/敏感度熱圖/配對 bootstrap CI）、頁 7 資料品質（MANIFEST/資料源/overrides/tickers）、頁 9 價格與交易（adj_close 折線+買賣標記+blotter）+ 新 readers（vol_eval/comparison/bootstrap/snapshot_dir）。以 subagent-driven TDD 執行 7 個 task；39→41 presentation 測試綠，9 頁對真實 canonical_dcc + ablation run 逐頁 AppTest 冒煙無例外。spec review 抓到 §11.2 頁 3 兩缺項（proxy 疊圖延、parity 對照頁籤卡引擎落盤）記 backlog。**使用者實測抓到「開啟即崩潰」bug**（側欄預設選到非回測 run `vol_eval` → 總覽 `load_nav` FileNotFoundError；冒煙皆指定 backtest run 而漏抓）——修 `is_backtest_run` 守護 + 側欄預設優先回測 run + 回歸測試。**7a 唯讀 dashboard 段完成，可 `uv run streamlit run quantcore/presentation/app.py` 啟動；尚待 7b Run Lab / 7c 報告。**
- 2026-07-31：**Phase 7 展示層重製啟動（計畫 1 Web 地基完成）**——使用者實測 Streamlit dashboard 四類問題並存（崩潰/醜/慢/難改），定案**整層換掉 Streamlit → FastAPI + Jinja2 + HTMX + Plotly**（深色 Bloomberg 風、價格與交易為旗艦頁、狀態走 query string、**不上 DB**、引擎/快照/`readers.py` 全不動）。brainstorm→spec→plan 見 `docs/superpowers/specs/2026-07-31-phase7-web-dashboard-rebuild-design.md`、`docs/superpowers/plans/2026-07-31-phase7-web-dashboard-plan1-foundation.md`。**本次只做唯讀頁、Run Lab(7b) 延後、頁 8 stub**。計畫 1（7 task，subagent-driven TDD → 後段因用量上限改 inline）：退役 Streamlit（`app.py`/`controls.py`/`pages/` 與 2 個 AppTest 測試移除）、新 `presentation/web/`（`controls` query 解析含回測優先牙齒、`cache` path+mtime 加 threading.Lock、`charts` Plotly 深色 template、`app` factory + `rendering.render_page`/`controls_for`、9 頁骨架 + 總覽真資料 KPI + 8 頁 stub、HTMX 局部換頁、vendored htmx/plotly）。§2.2 行程邊界由既有 AST 守護（`rglob` 全樹）自動涵蓋新 `web/`。**全套 pytest 44 presentation 綠、ruff 乾淨**。啟動改 `uv run python -m quantcore.presentation.web`（localhost:8000）。**計畫 2 做九頁唯讀（含價格與交易旗艦頁）。**
- 2026-07-31：**Phase 7 展示層重製完成（計畫 2a/2b/2c，唯讀 dashboard 8/9 頁真內容齊備）**——計畫 2a：`charts` 6 builder（NAV/回撤/曝險/權重堆疊/帶事件/換手成本）+ 頁 1 總覽（NAV 對數/回撤/曝險/指標表/子期間）、頁 5 組合與成本、頁 7 資料品質。計畫 2b：`charts` +5 builder（動量長條/熱圖/多線/殘差 QQ·ACF）+ 頁 2 決策解剖（**AC① UI 六層瀑布**）、頁 3 GARCH（參數軌跡/fallback/QLIKE·MZ-R²/殘差 QQ·ACF）、頁 4 相關結構（熱圖時間滑桿/資產對序列/第二 run 疊圖）、頁 6 消融（指標表/敏感度熱圖/bootstrap CI）。計畫 2c：`charts.price_with_trades` + 頁 9 **價格與交易旗艦**（走勢+進出場標記、標的持有列表、blotter 分頁/篩選、持倉堆疊、**點標記經 app.js 跳決策解剖**，decisions route 支援 `?ddate`）。頁內互動用 GET 表單（run/strat 帶入 hidden、cache 讓重載快）。inline 執行 TDD，**過程抓修 3 個真 bug**：correlation 策略選擇 IndexError（挑真有相關矩陣的策略）、**cache 鍵碰撞靜默供錯資料**（run_dir 同路徑被 load_correlation/load_comparison 共用 → 鍵加 loader 身份 + 回歸測試）、test fixture 浮點精度。**全套 66 presentation 綠、ruff 乾淨**；8 頁對真實 canonical_ewma/ablation run live 冒煙通過（決策六層/GARCH/相關熱圖/消融/旗艦 4 元件 + click→decision roundtrip 全 HTTP 200）。**頁 8 Run Lab 仍 stub（7b）；7c 研究報告未做。分支 `feature/phase7a-dashboard` 未併回 main。**
