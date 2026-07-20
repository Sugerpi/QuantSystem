# Phase 2 — 回測核心 設計文件

> 日期：2026-07-17
> 規格來源：`DEVELOPMENT_GUIDE v1.2.md` §1.2（事件時鐘）、§1.5–1.8、§2.1（模組地圖）、§3（INV-1/2/5/6）、§6（回測引擎）、§7（實驗框架）、§8（測試）、§9（Phase 2 AC）
> 狀態：已與使用者確認範圍，待實作

## 0. 範圍決策（已確認）

| 決策 | 選擇 | 理由 |
|------|------|------|
| 合格性規則 | 全策略統一用 `min_history_days`（252） | 消融比較時各策略的可投資宇宙時間軸一致；eligibility primitive 建在 Phase 2 由 INV-1 鎖，Phase 3 沿用 |
| warmup | 全 run 統一，由引擎取所有策略需求的最大值推導 | 七策略比較表的 NAV/Sharpe/MaxDD 直接可比，不需事後對齊 |
| `decisions.parquet` | Phase 2 即寫，模型欄位留 null | 符合 §6.2「引擎在決策當下就記錄」；Phase 3-4 填欄位而非補基礎建設 |
| `model_details/` | 不做 | Phase 2 無任何模型，必為空目錄 |
| 引擎迴圈結構 | 策略在外、天在內（`run_strategy` 為獨立單元） | 每策略回測可獨立理解與測試；golden case 直接餵單一策略 |
| `PointInTimeView` | 建構時實體切片並凍結 | 物件內物理上不存在未來資料；INV-1 可斷言結構而非斷言呼叫者自律 |
| 具體策略位置 | 新增 `backtest/strategies/` 子套件 | §2.1 只給了介面 `strategy.py`；最終七策略塞一檔會爆 |
| `bh_spy` 外部驗證 | 凍結外部數字進測試 + 推導文件 | 見 §6.3；**外部數字由使用者提供，不得自行編造** |
| block bootstrap | 不做 | §9 明講「先不含 bootstrap」 |
| golden master (`test_golden/`) | 不做 | Phase 2 AC 未要求；引擎仍會大改，此時凍結行為只會凍到待改的東西 |

## 1. 目標與驗收條件（§9）

Phase 2 完成須滿足：

1. INV-1/2/5/6 測試全綠（CI 可跑，用合成迷你快照）。
2. 三日手算 golden case 逐日吻合。
3. `bh_spy` 年化報酬與外部來源（portfoliovisualizer）對 SPY 同期吻合，差異可由成本與計息解釋。
   **註**：此條需真實快照，CI 無快照（`snapshots/` 為 gitignore），故為**本機閘門**，見 §6.3。

## 2. 事件時鐘與會計語意（本 Phase 最關鍵）

### 2.1 與 §6.1 的偏離（重要）

§1.2 規定：**新權重自 `close(t+1)` 生效，開始賺取 `(t+1 → t+2]` 的報酬**。

§6.1 伪代碼的步驟順序為「執行（`w ← w_target`）→ 當日損益（`NAV *= 1 + Σ w_i·r_i(t)`）→ 漂移 → 決策」。若 `r_i(t)` 依一般慣例為回看報酬（`close(t)/close(t-1) − 1`，與 §1.3 動量公式的 `TR_i(t−21)` 一致），此順序會讓 `w_target` 賺到它生效之前的報酬——正是 §1.2 要排除的偏誤。

存在一種自洽讀法：若 `r_i(t)` 為前向報酬（`close(t+1)/close(t) − 1`），§6.1 順序與 §1.2 一致。但該讀法與 §1.3 的回看記法衝突，且 step 3 註解自稱「當日損益」在前向報酬下實為明日損益。

**決議：以 §1.2 為準**（§1.2 標題自陳「全系統最重要的規格」，措辭精確；§6.1 為伪代碼，寫鬆了）。實作順序：

```
for t in trading_days[warmup:]:
    1. 當日損益：NAV *= 1 + Σ w_i(t)·r_i(t) + w_cash(t)·(DTB3(t)/252)
                 其中 w(t) 為 close(t-1) 建立的持倉，r_i(t) = close(t)/close(t-1) − 1
    2. 權重漂移：w_drift = w(t)(1+r(t)) / Σ_j w_j(t)(1+r_j(t))；現金按利息漂移
    3. 若 t 為執行日（前一決策日產生了 target）：
           turnover = Σ_i |w_target,i − w_drift,i|      # i 只跑風險資產，不含 CASH
           NAV -= NAV × turnover × per_side_bps
           w(t+1) = w_target
       否則：w(t+1) = w_drift
    4. 若 t 為決策日：target = strategy.decide(view(t))   # 於下一交易日執行
    5. 記錄 NAV、權重、決策
```

