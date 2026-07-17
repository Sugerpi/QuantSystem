# Phase 1 — 資料層 設計文件

> 日期：2026-07-13
> 規格來源：`DEVELOPMENT_GUIDE v1.2.md` §4（資料層）、§2.1（模組地圖）、§9（Phase 1 AC）
> 狀態：已與使用者確認範圍，待實作

## 0. 範圍決策（已確認）

| 決策 | 選擇 |
|------|------|
| 產出方式 | 先寫全部程式碼 + 離線測試（合成 fixtures，CI 全綠），再一起跑真實快照 |
| 密鑰保存 | gitignored `.env` + 環境變數（`TIINGO_API_KEY`），附 `.env.example`；建議事後輪替金鑰 |
| 交叉驗證來源 | v1 先兩源：yfinance（primary）+ Tiingo（validation）；Stooq 預留同介面 adapter，暫不併入驗證 |
| 測試範圍 | 只做 Phase 1 的 `tests/test_data/`；INV 測試留給 Phase 2 |
| FRED 金鑰 | 不需要——使用 keyless DTB3 端點（`pandas-datareader` FRED / `fredgraph.csv`） |

## 1. 目標與驗收條件（§9）

Phase 1 完成須滿足：
1. `snapshot create` 產出完整快照（`prices.parquet` / `rates.parquet` / `metadata.json` / `MANIFEST.json`）。
2. 總報酬驗證通過（§4.3-1）。
3. 跨源日報酬比對全選單通過（或差異已裁決並記錄於 `metadata.json` 的 `overrides`）。
4. 同日重建兩次快照 hash 相同。
5. `tests/test_data/` 全綠。

## 2. 模組設計

依 §2.1 模組地圖，Phase 1 交付：

```
quantcore/data/
├── provider.py                 # DataProvider Protocol（§4.1）
├── providers/
│   ├── yfinance_adapter.py     # primary
│   ├── tiingo_adapter.py       # validation（TIINGO_API_KEY）
│   ├── stooq_adapter.py        # arbiter（介面預留，v1 暫不併入驗證）
│   └── fred_adapter.py         # DTB3（keyless）
├── calendar.py                 # NYSE（exchange_calendars XNYS）
├── snapshot.py                 # 建立/載入/hash + CLI
├── validation.py               # §4.3 五項檢查
├── crosssource.py              # §4.5 跨源日報酬比對
└── hashing.py                  # 決定性 canonical hash（§4 / AC-4）
```

### 2.1 DataProvider 介面（§4.1）

`Protocol`，方法簽章完全依規格：

```python
class DataProvider(Protocol):
    def fetch_prices(self, tickers, start, end) -> pd.DataFrame:
        """tidy 格式：columns = [date, ticker, close, adj_close, volume]"""
    def fetch_metadata(self, tickers) -> dict: ...
    def fetch_series(self, series_id, start, end) -> pd.Series: ...
```

引擎任何模組不得 import yfinance；只認識 Protocol 與快照格式。

### 2.2 Adapter 兩層結構（可離線測試的網路邊界）

每個 adapter 拆為：
- **網路邊界**（薄）：真正的 HTTP / 套件呼叫（yfinance、`requests` 對 Tiingo、Stooq CSV URL、FRED keyless CSV）。
- **純正規化函數**：raw payload → tidy `[date, ticker, close, adj_close, volume]`。

純函數以存檔的 fixture payload 做單元測試（無網路）。快照 / 驗證 / 跨源邏輯以實作 Protocol 的 **fake provider** 測試 → `tests/test_data/` 全離線、CI 可綠。

### 2.3 NYSE 日曆（`calendar.py`）

包裝 `exchange_calendars` 的 XNYS。對外提供：交易日集合查詢、`sessions_in_range(start, end)`、`is_session(date)`。供驗證第 4 項（日曆一致）與第 5 項（單調性）使用。

## 3. 快照格式與決定性 hash

### 3.1 目錄結構（§4.2）

```
snapshots/{YYYY-MM-DD}_{short_hash}/
├── prices.parquet     # 全選單原生完整序列（不做跨資產交集裁切）
├── rates.parquet      # DTB3
├── metadata.json      # inception_date、名稱、資產類別、overrides、參與來源
└── MANIFEST.json      # 建立時間、provider、config hash、各檔 content SHA-256、discrepancy report hash
```

- 建立後唯讀。parquet gitignore；`MANIFEST.json` 進 git。
- 每檔資產保留原生完整序列，上市前為 NaN（由 point-in-time 規則於後續 Phase 處理），**絕不跨資產交集裁切**。

### 3.2 決定性 canonical hash（關鍵決策，守 AC-4）

**MANIFEST 的 content SHA-256 由資料的 canonical 表示計算，而非 parquet 原始位元組。**

理由：parquet 內嵌套件版本 / 時間戳 → 位元組不決定性。改以 `canonical_hash(df)`：以固定欄位順序，逐欄雜湊「dtype 標籤 + 原始值」（`float64.tobytes()`、日期為 int64 epoch-days、字串長度前綴 utf-8）。此法跨 pandas/pyarrow 版本與 OS 皆決定性。

- 快照目錄名的 `{short_hash}` = 對 (config 相關子集 + 各檔 content hash) 的合併雜湊取前 6 hex。
- 同日、同來源資料 → 相同 hash → 相同目錄名 → AC-4 成立。
- parquet 仍為磁碟儲存格式；只有「完整性 hash」走 canonical。

