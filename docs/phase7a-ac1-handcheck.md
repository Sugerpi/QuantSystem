# Phase 7a AC① 人工手查 — Decision Explorer 六層 vs `decisions.parquet`

> AC①（規格 §9 Phase 7 第一關）：任選一個歷史決策日，Decision Explorer 六層數字與 `decisions.parquet` 手查逐格一致。
> 本文件記錄**人工形式**的驗證。**自動化形式**由 `tests/test_presentation/test_decision_explorer.py` 的 golden 測試常態守護（六層抽取逐層對上獨立解析的原始列，含 executed 與 null/log-only 兩路徑）。

## 驗證方法

對真實 canonical run 任選一決策日，比對兩條**獨立**路徑：
1. **Decision Explorer 的資料源** `readers.decision_layers(run_dir, strategy_id, decision_date)`（頁 2 渲染此結構）。
2. **獨立手查**：`pd.read_parquet(decisions.parquet)` 直接取同一列，對每個 JSON 字串欄 `json.loads`、對純量欄直接讀。

兩者六層逐格相等即通過（抽取無錯映/無腐蝕）。

## 選定決策

| | |
|---|---|
| run | `runs/2026-07-29_2347_canonical_ewma`（快照 `2026-07-16_20ed09`，corr_model=ewma，全 8 策略） |
| 策略 | `full` |
| 決策日 | **2016-04-06** |
| event | `exposure_check`（曝險檢查日；`band_blocked=True` → log-only，`execution_date=NaT`） |

> 此列剛好落在 **band-blocked / log-only 路徑**（曝險在更新帶內、不執行、`execution_date` 為空），故本手查同時覆蓋六層的 executed 欄位與 null 路徑。

## 六層逐格比對（Decision Explorer ↔ decisions.parquet）

| 層 | §11.2 內容 | 值（`decision_layers` == 原始 parquet） | 一致 |
|----|-----------|------|:---:|
| (a) | point-in-time 合格選單 | 20 檔全選單：`EEM,EFA,GLD,HYG,IEF,IWM,LQD,QQQ,SPY,TLT,VNQ,XLB,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY` | ✅ |
| (b) | 動量分數（前 K 高亮） | 全 20 檔分數 dict（e.g. `XLU 0.1205`、`XLP 0.0664`、`XLE −0.2579`…）；`selected = [XLU, XLP, TLT, IEF, GLD]`（正動量前 5，此期防禦資產居多） | ✅ |
| (c) | 絕對動量 pass/fail | `{GLD, IEF, TLT, XLP, XLU}` 全 `True`（皆過 T-bill hurdle） | ✅ |
| (d) | GARCH σ̂（年化純量） | `GLD 0.1852, IEF 0.0551, TLT 0.1259, XLP 0.1147, XLU 0.1512` | ✅ |
| (e) | 曝險公式 | `w_risky`（inverse-vol）`{IEF 0.377, XLP 0.201, TLT 0.166, XLU 0.140, GLD 0.116}`；`σ̂_p = 0.06382`；`exposure_raw = clip(σ*/σ̂_p) = 1.5669`；`exposure_applied = 1.0`；**`band_blocked = True`** | ✅ |
| (f) | 最終目標權重（含 CASH） | `{IEF 0.377, XLP 0.201, TLT 0.166, XLU 0.140, GLD 0.116, CASH 0.0}` | ✅ |

（完整浮點值見驗證腳本輸出；上表為對照摘要。所有 11 個比對項——含 `sigma_p`/`exposure_raw`/`exposure_applied`/`band_blocked` 純量——皆 `layers == raw`。）

## 結論

**六層逐格一致，AC① 人工手查通過。** Decision Explorer（頁 2）渲染的每一層數字，都能在同一列 `decisions.parquet` 手查到相同值——回測裡這一天 `full` 的目標權重，可三次點擊回溯到產生它的每一層輸入（合格選單 → 動量 → 絕對動量 → σ̂ → 曝險公式 → 目標權重），符合 §11.1「核心價值主張」。

- **自動化守護**：`tests/test_presentation/test_decision_explorer.py::test_six_layers_match_raw_decisions`（golden，逐層獨立比對）+ `test_decision_layers_null_path_execution_date`（band_blocked/NaT 路徑）常態鎖住此性質。
- **重跑指令**：`uv run python`（見計畫 `docs/superpowers/plans/2026-07-30-phase7a-presentation-app.md` Task 8 Step 1/2 腳本）可對任一 run/決策日重跑此手查。

*Phase 7a AC① 人工手查 — 2026-07-30。run `2026-07-29_2347_canonical_ewma`、full、2016-04-06。*
