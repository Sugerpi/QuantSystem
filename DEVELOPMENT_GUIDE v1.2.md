# QuantCore 開發指引（v1.0）

> 商業軟體等級的重練藍圖。取代 RiskFirst QuantSystem。
> 本文件是系統的**唯一規格來源**：所有設計決策、不變量、驗收標準都在這裡。
> 開發時（無論人工或 AI 輔助）與本文件衝突的實作一律視為 bug。

---

## 0. 專案定位

### 0.1 一句話描述

在一個可配置的美股 ETF 選單內，以**橫斷面動量**決定持有什麼、以 **GARCH/DCC 波動率模型**決定持有多少的中低頻量化配置系統，全程 walk-forward、無 look-ahead、成本誠實。

### 0.2 明確的目標（Goals）

1. **回測結果可信**：任何一個數字都經得起「這是不是作弊算出來的」的質問。
2. **每個複雜度都要自證其值**：消融（ablation）內建於實驗框架。動量、GARCH、DCC、波動目標——每一層都必須打敗沒有它的版本，否則移除。
3. **可重現**：同一份 config + 同一份資料快照 + 同一個 commit → bit 級相同的結果。
4. **GARCH 手刻**：自行實作 GARCH(1,1) MLE 核心，以 `arch` 套件為 reference implementation，通過 parity test 後切換為正式路徑。這是學習目標，也是履歷素材。
5. **架構預留升級路徑**：資料層抽象化，未來換成付費 point-in-time 個股資料時，引擎零改動。

### 0.3 明確的非目標（Non-Goals）——同樣重要

- **不做**新聞/情緒層。舊系統的 news_ai、morning_scan、RAG、Discord 全部不搬。
- **不做** live 下單。v1 是研究系統，輸出是「今日目標權重」，不是委託單。
- **不做**日內策略、不做槓桿、不做放空。曝險 ∈ [0, 1]。
- **不追求**打敗機構。目標是「個人以免費資料能誠實達到的最好結果」。
- **不做**台股。單一市場（美股）、單一貨幣（USD）、單一交易日曆（NYSE）——這一刀消滅了舊系統的跨市場日曆污染與 FX 換算問題。

### 0.4 基準貨幣與稅務備註

- 系統內部全程 **USD**。TWD 報表換算屬展示層問題，不進引擎。
- 台灣投資人持有美股 ETF 的股息預扣稅為 30%（台美無租稅協定）。回測使用含息總報酬（Adj Close），**高估**了實際可得報酬約「股息率 × 30%」（對 SPY 約 0.4%/年）。此差異記錄於報表註腳，v1 不建模，但選單設計時避免過度傾斜高配息資產。

---

## 1. 策略規格（Strategy Specification）

這一節是策略的完整數學定義。實作必須逐條對應，不留模糊空間。

### 1.1 資產選單（Menu）

選單是**可配置的**（config 檔），不寫死在程式碼。v1 預設選單約 22 檔：

| 類別 | Tickers | 上市年 |
|------|---------|--------|
| 美股大盤 | SPY, QQQ, IWM | 1993 / 1999 / 2000 |
| 類股 (SPDR) | XLK, XLF, XLE, XLV, XLI, XLP, XLU, XLY, XLB | 1998 |
| 國際股 | EFA, EEM | 2001 / 2003 |
| 債券 | TLT, IEF, LQD, HYG | 2002 / 2002 / 2002 / 2007 |
| 商品 | GLD, DBC | 2004 / 2006 |
| 不動產 | VNQ | 2004 |
| 現金代理 | （不進選單，見 1.5） | — |

**Point-in-time 選單規則（消滅選單層面的倖存者偏差與新 ETF 資料不足問題）：**

- 每檔 ETF 有 `inception_date`（記錄於 metadata）。
- ETF 在 `inception_date + 252 個交易日` 之後才**進入**可選集合（動量與 GARCH 都需要一年歷史）。
- 回測起點建議 2005-01（此時 SPDR 類股、債券 ETF、GLD 已備齊，選單隨時間長大是正常且誠實的行為）。
- 選單異動（未來加減 ETF）記錄於 config 版本，舊實驗不受影響。

### 1.2 事件時間軸（Event Clock）——全系統最重要的規格

舊系統最大的風險是 `iloc[:t+2]` 這種靠註解保護的切片。新系統的時間語意如下，**由架構強制、由測試鎖死**：

```
定義：t 為 NYSE 交易日序號。

資料可得性：  day t 的 bar（含收盤價）在 close(t) 之後才存在。
決策時點：    close(t) 之後執行決策函數，只能看到 timestamp ≤ t 的資料。
執行時點：    close(t+1)，以 t+1 收盤價成交（模擬 MOC 單）。
損益歸屬：    新權重 h 自 close(t+1) 生效，開始賺取 (t+1 → t+2] 的報酬。
交易成本：    於 t+1 當日自 NAV 扣除（turnover × cost）。
```

換句話說：**訊號與執行之間強制存在至少一個交易日的延遲**。這比舊系統「當日收盤決策、當日收盤成交」保守，但它是唯一不需要辯護的選擇——你永遠不必回答「你怎麼可能在收盤瞬間算完 GARCH 又下完單」。

### 1.3 選標的：橫斷面動量（回答「持有什麼」）

於每個**選擇日**（見 1.7）計算：

```
M_i(t) = TR_i(t − 21) / TR_i(t − 252) − 1        # 12-1 動量
```

- `TR_i` 為**含息總報酬指數**（由 Adj Close 建構，資料層負責驗證，見 §4）。
- 跳過最近一個月（−21）是為了避開短期反轉效應，這是文獻標準做法（Jegadeesh & Titman 1993 以降）。
- 對所有「當日在選單內且合格」的資產排序，取前 **K = 5** 檔（config 可調）。
- 平手時以 ticker 字母序決定（確保確定性——同一份資料永遠同一個結果）。

### 1.4 絕對動量過濾（取代舊 regime filter）

入選的每一檔資產，額外檢查其**時間序列動量**：

```
AbsMom_i(t) = TR_i 過去 252 日總報酬 − 同期 T-bill 累積報酬
若 AbsMom_i(t) ≤ 0 → 該檔的部位配額轉入現金
```