### 2.2 換手率不含現金腿

§1.8 的 `Σ_i |w_i^new − w_i^drifted|` 中 `i` **只跑風險資產**。理由：§1.5 的現金為**合成現金**（直接以利率入帳，不持有 BIL/SHV），本無交易成本；若計入 CASH 腿，賣出 10% SPY 換現金會算成 `0.10 + 0.10 = 0.20` 換手、收兩倍成本，「單邊 5 bps」將名不副實。

### 2.3 初始狀態與 warmup

- 初始 NAV = `backtest.initial_nav`（新增 config 欄位，預設 1.0），初始持倉 100% 現金。
- 首個決策日產生 target，隔一交易日執行，首次建倉照常付一次換手成本。
- warmup 由引擎推導 = 所有參與策略需求的最大值。Phase 2 為 `universe.min_history_days`（252），故 NAV 自第 253 個交易日起跑。

### 2.3.1 決策日的錨點（§1.7 未明定，此處定死）

§1.7 只寫「選擇日：每 21 個交易日」「曝險檢查日：每 5 個交易日」，未定義從哪一天起算。若不定死，warmup 或 `backtest.start` 一改，全部決策日就整體位移，回測結果無法解釋。

**決議**：兩者皆以 **warmup 結束後的第一個交易日為第 0 天**起算。即該日為首個選擇日（亦為首個曝險檢查日），其後每 `schedule.selection_interval` / `schedule.exposure_check_interval` 個交易日各自再次觸發。錨點由 `clock.py` 單一定義，引擎不自行推算。

Phase 2 的兩策略均不使用曝險檢查日（無曝險模型）：`clock` 仍照常標記該類日子，但 `bh_spy` / `ew_menu` 於其上回傳 `None`（不產生決策）。曝險檢查日的首次實戰在 Phase 4。

### 2.4 Phase 2 的現金路徑

`bh_spy`（100% SPY）與 `ew_menu`（等權滿倉）的 `w_cash` 恆為 0，**現金計息不會被真實策略走到**，僅由三日手算 golden case 的合成資料驗證。DTB3 在 Phase 2 仍被 `metrics` 使用（Sharpe 超額於 DTB3）。計息的首次實戰在 Phase 3（絕對動量將配額轉現金）。

## 3. 模組設計

依 §2.2 單向依賴 `config ← data ← models ← signals/portfolio ← backtest ← experiments`。

| 檔案 | 職責 | 不知道什麼 |
|------|------|-----------|
| `backtest/clock.py` | §1.2 時間語意物件。輸入交易日序列 + `schedule` config；回答：t 是否決策日（選擇日／曝險檢查日）、t 是否執行日、決策日對應的執行日。INV-2 的唯一定義處 | 價格、策略 |
| `backtest/ptview.py` | **只做時間閘門**。`PointInTimeView(snapshot, t)` 建構時實體切片 `≤ t` 並凍結 | 合格性、動量等業務規則 |
| `portfolio/selection.py` | `eligible_assets(view, min_history_days)`。依 §2.1，「point-in-time 合格性」歸此處。Phase 3 於同檔加排序與 top-K | 時鐘、NAV |
| `backtest/accounting.py` | 純函式：扣成本、當日損益（含計息）、漂移再正規化。INV-5 的測試對象 | 日期、I/O |
| `backtest/strategy.py` | §6.2 的 `Strategy` ABC + `Decision` + `Diagnostics` dataclass | 引擎迴圈 |
| `backtest/strategies/bh_spy.py`、`ew_menu.py` | 具體策略 | 會計、檔案 |
| `backtest/engine.py` | `run_strategy(...) -> (nav, weights, decisions)`，單策略完整回測 | `runs/` 的存在 |
| `backtest/metrics.py` | Sharpe/Sortino/MaxDD/Calmar/turnover，純函式吃 nav + rates。**不含 bootstrap** | 檔案 |
| `experiments/tracking.py` | 建 run 目錄、寫 manifest、決定性寫 parquet/JSON | 會計、策略 |
| `experiments/runner.py` | config → 載快照 → 逐策略呼叫 `run_strategy` → concat → 寫 artifacts。**CLI 入口**（Phase 7 Run Lab 的 subprocess 對象） | — |