## 4. 資料驗證（§4.3）與跨源驗證（§4.5）

### 4.1 `validation.py`（§4.3 五項，純函數，任一硬失敗即拒絕產出快照）

1. **總報酬正確性**：SPY 抽查數個除息日，`adj_close` 報酬 ≈ `close` 報酬 + 股息/前收盤（容差內）。
2. **極端值**：單日 |r| > 20% 的 ETF 列人工確認清單。
3. **缺值**：上市後序列中間 NaN → 報告；連續缺值 > 5 日 → 拒絕。
4. **日曆一致**：所有日期 ∈ NYSE 交易日曆。
5. **單調性**：日期嚴格遞增、無重複。

每項回傳結構化 pass/fail + report rows。

### 4.2 `crosssource.py`（§4.5，v1 兩源）

1. 每檔資產同時自 primary（yfinance）與 validation（Tiingo）抓取，對齊日期。
2. **比對日報酬，不比價格水準**。
3. `|r_primary − r_validation| > 50 bps` 的日子進 discrepancy report。
4. 孤立差異 → 記錄放行；**同一資產 30 個交易日窗內 ≥ 3 筆 → 快照建立失敗**，強制人工裁決，結果寫入 `metadata.json` 的 `overrides`（永久可追溯）。
5.（三源預留）三源在場時少數服從多數；v1 兩源時不適用。
6. `MANIFEST.json` 記錄參與來源與 discrepancy report 的 hash。

## 5. CLI、密鑰、依賴

### 5.1 CLI

```
python -m quantcore.data.snapshot create --config quantcore/config/default.yaml
```

argparse 實作；成功後印出快照目錄，使用者手動填入 `default.yaml` 的 `snapshot:` 欄位。流程（§4.2）：抓取 → 驗證（§4.3）→ 跨源（§4.5）→ 全過才寫檔。

### 5.2 密鑰

`.env`（gitignored）+ `.env.example`。以小工具讀 `os.environ`（可用 `python-dotenv`）。缺 `TIINGO_API_KEY` 時給出清楚錯誤與設定指引，不將金鑰寫入任何進版控檔案或 log。

### 5.3 依賴（加入 `pyproject.toml`）

執行期：`pandas`、`pyarrow`、`numpy`、`yfinance`、`requests`、`exchange_calendars`、`pandas-datareader`、`python-dotenv`。
開發期：HTTP mock（`responses` 或存檔 fixtures）。

## 6. 測試計畫（`tests/test_data/`，全離線）

- `test_total_return.py`：§4.3-1 除息日抽查（合成 SPY 除息 fixture）。
- `test_snapshot.py`：hash 決定性（同資料建兩次 hash 相同）、唯讀性、MANIFEST 內容、載入往返。
- `test_normalization.py`：各 adapter 純正規化函數 vs fixture payload → tidy 格式。
- `test_crosssource.py`：50bps 門檻、30 日窗 ≥3 觸發失敗、孤立差異放行。
- `test_validation.py`：五項檢查各自 pass/fail 情境。
- `test_calendar.py`：NYSE session 查詢、非交易日判定。
- fixtures：合成價格 / 報酬序列、已知除息事件、跨源差異情境。

開發採 **TDD**：每個元件先寫測試再寫實作。CI 每次 push 跑全部測試。

## 7. 依賴方向與硬性規則檢核

- 依賴方向 `config ← data`：`data` 只 import `config`，不反向。✅
- 無魔術數字（依 CLAUDE.md 硬性規則「任何參數不得出現在 config 以外」）：所有資料品質門檻——跨源 `discrepancy_bps`（50）、`window_days`（30）、`window_max_hits`（3）、極端值 `extreme_return`（0.20）、缺值 `max_consecutive_nan`（5）、總報酬容差——全部進 config schema 新增的 `data_quality` 區塊（`_Strict`，`extra=forbid`），並於 `default.yaml` 給預設值。模組不得內嵌這些數字。
- 禁 pickle：序列化一律 parquet / JSON。✅
- 回測不直連網路：只有 `snapshot create` 連網；引擎讀快照。✅

## 7a. Config schema 擴充

`config/schema.py` 新增 `DataQualityConfig(_Strict)` 並掛到 `QuantConfig`：

```
data_quality:
  discrepancy_bps: 50        # §4.5 跨源日報酬差異門檻
  window_days: 30            # §4.5 滾動窗（交易日）
  window_max_hits: 3         # §4.5 窗內差異筆數上限（達到即失敗）
  extreme_return: 0.20       # §4.3-2 單日 |r| 極端值門檻
  max_consecutive_nan: 5     # §4.3-3 連續缺值上限（超過即拒絕）
  total_return_tol_bps: 10   # §4.3-1 總報酬抽查容差
```

對應在 `default.yaml` 補上 `data_quality:` 區塊；`test_config.py` 補驗證測試（沿用 Phase 0 風格）。

## 8. 交付順序（供 writing-plans 展開）

1. deps + `.env` 機制 + `config` schema 擴充（`data_quality`）+ `hashing.py`（決定性 hash，先鎖 AC-4）。
2. `provider.py` + `calendar.py`。
3. adapters（正規化純函數優先，fixtures 測試）。
4. `validation.py`（§4.3）。
5. `crosssource.py`（§4.5）。
6. `snapshot.py` + CLI（串接全流程）。
7. 一起跑真實快照（AC 1–4 端到端），填入 `default.yaml`，更新 `PROGRESS.md`。