這是舊系統「三指標 regime filter（殖利率曲線 + VIX<20 + TWII 動能）」的替代品。它功能相同（系統性風險升高時減碼），但：純價格驅動、無 FRED 依賴、無寫死閾值、無 2↔3 分邊界抖動問題、且有獨立文獻支撐（Moskowitz, Ooi & Pedersen 2012 時間序列動量）。舊 filter 最難辯護的部分就此消失。

### 1.5 現金的定義

- 現金部位賺取 **3 個月 T-bill 日利率**（FRED `DTB3`，除以 252，ffill 假日）。
- 舊系統 risk-off 時 50% 現金賺 0% 的錯誤在此修正——在 4-5% 利率年代這不是小數字。
- v1 用「合成現金」（直接以利率入帳）而非持有 BIL/SHV，避免多一檔資產的成本與追蹤誤差建模。

### 1.6 定倉位：GARCH/DCC 風險預算 + 組合波動目標（回答「持有多少」）

**Step 1 — 個別資產波動率預測。** 對每檔入選資產，以 GARCH 模型（§5）產生**與再平衡週期對齊的多步波動預測**：

```
σ̂_i(t) = sqrt( (1/H) × Σ_{h=1..H} 預測變異數(t+h) ) ，H = 21
```

**Step 2 — 入選資產間的相對權重（inverse-vol，v1 預設）：**

```
w_i^risky(t) = (1/σ̂_i) / Σ_j (1/σ̂_j)     ，Σ w^risky = 1
```

ERC（等風險貢獻，需 DCC 共變異數與優化器）作為 config 選項在 Phase 5 加入，**必須在消融中打敗 inverse-vol 才轉為預設**。先簡後繁是紀律，不是偷懶：inverse-vol 沒有優化器收斂失敗模式、沒有 PSD 投影需求，而文獻顯示兩者績效差距通常很小。

**Step 3 — 組合波動目標決定總曝險：**

```
σ̂_p(t) = sqrt( w^risky' Σ̂(t) w^risky )        # Σ̂ 由 GARCH 波動 + DCC 相關重建
E(t)   = clip( σ*/σ̂_p(t), E_min, 1.0 )         # σ* = 10% 年化（config），E_min = 0.1
最終權重： w_i(t) = E(t) × w_i^risky(t)，現金 = 1 − E(t) + 絕對動量轉入的配額
```

這是**連續**的曝險控制，取代舊系統 50/75/95 三檔跳動 + vol alert 縮放的多層疊乘。整個系統只有一個曝險出口，語意在一個地方定義。

**曝險更新帶（防止換手率失控）：** 曝險 E 每週檢查一次，但只有 `|E_new − E_current| > 0.10` 才實際調整。這條帶是換手率與反應速度的取捨，寬度進 config，消融要測。

### 1.7 再平衡時程

| 事件 | 頻率 | 內容 |
|------|------|------|
| 選擇日 | 每 21 個交易日 | 重跑動量排序 + 絕對動量過濾 + 完整權重計算 |
| 曝險檢查日 | 每 5 個交易日 | 只重算 E(t)，帶寬 0.10 內不動作 |
| 其他日子 | 每日 | 權重隨市場漂移（見 §6 會計規則），不交易 |

舊系統的「5% 漂移觸發」與「vol spike 2x 觸發」**v1 不做**——它們各自引入參數且與波動目標功能重疊。列為 v2 候選，屆時以消融證明價值。

### 1.8 交易成本模型

- 佣金：$0（現代美國券商現實）。
- 滑價 + 買賣價差：**單邊 5 bps**（對 SPY/TLT 等一線 ETF 偏保守，刻意如此），config 可調。
- 每次交易成本 = `Σ_i |w_i^new − w_i^drifted| × cost_bps`，於執行日自 NAV 扣除。
- 報表必附**年化換手率**與**成本拖累（bps/年）**，並提供 cost_bps ∈ {0, 5, 10, 20} 的敏感度表——策略若在 20 bps 下死亡，要誠實地知道。

### 1.9 策略成立的前提假設（寫下來，避免自欺）

1. 動量溢酬在 ETF 層級、月頻、未來十年仍然存在（歷史支持，無保證）。
2. 波動叢聚使 GARCH 預測有樣本外能力（這是統計性質，前提中最穩的一條）。
3. 22 檔選單提供足夠橫斷面寬度讓排序訊號有意義（這是最弱的一條，Grinold 法則：IR ≈ IC × √breadth，寬度小是個人系統的天然限制）。

---

## 2. 系統架構

### 2.1 模組地圖