**PROGRESS 補充**：PROGRESS.md 的 Phase 2 任務清單只列 `backtest/` 六檔，未列 `experiments/`。但 AC 的 INV-6 要比對 `runs/` artifacts，依 §2.1 該職責屬 `experiments/tracking.py` 與 `runner.py`，故 Phase 2 必然涵蓋。實作時一併更新 PROGRESS。

## 4. Strategy 介面與 Diagnostics

沿用 §6.2 定義。Phase 2 兩策略填得出的欄位：

| Diagnostics 欄位 | Phase 2 | 說明 |
|------------------|---------|------|
| `eligible` | ✅ | `min_history_days` 過濾後的選單 |
| `selected` | ✅ | `bh_spy` = `["SPY"]`；`ew_menu` = 全體 eligible |
| `momentum_scores` / `absmom` / `sigma_hat` / `w_risky` / `sigma_p` / `exposure_raw` / `exposure_applied` / `band_blocked` | null | Phase 3-4 填入 |

`Decision.target_weights` 含 `'CASH'` 鍵（Phase 2 恆為 0.0）。

### 4.1 兩策略語意

- **`bh_spy`**：`strategy_id = "bh_spy"`。首個決策日產生 `{SPY: 1.0, CASH: 0.0}`，其後不再產生決策（`decide` 回 `None`），權重隨市場漂移。全期僅一次交易。
- **`ew_menu`**：`strategy_id = "ew_menu"`。每個選擇日（`schedule.selection_interval` = 21）對全體 eligible 資產等權。HYG 於 2008-04 前後入列（inception 2007-04-11 + 252 交易日），屆時下一個選擇日起納入等權。

## 5. 產出格式（`runs/`）

### 5.1 目錄

```
runs/2026-07-17_1432_default/
├── config.yaml        # 完整展開（含所有預設值）
├── manifest.json
├── nav.parquet        # date, strategy_id, nav, turnover, cost
├── weights.parquet    # date, strategy_id, ticker, weight   （長格式，含 CASH 列）
├── decisions.parquet  # decision_date, execution_date, strategy_id, eligible, selected,
│                      #   target_weights, + Phase 3-4 模型欄位（null）
└── metrics.json       # 每策略一組
```

**與 §7.1 的偏離**：§7.1 範例目錄名為 `2026-08-15_1432_full_default`（讀作「策略_config」），但同一份 `nav.parquet` 又須容納「所有策略」——一個 run 多策略時，名稱含單一策略名無意義。改為 `YYYY-MM-DD_HHMM_<label>`，`label` 由 CLI `--label` 指定，預設取 config 檔名 stem。

`nav.parquet` 的 `turnover` / `cost` 兩欄為 §7.1 未列出的補充（§7.1 只列檔名不列欄位）：`metrics` 需要總換手與總成本才能算 §6.4 的「年化換手率」與「成本拖累」，而 §11.2 第 5 頁（組合與成本）要畫「每次再平衡換手率」與「累積成本拖累」——在決策當下記錄比事後從權重反推更誠實，亦符合 §6.2 原則。非執行日兩欄為 0。

不產出 `model_details/`（Phase 2 無模型）。§7.1 已規定 dashboard 缺該目錄時顯示「本次未儲存」而非崩潰。

### 5.2 manifest.json 與 INV-6 邊界

run 目錄名含時間戳、manifest 含 `created_at`，兩次跑必然不同，故「雙跑 byte 比對」不可能是整個目錄逐位元組相同。INV-6 原文為「(config, snapshot_hash, git_commit) 三元組決定**輸出**」，比對對象是資料產出。將 manifest 切為兩塊，使邊界寫在資料結構上而非藏在測試的 exclude 清單裡：

```json
{
  "identity": {
    "config_hash": "...",
    "snapshot_id": "...",
    "git_commit": "...",
    "quantcore_version": "..."
  },
  "content_hashes": {
    "nav.parquet": "...",
    "weights.parquet": "...",
    "decisions.parquet": "...",
    "metrics.json": "..."
  },
  "created_at": "2026-07-17T14:32:11Z"
}
```

