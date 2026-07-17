# Phase 1（資料層）開發回顧

> 期間：2026-07-13 → 2026-07-16
> 分支：`feature/phase1-data-layer` → merged to `main`（PR #1，CI 綠燈）
> 產出：33 commits、39 檔（+8,892 / −22）、77 項測試、首份可重現快照 `snapshots/2026-07-16_20ed09`

---

## 1. 摘要

Phase 1 目標是建立**回測永不直連網路**的資料基礎：一次抓取、驗證、凍結成不可變快照，之後所有回測只讀快照。

結果：規格 §9 的五項 AC 全數達成。但**過程與原計畫有實質偏離**，且多數偏離不是規劃疏忽，而是**只有真實資料才會暴露的問題**——其中三項（Stooq 失效、DBC 資料不可信、yfinance 調整價不可重現）足以寫進最終報告的「已知限制」。

一句話總結：**§4.5 跨源交叉驗證機制證明了它的價值——它抓到了真實的資料損壞，包含 yfinance 本身的錯誤。**

---

## 2. 交付內容

| 模組 | 職責 |
|------|------|
| `data/provider.py` | `DataProvider` Protocol + tidy schema（§4.1） |
| `data/providers/yfinance_adapter.py` | primary；raw close + **自建決定性含息調整** |
| `data/providers/tiingo_adapter.py` | validation；429 退避重試 + token 遮蔽 |
| `data/providers/twelvedata_adapter.py` | **實際第三源仲裁**（取代失效的 Stooq）；8 req/min 節流 |
| `data/providers/fred_adapter.py` | DTB3（keyless） |
| `data/providers/stooq_adapter.py` | 預留介面（端點已失效，未併入） |
| `data/calendar.py` | NYSE 交易日曆（XNYS，起始界 1990） |
| `data/adjust.py` | 由 close + 股息 + 拆分 back-adjust（決定性） |
| `data/hashing.py` | canonical hash（守 AC-4 位元級可重現） |
| `data/validation.py` | §4.3 五項資料驗證 |
| `data/crosssource.py` | §4.5 跨源比對 + 三源少數服從多數仲裁 |
| `data/snapshot.py` | 快照建立/載入/完整性驗證 + CLI |

**首份快照**：20 檔 ETF、2005-01-03 → 2026-07-15、107,750 筆價格 + 5,617 筆 DTB3。

---

## 3. 開發流程

採 spec-first + TDD + 每個任務兩階段審查：

```
brainstorming → 設計文件 → 實作計畫（12 tasks）
   → 每個 task：subagent 以 TDD 實作 → 規格符合性審查 → 程式碼品質審查 → 修正 → 再審
   → Task 12：真實資料端到端建立快照（唯一需要網路的一步）
```

**刻意的分工**：每個 adapter 拆成「薄網路邊界 + 純正規化函數」。純函數與所有驗證/快照邏輯用 fake providers 離線測試（77 項，CI 不需任何金鑰）。網路邊界只在 Task 12 真實驗證。

這個分工是對的——但也正是它讓某些問題**只能**在 Task 12 才暴露（見 §5.2）。

---

## 4. 與原計畫的差異

| 差異 | 原計畫 | 實際 | 原因 |
|------|--------|------|------|
| **第三源** | Stooq（規格 §4.5 指定，免金鑰） | **Twelve Data**（免費金鑰） | Stooq 免金鑰 CSV 端點已被 JS 反爬封鎖；`pandas-datareader` 亦移除 Stooq 支援 |
| **仲裁時機** | v1 只做兩源（brainstorm 時刻意延後 Stooq） | v1 就做**三源仲裁** | 兩源在真實資料上有 13/21 檔分歧且無法判斷誰對，被迫提前 |
| **選單** | 21 檔（含 DBC） | **20 檔**（移除 DBC） | DBC 2008 資料三源皆不一致、§4.5 無法認證 |
| **含息調整** | 直接用 yfinance 的 `Adj Close` | **自建 `adjust.py` 決定性調整** | yfinance 的 `Adj Close` 每次抓取都微幅重算，破壞 AC-4 |
| **config** | 規格未提 | 新增 `data_quality` 區塊 | 遵守 CLAUDE.md「參數不得出現在 config 以外」，把 §4.3/§4.5 門檻全部外部化 |