```
quantcore/
├── config/                      # 全系統唯一的參數來源
│   ├── schema.py                #   pydantic 模型（型別化 config）
│   └── default.yaml             #   預設參數（選單、K、σ*、成本、頻率…）
│
├── data/                        # 資料層（§4）
│   ├── provider.py              #   DataProvider 抽象介面
│   ├── providers/yfinance_adapter.py
│   ├── providers/fred_adapter.py
│   ├── snapshot.py              #   不可變快照的建立/載入/hash 驗證
│   ├── calendar.py              #   NYSE 交易日曆（exchange_calendars 套件）
│   └── validation.py            #   資料品質檢查（§4.3）
│
├── models/                      # 統計模型層（§5）
│   ├── volatility/
│   │   ├── base.py              #   VolatilityModel 介面：fit(returns) → forecast(H)
│   │   ├── garch_arch.py        #   arch 套件包裝（Phase 4 的正式路徑）
│   │   ├── garch_own.py         #   手刻 GARCH(1,1)-t（Phase 6，parity 後轉正）
│   │   └── ewma.py              #   RiskMetrics EWMA（消融基線，λ=0.94）
│   ├── correlation/
│   │   ├── base.py              #   CorrelationModel 介面
│   │   ├── dcc.py               #   DCC(1,1)，PSD 保證封裝在內部
│   │   └── ewma_corr.py         #   EWMA 相關（消融基線）
│   └── covariance.py            #   Σ = D·R·D 重建 + PSD 投影，唯一出口
│
├── signals/
│   └── momentum.py              #   橫斷面 12-1 + 絕對動量，純函數
│
├── portfolio/
│   ├── selection.py             #   排序、取 K、平手規則、point-in-time 合格性
│   ├── weighting.py             #   inverse-vol / ERC
│   └── exposure.py              #   波動目標 + 更新帶，全系統唯一曝險出口
│
├── backtest/                    # 回測核心（§6）
│   ├── clock.py                 #   事件時鐘：交易日、決策日、執行日
│   ├── ptview.py                #   PointInTimeView：結構性防 look-ahead
│   ├── engine.py                #   主迴圈（model-agnostic）
│   ├── accounting.py            #   NAV、權重漂移、現金計息、成本入帳
│   ├── strategy.py              #   Strategy 介面（含 strategy_id 欄位）
│   └── metrics.py               #   Sharpe/Sortino/MaxDD/Calmar/turnover + block bootstrap
│
├── experiments/                 # 實驗框架（§7）
│   ├── runner.py                #   單次實驗：config → 完整 pipeline → artifacts
│   ├── ablation.py              #   預定義消融矩陣
│   └── tracking.py              #   run 目錄、manifest、config/hash/commit 綁定
│
├── presentation/                # Web dashboard（§11）
│   ├── app.py                   #   Streamlit 入口
│   ├── pages/                   #   §11.2 的八個頁面，一頁一檔
│   ├── jobs.py                  #   Run Lab：subprocess 啟動引擎 CLI + status.json 輪詢
│   └── readers.py               #   runs/、snapshots/ artifacts 的唯讀載入
│
├── tests/                       # §8
├── snapshots/                   # 資料快照（gitignore，hash 進版控）
└── runs/                        # 實驗輸出（gitignore）
```

### 2.2 依賴方向（單向，違反即架構錯誤）

```
config ← data ← models ← signals/portfolio ← backtest ← experiments ← presentation
```

- `models` 不 import `backtest`；`backtest` 不 import `presentation`。
- `presentation` **永不 import 引擎模組**。它讀取 runs/ 與 snapshots/ 的檔案（parquet + JSON）；Run Lab（§11.3）要啟動回測時，只能寫出通過 schema 驗證的 config 檔並以 **subprocess 呼叫引擎 CLI**——行程邊界取代 import 邊界，引擎與 UI 的合約自始至終是檔案。舊系統 dashboard 依賴 `store_details=True` pickle 的隱性耦合就此斷根。
- 引擎與展示層之間的合約是**檔案格式**（§7.2），不是 Python 物件。pickle 全面淘汰。

### 2.3 舊系統教訓 → 新架構對策對照表

| 舊系統問題 | 新系統對策 |
|-----------|-----------|
| 不變量靠註解（「別改這行」） | 不變量封裝在型別/介面內 + property test 鎖死（§3） |
| `iloc[:t+2]` off-by-one 切片 | PointInTimeView：策略拿不到未來資料的 handle |
| 策略以名稱字串 "DCC-GARCH" 過濾 | `Strategy.strategy_id` 欄位，名稱只是顯示用 |
| pickle cache version 2 靠約定 | parquet + JSON manifest，schema 由 pydantic 驗證 |
| 參數散落各檔案（README 附行號速查表） | 單一 typed config，任何魔術數字出現在 config 以外即 code review 打回 |
| 每次重抓 yfinance，結果不可重現 | 不可變快照 + hash，回測永不直連網路 |
| DCC 對稱化在 317 行、忘了就爆 | CovarianceModel 輸出保證對稱 + PSD，呼叫端無法拿到非法矩陣 |
| 交集日曆污染單變量估計（LOO 換 spec 事件） | 單一市場單一日曆，且每檔資產保留原生序列 |
| 現金賺 0% | 現金計 DTB3 日息 |
| regime/vol-alert/RP 三層曝險疊乘無定義 | exposure.py 唯一曝險出口 |

---

## 3. 核心不變量（Invariants）與強制機制

每條不變量都有三件事：陳述、**結構性強制**（讓違反寫不出來）、**測試鎖定**（萬一寫出來了會被抓）。

### INV-1：無 Look-Ahead

- **陳述**：在決策日 t 做出的任何決定，只依賴 timestamp ≤ t 的資料。
- **強制**：策略的 `decide()` 只收到 `PointInTimeView` 物件，該物件內部持有完整資料但所有存取方法以 t 截斷；不暴露底層 DataFrame。存取 t 之後的索引 → raise。
- **測試**：`test_no_lookahead_property` —— 跑回測至日期 T 兩次：一次用完整資料，一次把 T 之後所有價格換成隨機亂數。斷言兩次在 T 之前的**每一個決策與每一筆 NAV** bit 級相同。這一個測試永久取代舊系統 CLAUDE.md 裡整段「別碰這幾行」。

### INV-2：訊號-執行延遲 ≥ 1 個交易日

- **強制**：engine 的排程器負責「t 日決策 → t+1 日執行」的搬運，策略碰不到執行時點。
- **測試**：golden 小資料集上手算三天的 NAV，逐日比對。另設「偏誤偵測測試」：故意允許同日執行跑一次，斷言 Sharpe 顯著上升（證明延遲機制真的在擋東西，而不是死碼）。

### INV-3：共變異數矩陣永遠合法

- **陳述**：任何離開 `covariance.py` 的矩陣必為對稱、PSD、對角線 = 個別變異數。
- **強制**：對稱化與 PSD 投影（clip 特徵值至 ≥ ε）是輸出前的無條件步驟，不是可選項。
- **測試**：隨機殘差序列 property test：對稱性、最小特徵值 ≥ 0、`R` 對角線 = 1。

### INV-4：GARCH 數值慣例

- **陳述**：報酬 ×100 後估計、預測 /100 還原；Student-t 分配；GARCH persistence α+β < 1（EGARCH 為 |β| < 1）。
- **強制**：縮放封裝在 `VolatilityModel` 基底類別的 template method 內，子類別只實作已縮放空間的 `_fit`/`_forecast`，不可能忘記還原。
- **測試**：round-trip 測試（合成常數波動序列 → 預測 ≈ 已知真值）；persistence 邊界測試。

