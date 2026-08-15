# full_gjr 策略設計：GJR-GARCH 波動引擎

日期：2026-08-15
狀態：設計待實作

## 動機

`full` 策略以 GARCH(1,1)-t 估計每檔個別波動 σ̂。GARCH(1,1) 對正負向衝擊對稱反應，
無法捕捉股票報酬常見的「槓桿效應」（負向衝擊比同幅正向衝擊更放大後續波動）。

GJR-GARCH 在條件變異數遞迴中加入非對稱項 γ：

```
σ²_t = ω + α·ε²_{t-1} + γ·ε²_{t-1}·I(ε_{t-1}<0) + β·σ²_{t-1}
```

新增策略 `full_gjr`，除了波動引擎改用 GJR-GARCH 外，其餘（動量選股、inverse-vol
權重、絕對動量、波動目標曝險）與 `full` 完全相同，以便 head-to-head 對比 GJR 是否
改善績效／曝險行為。

## 核心洞察：單一抽換點覆蓋 Step 2 與 Step 3

`full` 的 σ̂ 全部由 `VolForecaster` 產生，有兩個下游用途：

- **Step 2**：每檔 σ̂_i → `inverse_vol` → `w_risky`（見 `full._select_and_weight`）
- **Step 3**：同一批 σ̂_i 作為 `build_covariance` 的對角線 → `portfolio_vol` → σ̂_p(t)
  → `target_exposure` → E(t)（見 `vol_target_base._build_cov` / `_exposure_decision`）

兩者吃的是**同一份 σ̂_i**（Step 3 共變異數的對角線就是 Step 2 的個別 σ̂）。因此只要
把 `full_gjr` 的 forecaster spec 換成 GJR，Step 2 與 Step 3 會**同時**改用新變異數，
不需要在兩處各改一次。這是本設計「小改動」的關鍵。

## 決策（已與使用者確認）

1. **full_gjr 內部強制 GJR**：策略自身固定用 GJR，不依賴 `config.vol_model`。這使
   `full`（標準 GARCH）與 `full_gjr`（GJR）能在同一 experiment suite 直接對比，
   比照 `full_erc` 的「策略即身份」既有模式。
2. **`"gjr_garch"` spec 不加進 config VolModel 列舉**：僅作為 `fit_volatility` /
   `VolForecaster` 認得的內部 spec 字串，由 `full_gjr` 內部指定。`config.vol_model`
   維持現狀（`garch_arch | garch_own | ewma | rolling_std`）。YAGNI。

## 架構變更

### 1. `models/volatility/garch_arch.py`：加入 GJR 能力

- `_build_arch_model(scaled_array, o=0)` 加 `o` 參數（arch 的非對稱階數）。`o=0`＝
  現況標準 GARCH(1,1)（零行為改變）；`o=1`＝GJR。保持 `_estimate` 與濾波函式共用
  單一模型建構來源的既有設計。
- 新增 `GjrGarchArch(GarchArch)` 子類：
  - 類別屬性 `_o = 1`；`_build_arch_model` 呼叫改帶 `o=self._o`。
  - `_estimate` 從 `res.params` **依名稱**取值（不用寫死位置），額外存 `gamma`
    （`gamma[1]`）到 `self._params`。
  - `arch_params` 自然包含 gamma[1]（完整 arch 向量）。
- `garch_filter_forecast(fixed_params, returns, horizon, o=0)` 與
  `garch_filter_residuals(fixed_params, returns, o=0)` 加 `o` 參數，濾波時用
  `_build_arch_model(..., o=o)` 重建**相同 spec** 的模型再 `fix()`（arch `fix()`
  要求參數順序與模型 spec 對齊）。

### 2. `models/volatility/base.py`：平穩性條件納入 γ（INV-4）

- `_check_stationarity` 的 persistence 改為 `α + β + 0.5·γ`（對稱分布下負向指標
  期望值 = 0.5，為 GJR 標準平穩條件）。`γ` 對純 GARCH 以 `params.get("gamma", 0.0)`
  取得預設 0 → 純 GARCH 行為不變（仍是 α+β<1）。