> 註：`adjust.py` **完全不在原計畫中**——它是 AC-4 失敗後才被迫生出來的模組。

---

## 5. 遇到的問題

### 5.1 審查階段就攔下的（真實資料之前）

這些全部由「規格符合性審查 + 程式碼品質審查」抓到，未進入真實執行：

| 問題 | 影響 |
|------|------|
| `canonical_hash` 未固定欄序；NaN 正負號、`-0.0` 未正規化 | 直接破壞 AC-4（此模組唯一職責就是決定性） |
| **§4.5 滾動窗用「日曆日」，規格明寫「交易日」** | **規格違反，且源頭是我自己寫的計畫**。30 日曆日 ≈ 21 交易日，會漏掉成群分歧 |
| `check_total_return` 未 groupby ticker | 多檔資料會跨檔汙染報酬計算 |
| `check_missing_values` 對「整段全 NaN」靜默放行 | 資料完全遺失卻通過檢查——正是此檢查該抓的最壞情況 |
| `yf.download` 單 ticker 仍回傳 MultiIndex 欄位 | **會在 Task 12 直接崩潰**（審查者實際重現） |
| Tiingo token 洩漏進 `HTTPError` 訊息 | 金鑰會出現在 traceback / CI log |
| `DataProvider` protocol 測試是空操作 | 從未真正驗證 `isinstance`（`@runtime_checkable` 的存在意義） |
| `load_snapshot` 只驗 prices hash；provenance 寫死 | 竄改 rates/metadata 不會被發現；MANIFEST 謊報來源 |

**教訓**：兩階段審查（先規格、後品質）不是形式。上表半數以上是「測試全綠但仍然錯」的問題。

### 5.2 只有真實資料才暴露的

| 問題 | 現象 | 解法 |
|------|------|------|
| NYSE 日曆預設只建近 ~20 年 | 首個 session = 2006-07-17，抓 2005 直接 `DateOutOfBounds` | 明確指定起始界 1990 |
| Tiingo 每小時 50 req 上限 | debug 期間重跑數次即耗盡，429 中斷建置 | 加 429 指數退避重試；理解單次建置只需 21 req（月頻操作完全夠用） |
| Stooq 端點失效 | 全 21 檔 404；帶瀏覽器 UA 則回 JS 驗證牆 | 判定為反爬機制，**不繞過**；改用 Twelve Data |
| `.env` 手動編輯出錯 | 變數名打成 `TEWLVEDATA_API_KEY`；Tiingo key 被截成 36 字（403） | 診斷時只印「鍵名 + 長度」不印值 |
| **§4.5 判定 13/21 檔失敗** | 真實的 yfinance ↔ Tiingo 日報酬分歧 | 見下 §6.1 |
| **DBC 三源皆不一致** | 2008 商品崩盤期，三個來源彼此都對不上 | 移除 DBC |
| **AC-4 失敗** | 同日重建 hash 不同 | 見下 §6.2 |

---

## 6. 關鍵發現（建議寫進最終報告 §10）

### 6.1 §4.5 抓到了真實的資料損壞

首次真實建置，13/21 檔未通過跨源驗證。診斷後確認**不是程式 bug**（改用對齊網格重算，差異數完全相同），而是真實分歧，且集中在 **2008 金融危機期的類股 ETF**。

引入 Twelve Data 三源仲裁後：

| 裁決 | 筆數 | 意義 |
|------|------|------|
| `validation_outlier` | **343** | Tiingo 是錯的那一方（yfinance + TD 一致） |
| `primary_outlier` | **2** | **yfinance 本身是錯的**（Tiingo + TD 一致） |

13 檔中 12 檔的分歧來自 **Tiingo 的壞資料**（典型症狀：單日暴衝隔日反轉的壞報價，例如 XLK 2014-08-11 Tiingo 顯示 +3.6% 隨即 −3.1%，yfinance 與 TD 皆 ≈ 0）。