`content_hashes` 為輸出的**內容指紋**（沿用 §5.3 的 `canonical_hash`，與 parquet 位元
編碼無關）。INV-6 測試斷言：兩次跑的 `identity` 與 `content_hashes` 相同、讀回的資料
`assert_frame_equal` 相同（抓列序、對 parquet 編碼穩健）；`created_at` 允許不同。

> **不比 parquet 位元組**：pyarrow 升級會改變位元編碼卻不改內容，位元比對會因環境
> 而非真迴歸變紅。故 INV-6 比 `content_hashes`（跨環境穩健）+ `assert_frame_equal`
> （抓 `canonicalize` 排序會遮蔽的列序不決定性）。此為最終 code review 後的修正。

### 5.3 決定性寫檔

沿用 Phase 1 的 `data/hashing.py`（`canonicalize` + 固定欄序/dtype）——該套已由 Phase 1 AC-4 驗證可達位元級可重現。`metrics.json` 以 `sort_keys=True` 寫出。

`git_commit`：工作區若有未提交改動記為 `<sha>-dirty`，否則 INV-6 的三元組會撒謊。

## 6. 測試計畫

### 6.1 CI 與快照的現實

`snapshots/` 為 gitignore（§2.1：「hash 進版控」而非資料本身），**CI 上沒有真實快照**。因此：

- INV-1/2/5/6 一律使用**合成迷你快照**（`tests/fixtures/`，沿用 `tests/test_data/test_snapshot.py` 的 fake provider 手法建數十日假資料）→ CI 可跑。
- 需真實快照的測試加 `requires_snapshot` marker，快照不存在即 skip。

### 6.2 四條不變量各自鎖什麼

| 檔案 | 鎖什麼 |
|------|--------|
| `test_no_lookahead.py`（INV-1） | (a) property：view 內任何 timestamp ≤ t。(b) **竄改未來資料，決策必須不變**——將 t 之後所有價格換成隨機值重跑，決策日 t 的 target 逐位元相同。(b) 才是有牙齒的一條：它測結構而非自律，若有人讓 view 洩漏未來，(a) 可能仍過，(b) 必當場紅燈 |
| `test_execution_lag.py`（INV-2） | (a) 時鐘算術：執行日嚴格晚於決策日至少一個交易日。(b) 行為：**將某次決策的 target 換成任意其他值，決策日與執行日當天的 NAV 報酬完全不變**，僅執行日之後改變——直接釘死 §1.2 的「新權重自 `close(t+1)` 生效、賺 `(t+1 → t+2]`」，亦即 §2.1 那個順序問題的著陸點 |
| `test_accounting.py`（INV-5） | 三日手算 golden case：兩檔資產 + 現金，數字取整（+10% / −5% 之類），期望值人手算出後寫成字面常數，docstring 附完整算式供紙筆核對。走過扣成本、計息、漂移再正規化全路徑（Phase 2 唯一實際驗證現金計息處）。另加 property：權重恆和為 1 |
| `test_reproducibility.py`（INV-6） | 見 §5.2 |

### 6.3 `bh_spy` 外部驗證（AC-3）

- 位置：`tests/test_backtest/test_bh_spy_external.py`（新增目錄，見 §10 偏離 #5），加 `requires_snapshot` marker。
- 外部數字（SPY 同期含息 CAGR、同起訖日）**由使用者查 portfoliovisualizer 提供**。實作時此為明確的「需要輸入」步驟——不得填入未經查證的數字，否則此條 AC 淪為自我驗證。
- 測試凍結：外部數字、查詢日期、期間、含息與否。docstring 須逐項寫明容差的來源（滑價、現金計息、資料源差異）。
- **容差於交付順序第 13 步決定，非事先指定**：先跑出 `bh_spy` 的實際年化報酬，與外部數字比對後，逐項估算三個差異來源各自的量級，容差取其合計並在 docstring 寫明每一項的推導。先射箭再畫靶（挑一個剛好會過的容差）與先畫靶再射箭（憑空指定 ±30 bps）都不可接受——前者無意義，後者若過寬會放掉真錯、過窄會逼人事後放寬。
- 另寫推導文件記錄比對過程與差異解釋。

## 7. Config schema 擴充

`BacktestConfig` 新增：

| 欄位 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `initial_nav` | `float > 0` | 1.0 | 初始 NAV。**註**：NAV 為尺度不變，此值不影響任何指標（Sharpe/MaxDD/Calmar/換手率皆尺度不變），僅影響 `nav.parquet` 的數字大小。仍入 config 以維持「參數只在 config」這條明線，避免開個案豁免的先例 |

