# 曝險更新帶 log（相對）模式 — 設計文件

- 日期：2026-08-13
- 規格章節：§1.6 Step 3、§1.7（曝險出口與更新帶）
- 狀態：設計已核可，待寫實作計畫

## 1. 動機

現行曝險更新帶用**絕對**判定 `|E_new − E_current| > exposure_band`（0.10）。實測（canonical_ewma run，`full`）曝險檢查日帶突破率 16.1%，且突破率不均：平靜年（2016=6%、2012=8%）與動盪年（2020=29%、2021=31%）差距大，連低波動的 2017 都達 25%。

根因**不是** σ̂_p 估計 bug（已用讀碼 + 實測雙重排除：refit/filter 的 ×100/÷100² 縮放一致、同一聚合函式；實測 selection→exposure_check 交界是所有轉換中 σ̂_p 變動最小者，反證無估計器斷層）。根因是 `E = σ*/σ̂_p` 的**凸性**：靈敏度 `dE/dσ̂_p = −E/σ̂_p`，在 σ̂_p 接近 σ*=0.10（E 大）時放大。搭配**絕對**帶,同樣的 σ̂_p 相對抖動在平靜期造成的 E 位移遠大於動盪期，導致平靜期不必要換手。

## 2. 目標與非目標

**目標**：把更新帶的雜訊容忍度改為在所有波動 regime 下一致（相對／對數空間）。

**非目標**：
- 不動 σ̂_p 估計器（估計品質非本案根因；QLIKE 另有出口）。
- 不改再平衡時程（§1.7 的 21/5 不變）。
- 不改選擇日行為（選擇日仍 `e_current=None` 無條件套用 E，見 §1.7 既有語義）。

## 3. 帶語義

`target_exposure` 新增 `band_mode` 參數，判定式二選一，其餘（clip、首次繞過、band_blocked 回傳 raw）完全不變：

```
absolute（現行）：  |clipped − e_current|            > band
log（新增）：       |ln(clipped) − ln(e_current)|    > band
```

數學依據：`ln(E) = ln(σ*) − ln(σ̂_p)` ⟹ `|Δ ln E| = |Δσ̂_p / σ̂_p|`（未 clip 區間內精確成立）。故 log 帶的容忍度直接以「σ̂_p 相對變動」計量，與 σ̂_p 水準無關。log 帶在 E 空間是**乘性、上下不對稱**的（可乘 `e^band` 或除 `e^band` 才觸發），對比值型的曝險量更自然。

clip 相容性：`clipped`、`e_current` 皆落在 `[e_min, 1.0]`。深度平靜（E pin 在 1.0）或極端危機（pin 在 e_min）時 log 差恆為 0 → 不穿，行為正確；log 帶只在未 clip 的內部（實測約 75.8% 的時間）起作用。

## 4. 設定（config）

`risk` 區新增**一個** enum，沿用既有 `exposure_band` 數字（其含義隨 mode 變）：

```yaml
exposure_band_mode: absolute   # absolute | log；default 維持 absolute（現行行為）
exposure_band: 0.10            # absolute=E 位移門檻；log=ln(E) 位移門檻（相對）
```

**不新增第二個帶參數**，避免一個永遠 inert 的死參數。frontier 消融時每個 mode 各自掃 `exposure_band` 網格（§7）。

## 5. 誠實失敗守護（schema 跨欄位驗證）

log 判定需 `clipped, e_current > 0`。實務上 `e_min=0.10>0` 保證成立，但 config schema 允許 `exposure_min=0`。

**規則**：當 `exposure_band_mode == "log"` 時，schema 驗證強制 `exposure_min > 0`；否則以明確訊息拒絕該 config（不讓 `ln(0)=−inf` 靜默污染曝險）。

`target_exposure` 本身在收到 `band_mode="log"` 且 `e_current` 或 `clipped` ≤ 0 時亦 `raise ValueError`（防止非經 config 路徑的呼叫繞過守護）。

## 6. 改動面與相依

曝險出口仍是 `exposure.py` 唯一一處，改動小：