**結論**：yfinance 作為 primary 是站得住腳的（20 檔中只有 2 天被確認錯誤，且孤立、已記入 overrides）。但這個結論**不是假設出來的，是被兩個獨立來源驗證出來的**——這正是 §4.5 存在的理由。

### 6.2 yfinance 的 `Adj Close` 不可用於可重現研究 ⚠️

AC-4（同日重建 hash 相同）一度失敗。逐欄量化後：

| 欄位 | 跨次抓取是否一致 |
|------|-----------------|
| 原始 `close` | **100% 位元相同**（107,730/107,730） |
| `dividends` / `splits` | **100% 相同**（20 檔皆是） |
| FRED `DTB3` | **100% 相同** |
| **`Adj Close`** | **每次都變**（max 相對差 1.85e-6、中位數 1.2e-7） |

原因：yfinance 每次抓取都會用完整股息歷史**重新推算**整條回調序列，浮點微差使整條 `Adj Close` 漂移。差異本身對研究無關緊要（次於 1 bp），但 **SHA-256 不管「無關緊要」**——任何一位元不同就是不同 hash。

**解法**：只存穩定的原始 `close`，自建 `adjusted_close`（僅股息回調；yfinance 的 close 與 dividends 皆已拆分調整，再套 splits 會重複調整——實測會造成 ~0.5 的相對誤差）。自建結果與 yfinance 的 `Adj Close` 相符至 **1.6e-6**（即只差 yfinance 自己的抖動），但**是決定性的**。

驗證：build#1 == build#2 == `2026-07-16_20ed09`。AC-4 通過。

> 這條發現有普遍性：**任何以 yfinance `Adj Close` 為基礎、宣稱可重現的回測，其實都不可重現。**

### 6.3 免費資料源是會腐朽的基礎設施

一個 Phase 內就遇到：Stooq 端點死亡（規格寫作時仍可用）、`pandas-datareader` 移除 Stooq、Tiingo 每小時 50 req、Twelve Data 免費層只回最近 5,000 筆（≈ 2006-08 起，故 2005–2006 初期無法仲裁）。

Provider 介面抽象在此獲得回報：換掉整個第三源只需新增一個 adapter，仲裁邏輯與快照流程一行未改。

### 6.4 離線測試涵蓋不到什麼

77 項離線測試全綠，仍然擋不住：日曆界限、`yf.download` 欄位形狀、`Adj Close` 抖動、真實跨源分歧。**這些全部是「與外部世界的介面」問題**，不是邏輯問題。

這不代表離線測試沒用（見 §5.1，它們配合審查擋下了 8 類真實缺陷），而是說明：**網路邊界的正確性只能靠真實執行驗證**，Task 12 不是形式驗收。

---

## 7. 遺留事項

- **DBC**：日後若找到可信的商品 ETF 歷史資料源可加回（目前廣義商品曝險缺口；GLD 僅黃金）。
- **Twelve Data 涵蓋範圍**：免費層 5,000 筆上限 → 2006-08 之前無法仲裁。若日後 2005–2006 出現成群分歧，需分段抓取。
- **Stooq adapter**：保留為預留介面，端點若復活可直接接回。
- **2 筆 `primary_outlier`**：yfinance 被確認錯誤的 2 天已記入 `metadata.json` overrides，孤立未成群故放行；若日後對該區間敏感可再處理。
- **`adjust.py` 的 splits 路徑**：目前 yfinance 路徑傳空 splits（因 close 已拆分調整）。該路徑已有測試，但尚未在真實資料上跑過——未來若接入真正未調整的來源才會用到。

---

## 8. 數字

| 項目 | 值 |
|------|-----|
| commits / 檔案 | 33 / 39（+8,892 / −22） |
| 測試 | 77 項（全離線，CI 不需金鑰） |
| 快照 | 20 檔、2005-01-03→2026-07-15、107,750 筆價格 |
| §4.5 裁決 | 345 筆（343 Tiingo 錯 / 2 yfinance 錯） |
| 單次建置 API 用量 | yfinance 20（免費）+ Tiingo 20（50/hr）+ TwelveData 20（800/day）+ FRED 1 |
| AC | 5/5 達成；CI 綠燈 |