### INV-5：會計恆等式

- **陳述**：每一天，`NAV(t) = NAV(t−1) × (1 + Σ w_i·r_i + w_cash·r_cash − TC(t))`，且權重（含現金）恆和為 1。
- **測試**：每次回測結束自動跑會計自檢（assert 內建於 engine，非可選），加上手算 golden case。

### INV-6：可重現性

- **陳述**：(config, snapshot_hash, git_commit) 三元組完全決定輸出。
- **強制**：所有隨機性（bootstrap、優化器初始值）走單一 seeded RNG，seed 進 config；引擎在偵測到快照 hash 不符時拒絕執行。
- **測試**：同一 config 連跑兩次，輸出 artifacts 逐 byte 相同。

---

## 4. 資料層規格

### 4.1 DataProvider 介面（付費資料升級路徑的保險）

```python
class DataProvider(Protocol):
    def fetch_prices(self, tickers, start, end) -> pd.DataFrame:
        """回傳 tidy 格式：columns = [date, ticker, close, adj_close, volume]"""
    def fetch_metadata(self, tickers) -> dict:
        """inception_date、名稱、資產類別"""
    def fetch_series(self, series_id, start, end) -> pd.Series:
        """總經/利率序列（FRED 用）"""
```

v1 實作 `YFinanceAdapter`（primary）、`TiingoAdapter`（validation，免費 API key，adjClose 正確含息）、`StooqAdapter`（第三源仲裁，免金鑰，僅拆分調整）與 `FredAdapter`。未來的 `EODHDAdapter` 或個股 point-in-time 供應商只需實作同一介面。**引擎的任何模組不得 import yfinance**——只認識 Provider 介面與快照格式。

### 4.2 不可變快照（Snapshot）

回測**永不直連網路**。工作流程：

```
python -m quantcore.data.snapshot create --config default.yaml
  → snapshots/2026-07-08_a3f9c1/
      ├── prices.parquet        # 全選單價格
      ├── rates.parquet         # DTB3
      ├── metadata.json         # inception dates 等
      └── MANIFEST.json         # 建立時間、provider、config hash、內容 SHA-256
```

- 快照建立後**唯讀**。yfinance 因除息回溯改價的問題被凍結在快照時點——你三個月後重跑，結果不變；想用新資料就建新快照，兩份快照的差異可被 diff 追查。
- `MANIFEST.json` 的 hash 進 git；parquet 本體 gitignore。
- 每檔資產保留**原生完整序列**（NYSE 單一日曆下自然對齊；個別 ETF 上市前為 NaN，由 point-in-time 合格性規則處理，**絕不做跨資產交集裁切**）。

### 4.3 資料驗證（快照建立時強制執行，任一失敗即拒絕產出快照）

1. **總報酬正確性**：對 SPY 抽查數個除息日，驗證 `adj_close` 報酬 ≈ `close` 報酬 + 股息/前收盤（容差內）。動量排序建立在含息總報酬上，這條錯了全系統的排序都是錯的。
2. **極端值**：單日報酬 |r| > 20% 的 ETF 列出人工確認清單（拆分處理錯誤的典型症狀）。
3. **缺值**：上市後的序列中間出現 NaN → 報告；連續缺值 > 5 日 → 拒絕。
4. **日曆一致**：所有日期 ∈ NYSE 交易日曆。
5. **單調性**：日期嚴格遞增、無重複。

### 4.4 FRED 的角色（大幅縮減）

舊系統 FRED 供養 regime filter（殖利率曲線、VIX）。新系統 FRED 只剩一個用途：**DTB3**（現金利率與 Sharpe 的無風險利率）。依賴面縮到最小。

### 4.5 多資料源交叉驗證（Cross-Source Validation）

yfinance 的遠期歷史資料有已知的系統性品質問題（拆分未調整、股息遺漏、整段損壞），且此類錯誤**不報錯、不崩潰，只安靜地污染動量排序**。對策不是尋找更可信的單一來源，而是讓錯誤可偵測：

**Provider 角色分工：**

| 角色 | 來源 | 說明 |
|------|------|------|
| Primary | yfinance | 快照的正式資料來源 |
| Validation | Tiingo | 免費 API key，adjClose 含息，可比對總報酬 |
| Arbiter | Stooq | 免金鑰；僅拆分調整不含息，只比對價格報酬 |

**驗證流程（併入快照建立，任一資產不通過即快照建立失敗）：**

1. 每檔資產同時自 primary 與 ≥1 個 validation source 抓取，對齊日期。
2. **比對日報酬，不比價格水準**——不同來源的調整基準不同，水準天生不可比；正確調整後的日報酬必須一致。
3. `|r_primary − r_validation| > 50 bps` 的日子進差異報告（discrepancy report）。
4. 孤立差異（多為收盤快照時點差）→ 記錄放行；**同一資產 30 個交易日窗內 ≥ 3 筆** → 快照建立失敗，強制人工裁決。成群的差異幾乎必然是某一源的拆分/配息調整錯誤。
5. 三源在場時少數服從多數；人工裁決結果寫入 `metadata.json` 的 overrides 區塊，永久可追溯。
6. `MANIFEST.json` 記錄所有參與來源與差異報告的 hash。

Tiingo 免費額度有限，但快照建立是低頻操作（月頻），額度充裕。此機制的成本是快照建立多花幾分鐘；換到的是「動量排序建立在被兩個獨立來源確認過的總報酬上」。

---

## 5. 模型層規格

### 5.1 VolatilityModel 介面

```python
class VolatilityModel(ABC):
    def fit(self, returns: pd.Series) -> FitResult: ...
    def forecast(self, horizon: int) -> np.ndarray:  # 每步變異數，已還原縮放
    @property
    def standardized_residuals(self) -> pd.Series: ...  # 供 DCC 使用
```

縮放（×100 / ÷100）在基底類別完成（INV-4）。

### 5.2 GARCH 雙軌計畫

