# CLAUDE.md — QuantCore

本檔為 repo 根目錄的精簡開發守則。原則：**列「哪些測試在守護什麼」，不列「別碰哪幾行」**。

## 規格來源
- 規格唯一來源：`DEVELOPMENT_GUIDE v1.2.md`（最新版）。實作與規格衝突 = bug。
- 舊版 `DEVELOPMENT_GUIDE.md` / `v1.1.md` 僅供對照，不作為實作依據。

## 六條不變量（INV-1 ~ INV-6）
由 `tests/test_invariants/` 鎖定。改動核心邏輯前先跑它們；改完必須全綠。

| 不變量 | 內容 | 守護測試 |
|--------|------|---------|
| INV-1 | 無 Look-Ahead：決策日 t 只依賴 timestamp ≤ t 的資料 | `test_no_lookahead.py` |
| INV-2 | 訊號-執行延遲 ≥ 1 個交易日 | `test_execution_lag.py` |
| INV-3 | 共變異數矩陣永遠對稱、PSD、對角線 = 個別變異數 | `test_covariance_valid.py` |
| INV-4 | GARCH 數值慣例（×100 估計 / ÷100 還原、Student-t、α+β<1） | `test_garch_conventions.py` |
| INV-5 | 會計恆等式：NAV 遞推 + 權重恆和為 1 | `test_accounting.py` |
| INV-6 | 可重現性：(config, snapshot_hash, git_commit) 三元組決定輸出 | `test_reproducibility.py` |

## 硬性規則
- 任何參數不得出現在 `config/` 以外（發現魔術數字 = code review 打回）。
- `presentation/` 不 import 引擎；讀取限 `runs/` 與 `snapshots/`，啟動回測只能以 subprocess 呼叫引擎 CLI。
- 禁用 pickle。序列化一律 parquet / JSON。
- 新增複雜度（新模型、新規則）必須附帶消融（ablation）證據。
- 回測資料只來自 `snapshots/`，不直連網路。
- 依賴方向單向：`config ← data ← models ← signals/portfolio ← backtest ← experiments ← presentation`。違反即架構錯誤。

## 開發紀律
- 每個 Phase 有明確 AC（驗收條件），AC 不過不進下一階段（見規格 §9）。
- 測試不綠不開新功能。CI 每次 push 跑全部測試。
- 進度追蹤見 `PROGRESS.md`。