### 3. `models/volatility/__init__.py`：`fit_volatility` 認 `"gjr_garch"`

- `spec == "gjr_garch"`：建 `GjrGarchArch().fit(returns)`，失敗（GarchDegenerateError）
  一樣 fallback EWMA、記 `fell_back=True`（與 `garch_arch` 相同保護傘）。

### 4. `models/volatility/forecaster.py`：`VolForecaster` 支援 GJR spec

- 允許 spec 集合加入 `"gjr_garch"`。
- `_CacheEntry` 需能區分 GJR 與標準 GARCH（例如新增 `arch_o: int` 或以 `kind` 值
  區分），使 `filter()` 濾波時把正確的 `o` 傳給 `garch_filter_forecast/residuals`。
- `last_params` 依 spec 分支取 gamma：GJR 向量為
  `[mu, omega, alpha, gamma, beta, nu]`（位置 1..5），標準 GARCH 為
  `[mu, omega, alpha, beta, nu]`（位置 1..4）。GJR 回傳 dict 額外含 `gamma`。

### 5. `backtest/strategies/full_gjr.py`：新策略

- `class FullGjr(Full)`，`strategy_id = "full_gjr"`。
- 覆寫 `__init__`：`super().__init__(cfg)` 後，以 `spec="gjr_garch"` 重建
  `self._forecaster`（其餘 forecaster 參數沿用 cfg.risk）。
- `_select_and_weight`、`warmup_days`、曝險邏輯全部繼承 `Full` / `VolTargetStrategy`，
  不重寫。
- 於 `strategies/__init__.py` 的 `STRATEGIES` 註冊。

## 測試與驗收

- **INV 全綠**：特別是 `test_invariants/test_garch_conventions.py`（INV-4，含新的
  γ 平穩條件）與 `test_covariance_valid.py`（INV-3）。
- **GJR 模型單元測試**（比照既有 `test_garch_arch.py`）：
  - `GjrGarchArch.fit` 產出含 `gamma` 的 params，α+β+0.5γ<1，Student-t（nu）。
  - `garch_filter_forecast/residuals` 帶 `o=1` 濾波與 refit 結果一致（parity）。
  - 標準 GARCH 路徑（`o=0`）數值與行為不變（回歸保護）。
- **`VolForecaster` GJR 測試**：refit/filter 快取正確、`last_params` 取到 gamma、
  fallback EWMA 正常。
- **`full_gjr` backtest 測試**（比照 `test_full.py`）：策略可跑通、log-only Decision、
  σ̂_i 進 inverse-vol 與 σ̂_p 進曝險皆來自 GJR。
- **消融證據（CLAUDE.md 硬性規則）**：`full` vs `full_gjr` 在同一 snapshot 的對比
  （績效指標 + 曝險行為差異），證明 GJR 帶來可辨識的變化。走研究輕流程
  （scratchpad 腳本）產出，結論記入 `PROGRESS.md`。

## 不變量影響

- **INV-4**：新增 γ 平穩條件；GJR 沿用 ×100 估計／÷100² 還原、Student-t 慣例。
- **INV-3**：σ̂_i 仍為共變異數對角線來源，GJR 只改變數值不改結構，PSD/對稱不受影響。
- **INV-6**：GJR analytic forecast 為決定性遞迴，(config, snapshot_hash, git_commit)
  仍決定輸出。
- INV-1/INV-2/INV-5 不受影響（僅波動數值改變，資料時序與會計恆等式不變）。

## 明確不做（YAGNI）

- 不把 `gjr_garch` 加進 config VolModel（見決策 2）。
- 不改 `garch_own`（手刻 GARCH，未接入 forecaster）。
- 不做 GJR 的參數選規格（p/o/q AIC 選擇）；固定 GJR(1,1,1)-t。
- 不改動 `full` / 其他既有策略行為。