| 階段 | 正式路徑 | 說明 |
|------|---------|------|
| Phase 4 | `garch_arch.py`（arch 套件，GARCH(1,1)-t） | 系統先能動、能出結果 |
| Phase 6 | `garch_own.py` 開發 | 手刻：log-likelihood、變異數遞迴、t 分配、L-BFGS-B、多步預測 |
| Parity 通過後 | `garch_own.py` 轉正，arch 降為測試中的 reference | 學習目標達成且有正確性保障 |

**Parity test 標準**：在 ≥ 5 檔真實 ETF 報酬序列上，參數 (ω, α, β, ν) 相對誤差 < 1%，21 步波動預測相對誤差 < 0.5%。

**規格選擇的簡化**：舊系統每次 refit 以 AIC 在四個規格間重選，造成規格不穩定（你的 LOO 表已示範）。新系統 v1 **固定 GARCH(1,1)-t**。GJR（槓桿效應）列為 config 選項，消融證明有貢獻才啟用。「一個穩定的模型」勝過「四個輪流上場的模型」。

**Refit 節奏**：每 21 個交易日 refit，其間沿用參數、只更新條件變異數遞迴（濾波便宜、估計昂貴，兩者分離）。warmup = 252 日。

### 5.3 CorrelationModel 與消融基線

- `dcc.py`：DCC(1,1)，兩步 QMLE，參數每 63 日 walk-forward 重估（舊系統寫死 a=0.01, b=0.96，新系統把「固定 vs 重估」做成 config 開關，消融比較）。對稱化、Q̄ 的 shrinkage、R 正規化全在模組內部。
- `ewma_corr.py`：RiskMetrics λ=0.94。**DCC 必須在消融中打敗它**（風險預測品質 + 最終組合績效兩個維度），否則 v1 出貨用 EWMA、DCC 留作研究章節。這是「複雜度自證其值」原則最重要的一次應用——DCC 是舊系統的招牌，正因如此更要敢於檢驗它。

### 5.4 風險預測品質的獨立評估（不只看最終 Sharpe）

模型好壞不能只用組合績效倒推（雜訊太大）。`metrics.py` 需支援：

- **波動預測**：QLIKE 損失（比 MSE 穩健）、Mincer-Zarnowitz 回歸的 R²，以 5 分鐘… 不可得，用日報酬平方 / 21 日已實現變異數作 proxy。
- **波動目標達成度**：組合已實現年化波動 vs σ* = 10% 的追蹤誤差——這是 vol targeting 系統最直接的成績單。

---

## 6. 回測引擎規格

### 6.1 主迴圈（伪代碼）

```
for t in trading_days[warmup:]:
    # 1. 開盤前狀態：昨日收盤後的持倉 w(t-1)
    # 2. 若 t 是「執行日」（前一個決策日 t-1 產生了目標權重）：
    #       turnover = Σ|w_target - w_drifted|
    #       NAV 扣 turnover × cost_bps
    #       w ← w_target
    # 3. 當日損益：NAV *= 1 + Σ w_i·r_i(t) + w_cash·(DTB3(t)/252)
    # 4. 權重漂移：w_i ← w_i(1+r_i(t)) / Σ_j w_j(1+r_j(t)) （現金按利息漂移）
    # 5. 若 t 是「決策日」（選擇日或曝險檢查日）：
    #       view = PointInTimeView(data, t)
    #       target = strategy.decide(view)     # 明日執行
    # 6. 記錄：NAV、權重、曝險、觸發事件 → 逐日 log
```

### 6.2 Strategy 介面

```python
@dataclass
class Decision:
    target_weights: dict[str, float]   # 含 'CASH'
    diagnostics: Diagnostics           # 每一層的完整中間結果，供 Decision Explorer（§11.2）

@dataclass
class Diagnostics:                     # 全部落盤進 decisions.parquet
    eligible: list[str]                # point-in-time 合格選單
    momentum_scores: dict[str, float]  # 全體合格資產的 12-1 分數（不只前 K）
    selected: list[str]                # 排序後的前 K
    absmom: dict[str, bool]            # 入選資產的絕對動量 pass/fail
    sigma_hat: dict[str, float]        # 21 步年化波動預測
    w_risky: dict[str, float]          # inverse-vol 相對權重
    sigma_p: float                     # 組合預測波動
    exposure_raw: float                # clip 與帶寬判定前的 σ*/σ̂_p
    exposure_applied: float            # 實際採用的 E(t)
    band_blocked: bool                 # 本次曝險調整是否被更新帶擋下

class Strategy(ABC):
    strategy_id: str                   # 穩定識別碼，取代舊系統的名稱字串過濾
    def decide(self, view: PointInTimeView) -> Decision | None: ...
```

**原則：dashboard 需要看什麼，引擎在決策當下就記錄什麼。** diagnostics 不是可選的 debug 資訊，是 Decision Explorer 的正式資料合約——事後補記錄等於重跑回測。

### 6.3 v1 策略清單（benchmark 先行）

| strategy_id | 內容 | 存在理由 |
|-------------|------|---------|
| `bh_spy` | Buy & Hold SPY | 最誠實的基準：不折騰能拿到什麼 |
| `ew_menu` | 選單等權重，月再平衡 | 分散但無訊號 |
| `sixty_forty` | 60% SPY / 40% IEF | 傳統配置基準 |
| `mom_only` | 動量選 K + 等權 + 絕對動量 | 消融：只有選擇層 |
| `voltarget_only` | 持有 SPY + GARCH 波動目標 | 消融：只有倉位層 |
| `mom_ivol` | 動量 + inverse-vol（無波動目標） | 消融：無總曝險控制 |
| `full` | 完整策略（§1） | 主策略 |

**驗收邏輯**：`full` 必須在風險調整後（Sharpe、MaxDD、Calmar）優於它的每一個殘缺版本，且優勢在 block bootstrap CI 下站得住，否則移除無貢獻的層。這張表就是你研究報告的骨架。

### 6.4 績效統計

- Sharpe（超額於 DTB3）、Sortino、MaxDD、Calmar、年化換手率、平均曝險、成本拖累。
- **Block bootstrap CI**（stationary bootstrap，平均 block 長度 21 日，1000 次）取代舊系統的 iid bootstrap——日報酬有自相關，iid 重抽樣的 CI 系統性偏窄。
- 子期間分析：至少切 2005-2009 / 2010-2019 / 2020- 三段，動量策略的績效高度 regime 依賴，單一全期數字會說謊。