`default.yaml` 同步加入。

## 8. 依賴方向與硬性規則檢核

| 規則 | 檢核 |
|------|------|
| 參數只在 `config/` | `initial_nav`、`min_history_days`、`selection_interval`、`per_side_bps` 皆由 config 注入；引擎無字面常數 |
| `presentation/` 不 import 引擎 | Phase 2 不動 `presentation/` |
| 禁用 pickle | 全部 parquet / JSON |
| 回測資料只來自 `snapshots/` | `runner` 只讀快照；引擎無網路呼叫 |
| 依賴方向單向 | `portfolio ← backtest ← experiments`；`backtest` 不 import `experiments`；`accounting` 不 import `clock` |
| 新增複雜度須附消融 | Phase 2 無新模型 |

## 9. 交付順序（供 writing-plans 展開）

1. Config：`BacktestConfig.initial_nav` + `default.yaml` + schema 測試。
2. `clock.py` + `test_execution_lag.py` 的時鐘算術部分。
3. `ptview.py` + `test_no_lookahead.py`。
4. `portfolio/selection.py`（`eligible_assets`）+ 測試。
5. `accounting.py` + `test_accounting.py`（三日手算 golden case）。
6. `strategy.py`（介面 + Diagnostics）。
7. `strategies/bh_spy.py`、`strategies/ew_menu.py` + 測試。
8. `engine.py` + `test_execution_lag.py` 的行為測試部分。
9. `metrics.py` + 測試。
10. `experiments/tracking.py`（run 目錄、manifest、決定性寫檔）。
11. `experiments/runner.py` + CLI。
12. `test_reproducibility.py`（INV-6）。
13. 真實快照跑一次；`bh_spy` 外部驗證（**需使用者提供外部數字**）。
14. 更新 PROGRESS.md（含 `experiments/` 補充與本文件的三處規格偏離）。

## 10. 與規格的偏離總表

| # | 偏離 | 規格處 | 理由 |
|---|------|--------|------|
| 1 | 迴圈順序改為「損益 → 漂移 → 執行 → 決策」 | §6.1 伪代碼 | §6.1 順序在回看報酬慣例下與 §1.2 的損益歸屬矛盾；以 §1.2 為準（見 §2.1） |
| 2 | run 目錄名改為 `YYYY-MM-DD_HHMM_<label>` | §7.1 範例 | 一個 run 多策略時，名稱含單一策略名無意義（見 §5.1） |
| 3 | 具體策略置於 `backtest/strategies/` 子套件 | §2.1 模組地圖 | §2.1 只給了介面 `strategy.py`；七策略塞一檔會爆 |
| 4 | AC-3（`bh_spy` 外部驗證）為本機閘門而非 CI | §9 Phase 2 AC | `snapshots/` gitignore，CI 無真實快照（見 §6.1） |
| 5 | 新增 `tests/test_backtest/`、`tests/test_portfolio/`、`tests/test_experiments/` 目錄 | §8 測試樹 | §8 的樹未列這三者，但既有 `test_data/` 已對應 `data/`；策略、合格性、run 落地皆非不變量／模型／資料，無處可放。沿用「測試目錄對應模組」的既有慣例 |
| 6 | 決策日錨定於 warmup 結束後第一個交易日 | §1.7 未明定 | §1.7 只給間隔未給起點，不定死則 warmup 一改全部決策日位移（見 §2.3.1） |
| 7 | `Strategy.decide` 加 `event` 參數；cfg 於 `__init__` 綁定 | §6.2 介面 | §6.2 的 `decide(self, view)` 只吃 view，但 §1.7 定義了兩種決策日（選擇日重跑完整權重、曝險檢查日只重算 E(t)），策略必須分辨自己被哪一種叫到，否則 `ew_menu` 會在每個曝險檢查日也做月再平衡、`full` 無法實作 §1.6 的分頻。`decide(view)` 無管道傳此資訊。改為 `decide(view, event)`，`event ∈ {SELECTION, EXPOSURE_CHECK}`；一天同時符合兩者時引擎發 `SELECTION`（完整權重計算為超集動作）。此法可維持 view 為純時間閘門、時鐘語意仍只在 `clock.py` |
| 8 | `nav.parquet` 增 `turnover` / `cost` 欄 | §7.1 未列欄位 | §6.4 的年化換手率與成本拖累、§11.2 第 5 頁需要（見 §5.1） |