| 檔案 | 改動 |
|------|------|
| `quantcore/portfolio/exposure.py` | `target_exposure` 加 `band_mode: str = "absolute"` 參數 + log 分支（純函數，一處）；未知 mode 與 log 非法域 `raise` |
| `quantcore/backtest/strategies/vol_target_base.py` | `_exposure_decision` 多傳 `cfg.risk.exposure_band_mode`（一行） |
| `quantcore/config/schema.py` | 加 `exposure_band_mode` 欄位（enum）+ `exposure_min>0`（log 模式）跨欄位驗證 |
| `quantcore/config/default.yaml`（及 canonical_*.yaml） | 加 `exposure_band_mode: absolute` |
| `quantcore/backtest/metrics.py` | `compute_metrics` 加 `annualized_vol`（§6.4 明列該有、目前僅存在於 vol_target_ac；補上後 frontier 可零改動重用 `run_ablation`） |

**向後相容**：現有 `test_exposure.py` 全部不帶 `band_mode` → 走 default absolute → 一字不改、全綠。`default.yaml` 加 `exposure_band_mode: absolute` 後既有回測 bit 級不變（INV-6）。`compute_metrics` 加欄位屬 additive；若 `test_metrics.py` 有精確 dict 比對需同步更新。

## 7. 消融：換手率–追蹤誤差前沿

判準：**log 帶是否在「換手率 vs σ* 追蹤誤差」前沿上支配 absolute**，在 `voltarget_only`（單資產、無選股雜訊，看帶本身行為）與 `full`（實戰決策，判 default 是否翻）**兩者**上都成立。

重用現有 `run_ablation`（一次動一參數），frontier = 兩趟掃描：

- **Pass A**：baseline `exposure_band_mode=absolute`，grid `exposure_band ∈ {0.06, 0.08, 0.10, 0.13, 0.16}`
- **Pass B**：baseline `exposure_band_mode=log`，grid `exposure_band ∈ {0.10, 0.15, 0.20, 0.25}`

每 cell 對 `voltarget_only` 與 `full` 取比較表的：
- **年化換手率** = `annualized_turnover`（現成）
- **σ* 追蹤誤差** = `|annualized_vol − 0.10|`（§6 補 `annualized_vol` 後可得）

新增薄驅動 `quantcore/experiments/exposure_band_frontier.py`：跑上述兩趟、併兩張 `comparison.parquet`、輸出前沿表（mode × band → turnover、tracking_error、sharpe）與支配判定。ablation.py 本身**不改**。

## 8. 驗收條件（AC）

1. **正確性**：`target_exposure` log 分支通過新測試——邊界（`|Δln E|` 恰 = band → blocked，嚴格 `>`）、跨水準等效性（同一相對 σ̂_p 變動在高低 σ̂_p 兩處皆穿／皆不穿）、首次 `e_current=None` 繞過、log 非法域 raise。
2. **相容**：既有 `test_exposure.py`、`test_invariants/`（尤 INV-5/6）全綠；absolute 路徑 canonical run 輸出不變。
3. **schema**：`band_mode=log` 且 `exposure_min=0` 的 config 被拒並附明確訊息（新測試）。
4. **消融產出**：frontier 表在 `voltarget_only` + `full` 上產出，含 turnover／tracking_error／sharpe 與支配判定。
5. **default 翻轉**：僅當 log 前沿在**兩個**策略上都支配 absolute，才把 `default.yaml` 的 `exposure_band_mode` 改為 `log`；否則保留 absolute，log 留作已驗證 config 選項（套 CLAUDE.md「消融打贏才轉預設」）。

## 9. 風險與取捨

- 「相對容忍度一致」是**假設**，非先驗更優：反方論點是危機時反而想更敏感去風險，而絕對帶本就讓危機大跳動輕鬆穿過。§7 的前沿消融即為裁決此假設而設；未支配則不翻 default。
- 前沿網格值為初始猜測，實跑後可能需微調涵蓋範圍（確保兩 mode 的前沿有重疊的 turnover 區間可比）。