### 6.5 多重檢定校正與顯著性檢定

§6.4 的 block bootstrap CI 只回答「單一比較下優勢站不站得住」。但研究流程會**試很多次**（消融格、七策略、參數掃描），單次 CI 未校正搜尋次數，會系統性高估顯著性。以下三個檢定補這個洞，純函式在 `backtest/significance.py`，編排在 `experiments/significance_report.py`（讀消融 run 產 `significance.json`）。所有隨機性走 `cfg.seed`（INV-6）。

- **Deflated Sharpe Ratio（DSR）**：以「N 次試驗下的期望最大 Sharpe」為 benchmark 的 PSR（Bailey & López de Prado 2014）。**N = 消融格數**（自動計數），benchmark 隨試驗次數與試驗間 Sharpe 橫斷面離散度上調。判讀：DSR > 0.95 才算 Sharpe 在校正搜尋後仍顯著 > 0。**限制**：N 只涵蓋單次消融的格數，未涵蓋跨實驗的累積搜尋；格間 Sharpe 離散度低時校正力弱。
- **PBO / CSCV**（Bailey, Borwein, López de Prado & Zhu 2017）：以消融格為候選集、鎖定 `full`，用組合對稱交叉驗證量「挑樣本內最佳格在樣本外落到中位數以下的機率」。判讀：PBO < 0.5 才算沒過擬合，越低越好；PBO ≈ 0.5 表示候選格的選擇無可泛化優勢（含「各格統計上無法區分」的情形）。
- **蒙地卡羅區塊置換檢定**：`full` vs 各對照策略的 Sharpe/Calmar 差異，做區塊符號置換（塊長 = bootstrap 平均塊長，尊重自相關）建 null 分布，回雙尾 p-value。與 block bootstrap CI 用不同假設，兩者一致（CI 排除 0 且 p < 0.05）才踏實。`observed` 為非有限（如零變異 Sharpe、無回撤 Calmar）時回 NaN p 值，不製造假顯著。

**驗收紀律**：§6.3 的「`full` 須優於每個殘缺版」判準，除 block bootstrap CI 外，應同時看置換 p-value（Sharpe 與 Calmar 分開）與 PBO；並明確區分優勢落在哪個指標（Sharpe vs 風險調整後的 MaxDD/Calmar）。正式結論的置換對照應鎖定消融階梯（mom_only → mom_ivol → voltarget_only → full），不混入非殘缺版的基準策略。

---

## 7. 實驗框架與可重現性

### 7.1 一次實驗 = 一個目錄

```
runs/2026-08-15_1432_full_default/
├── config.yaml            # 完整 config（含所有預設值展開）
├── manifest.json          # snapshot_hash、git_commit、時間戳、quantcore 版本
├── nav.parquet            # 逐日 NAV（所有策略）
├── weights.parquet        # 逐日權重
├── decisions.parquet      # 每次決策的完整 diagnostics
├── metrics.json           # 彙總統計 + bootstrap CI
└── model_details/         # GARCH 參數軌跡、相關矩陣（供 dashboard 深掘）
```

- Dashboard 只讀這些檔案。缺 `model_details/` 時對應頁面顯示「本次未儲存」而非崩潰（舊系統 `store_details` 教訓）。
- `manifest.json` 讓任何一張圖都能回答「這是哪份 code + 哪份資料 + 哪組參數跑出來的」。

### 7.2 Config 範例（節錄）

```yaml
snapshot: snapshots/2026-07-08_a3f9c1
seed: 42
universe:
  menu: [SPY, QQQ, IWM, XLK, XLF, XLE, XLV, XLI, XLP, XLU, XLY, XLB,
         EFA, EEM, TLT, IEF, LQD, HYG, GLD, DBC, VNQ]
  min_history_days: 252
signal:
  momentum_lookback: 252
  momentum_skip: 21
  top_k: 5
risk:
  vol_model: garch_arch          # garch_arch | garch_own | ewma
  corr_model: dcc                # dcc | ewma
  vol_target_annual: 0.10
  exposure_band: 0.10
  exposure_min: 0.10
schedule:
  selection_interval: 21
  exposure_check_interval: 5
costs:
  per_side_bps: 5
backtest:
  start: 2005-01-03
```

### 7.3 消融矩陣（`experiments/ablation.py` 預定義）

一個指令跑完 §6.3 全部七個策略 + 以下參數敏感度：

- `top_k ∈ {3, 5, 8}`、`vol_target ∈ {8%, 10%, 12%}`、`momentum_lookback ∈ {126, 252}`、`cost_bps ∈ {0, 5, 10, 20}`
- 輸出單一比較表（parquet + 終端摘要）+ 每格每策略日報酬（`cell_returns.parquet`，供 §6.5 的 PBO/DSR/置換消費）。**紀律**：敏感度表的用途是確認結論對參數擾動穩健，不是挑最好的一格回填 config——後者是過擬合的標準姿勢，報告中必須揭露看過哪些格子。
- 顯著性檢定（§6.5）由 `experiments/significance_report.py` 讀消融 run 目錄產出 `significance.json`（DSR/PBO/置換 p-value + provenance）。

---

## 8. 測試策略

```
tests/
├── test_invariants/
│   ├── test_no_lookahead.py        # INV-1，全系統最重要的測試
│   ├── test_execution_lag.py       # INV-2 + 偏誤偵測測試
│   ├── test_covariance_valid.py    # INV-3 property test
│   ├── test_garch_conventions.py   # INV-4 round-trip
│   ├── test_accounting.py          # INV-5 手算 golden case
│   └── test_reproducibility.py     # INV-6 雙跑 byte 比對
├── test_models/
│   ├── test_garch_parity.py        # 手刻 vs arch
│   └── test_dcc.py
├── test_data/
│   ├── test_total_return.py        # 除息日抽查
│   └── test_snapshot.py            # hash、唯讀性
├── test_golden/
│   └── test_golden_master.py       # 凍結的小資料集 + 凍結的預期輸出
└── fixtures/                        # 合成資料（已知 GARCH 參數生成的序列等）
```

- 合成資料是模型測試的關鍵：用**已知參數**的 GARCH 過程生成序列，估計必須收斂回真值附近——這是唯一能驗證「估計器正確」而非「估計器跑得動」的方法。
- Golden master 在每次重構後守住行為不變；刻意的行為變更必須同時更新 golden 並在 commit message 說明原因。
- CI（GitHub Actions）：每次 push 跑全部測試。測試不綠不開新功能。

---

## 9. 開發順序與里程碑

每個 Phase 有明確驗收條件（AC），**AC 不過不進下一階段**。這個順序刻意讓「最無聊的基礎」最先完成、「最有趣的模型」最後進場——因為基礎錯了，模型層做得再漂亮都是在錯的地基上刷油漆。

### Phase 0 — 骨架（~數天）
repo 初始化、pydantic config、pytest + CI、pre-commit（ruff/black）、目錄結構。
**AC**：CI 綠燈跑一個 dummy test；config 能載入並驗證 default.yaml。

### Phase 1 — 資料層（~1.5 週）
Provider 介面、yfinance/Tiingo/Stooq/FRED adapters、快照建立與 hash、NYSE 日曆、驗證規則、跨源交叉驗證（§4.5）。
**AC**：`snapshot create` 產出完整快照；總報酬驗證通過；跨源日報酬比對全選單通過（或差異已裁決並記錄於 overrides）；同日重建兩次快照 hash 相同；test_data/ 全綠。

### Phase 2 — 回測核心（~1-2 週，全案最關鍵階段）
事件時鐘、PointInTimeView、engine、accounting、成本、metrics（先不含 bootstrap）。策略只做 `bh_spy` 與 `ew_menu`。
**AC**：INV-1/2/5/6 測試全綠；三日手算 golden case 逐日吻合；`bh_spy` 的回測年化報酬與外部來源（如 portfoliovisualizer）對 SPY 同期的數字在成本與計息差異解釋範圍內吻合——**這是對整個引擎的端到端體檢**。

### Phase 3 — 訊號與組合層（~1 週）
動量、絕對動量、選擇、inverse-vol（此階段波動率暫用 63 日滾動標準差）、`mom_only` 與 `mom_ivol` 策略。
**AC**：消融跑得動並產出比較表；決策 diagnostics 完整落盤。

### Phase 4 — 波動率模型與波動目標（~1-2 週）
`garch_arch`、`ewma`、多步預測、曝險模組與更新帶、`voltarget_only` 與 `full` 策略、QLIKE 評估、block bootstrap。
**AC**：`full` 已實現波動率落在 σ* ± 2% 內；GARCH vs EWMA 的 QLIKE 比較表產出；七策略消融全表產出。

### Phase 5 — DCC 與 ERC（~1 週）
DCC（含參數 walk-forward 重估開關）、ERC 權重選項。
**AC**：DCC vs EWMA 消融結論明確寫入報告（無論結論是什麼——「DCC 沒有顯著貢獻」也是合格的、甚至更誠實的結論）。

### Phase 6 — 手刻 GARCH（~2-3 週，學習里程碑）
`garch_own.py`：t 分配 log-likelihood 推導與實作、變異數遞迴、數值優化、多步預測。
**AC**：parity test 通過（§5.2 標準）→ 轉正為預設 `vol_model`。建議同步寫一份推導筆記，這就是申請時的技術寫作樣本。

### Phase 7 — Dashboard 與研究報告（~2.5 週）
7a 唯讀頁面：總覽、決策解剖、GARCH、相關結構、組合成本、消融、資料品質（§11.2）。
7b Run Lab：job runner、status.json 合約、schema 表單生成（§11.3）。
7c 最終研究報告（以消融表為骨架）。
**AC**：任選一個歷史決策日，Decision Explorer 六層數字與 decisions.parquet 手查一致；從 Run Lab 提交新 config 並完整跑完一次回測，全程不碰終端機；UI 行程強制終止再重啟後，運行中的 job 狀態與進度無損。

**總時程**：認真做約 3-3.5 個月的業餘時間。你同時在準備普業與 CFA——Phase 0-2 可以在暑假密集完成（它們最需要連續專注），Phase 3 之後每階段可獨立推進。

---

## 10. 已知限制與誠實聲明（直接寫進最終報告）

1. **過擬合的殘餘風險**：即使有消融紀律，選單構成、K、σ*、回看期都是人選的。緩解：參數敏感度全揭露、子期間分析、不挑格子。無法完全消除，只能誠實。
2. **橫斷面寬度小**：22 檔 ETF 的排序訊號天生比 500 檔個股雜訊高。這是免費資料的代價，也是預留付費資料層的原因。
3. **動量的 regime 依賴**：長期橫盤或 V 型反轉環境下策略會落後 buy & hold，這是特性不是 bug，報告需展示這些期間而非隱藏。
4. **yfinance 非官方**：快照機制隔離了回溯改價問題，但無法隔離「某天 API 徹底壞掉」——屆時換 provider adapter。
5. **稅務未建模**：30% 股息預扣（§0.4）。
6. **無 live 驗證**：回測與實盤之間永遠有落差（成交價、時點）。v2 若做 paper trading，先跑 6 個月影子組合再談真錢。

---

## 11. Dashboard 規格（決策透明化 + 互動回測）

### 11.1 設計原則

1. **Web 前端，v1 用 Streamlit**。它本身就是瀏覽器 web app，表單可由 pydantic schema 自動生成，圖表零前端程式碼。客製 UX 的 React 路徑見 §11.4，因合約設計正確而隨時可換。
2. **行程邊界取代 import 邊界**。UI 永不 import 引擎、永不在自己的行程內計算。讀：runs/ 與 snapshots/ 的 artifacts。寫：僅限新 run 的 config 檔與 job 請求。啟動計算：僅能 subprocess 呼叫引擎 CLI。
3. **核心價值主張**：回測裡任何一天的任何一個權重，都能在三次點擊內回溯到產生它的每一層輸入。

### 11.2 頁面規格

全域控制列（所有頁面共用）：run 選擇器（可多選以比較）、策略選擇器、日期範圍。

| # | 頁面 | 內容 |
|---|------|------|
| 1 | 總覽 | NAV 疊圖（對數座標，vs benchmarks）、指標表含 block bootstrap CI、drawdown 圖、曝險 E(t) 時間軸、子期間績效表 |
| 2 | **決策解剖**（Decision Explorer） | 日期滑桿選任一決策日，六層垂直瀑布：(a) point-in-time 合格選單（未合格者灰顯並標原因）→ (b) 動量分數長條圖，前 K 高亮 → (c) 絕對動量逐檔 pass/fail，fail 配額流向現金的視覺化 → (d) 每檔 GARCH 21 步 σ̂（含上一決策日對照）→ (e) inverse-vol 權重 → σ̂_p → `E = clip(σ*/σ̂_p, ...)` 以實際數字展開公式，標示是否被更新帶擋下 → (f) 最終目標權重 vs 漂移後現況、預期換手與成本。資料來源：decisions.parquet 的 Diagnostics（§6.2） |
| 3 | GARCH 檢視 | 每資產：條件波動 vs 已實現波動 proxy 疊圖、參數軌跡 (ω, α, β, ν) 隨 refit 演變、persistence α+β、QLIKE 與 MZ-R² 表、標準化殘差 QQ 圖與 ACF。Phase 6 後加「手刻 vs arch parity」對照頁籤 |
| 4 | 相關結構 | DCC 相關矩陣熱圖 + 時間滑桿、任選資產對的相關時間序列、DCC vs EWMA 疊圖 |
| 5 | 組合與成本 | 權重堆疊面積圖（含現金）、曝險軌跡與帶寬事件標記、每次再平衡換手率、累積成本拖累 |
| 6 | 消融比較 | §6.3 七策略指標表與小倍數 NAV 圖、參數敏感度熱圖（如 K × σ* 的 Sharpe 格）。介面常駐提示：「敏感度表用於檢驗穩健性，不是用來挑最好的一格」 |
| 7 | 資料品質 | 快照 MANIFEST 檢視、跨源差異報告（§4.5）瀏覽器、總報酬驗證結果、人工裁決 overrides 清單 |
| 8 | **回測工作台**（Run Lab） | 互動層，規格見 §11.3 |

### 11.3 Run Lab 與 Job Runner

**提交流程：**

```
UI 表單（pydantic schema 自動生成，支援「以既有 run 的 config 為底稿」）
  → 寫 config.yaml 至新 run 目錄
  → pydantic 驗證（不過即擋在 UI 層）
  → subprocess.Popen([python, -m, quantcore.experiments.runner, --config, ...])
  → UI 立即返回，job 進入佇列列表
```

**狀態合約（引擎端維護，UI 端輪詢）：** 每個 run 目錄含

```json
// status.json
{ "state": "queued | running | done | failed",
  "progress": { "stage": "backtest", "pct": 62 },
  "started_at": "...", "finished_at": null,
  "error": null, "log": "run.log" }
```

- 引擎每完成一個回測年度更新一次心跳；崩潰時 traceback 寫入 `error`。
- UI 顯示 job 列表、進度條、log tail；完成的 run 自動出現在全域 run 選擇器。
- **併發控制**：單一 worker 佇列（同時最多一個回測），防止資源互撞。
- **邊界收益**：UI 只能提交通過 schema 驗證的 config，無法注入程式碼；引擎行程崩潰不影響 UI；UI 重啟後 job 狀態無損（狀態在磁碟，不在記憶體）。

### 11.4 v2 升級路徑（FastAPI + React，選配）

需要客製 UX 時：加一層 FastAPI 把「列出 runs、讀 artifacts、提交 job、查 status」包成 REST API，前端換 React。因為 UI 與引擎的合約自始至終是檔案格式，此升級是**純前端替換**，引擎與 artifacts 零改動。v1 刻意不做：Streamlit 以約 1/10 的工作量交付 100% 的功能需求，省下的時間屬於引擎。

---

## 附錄 A — 新專案的 CLAUDE.md 骨架

重練後 repo 根目錄放一份精簡的 CLAUDE.md，內容原則與舊版有本質差異：**舊版列「別碰哪幾行」，新版列「哪些測試在守護什麼」**。

```markdown
# CLAUDE.md — QuantCore

- 規格唯一來源：DEVELOPMENT_GUIDE.md。實作與規格衝突 = bug。
- 六條不變量（INV-1 ~ INV-6）由 tests/test_invariants/ 鎖定。
  改動核心邏輯前先跑它們；改完必須全綠。
- 任何參數不得出現在 config/ 以外（發現魔術數字 = 打回）。
- presentation/ 不 import 引擎；讀取限 runs/ 與 snapshots/，啟動回測只能以 subprocess 呼叫引擎 CLI。
- 禁用 pickle。序列化一律 parquet / JSON。
- 新增複雜度（新模型、新規則）必須附帶消融證據。
- 回測資料只來自 snapshots/，不直連網路。
```

## 附錄 B — 關鍵文獻（報告引用與實作依據）

- Jegadeesh & Titman (1993) — 橫斷面動量原典
- Moskowitz, Ooi & Pedersen (2012) — 時間序列動量（絕對動量過濾的依據）
- Barroso & Santa-Clara (2015) — 波動管理動量（本系統兩層架構的直接依據）
- Moreira & Muir (2017) — Volatility-Managed Portfolios（波動目標的依據）
- Bollerslev (1986) / Engle (2002) — GARCH / DCC 原典
- Patton (2011) — QLIKE 等波動預測損失函數的穩健性
- Politis & Romano (1994) — stationary bootstrap

---

*v1.2 — 2026-07-09。新增 §11 Dashboard 完整規格（Decision Explorer、Run Lab、行程邊界），擴充 §6.2 Diagnostics schema。v1.1 新增 §4.5 多資料源交叉驗證（Tiingo/Stooq）。設計決策經兩輪討論定案：美股 ETF 選單自動選標的、動量選擇 + GARCH/DCC 定倉位、免費資料 + 預留付費層、不做新聞層。*
