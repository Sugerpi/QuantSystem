# Phase 4a — 波動率模型層 設計文件

> 規格來源：`DEVELOPMENT_GUIDE v1.2.md` §5.1 / §5.2 / §5.4 / §1.6（Step 1）/ INV-4 / §8。
> 本文件為 brainstorming 定案，作為 writing-plans 的輸入。日期：2026-07-22。

## 0. 範圍與邊界

Phase 4 依 brainstorming 切為三段：

- **4a（本文件）**：波動率模型層 + 評估。`base.py`、`garch_arch.py`、`ewma.py`、多步預測、QLIKE/MZ-R² 評估。
- **4b**：曝險模組（`portfolio/exposure.py`）+ `voltarget_only`/`full` 策略 + 接進引擎（含 refit/filter 節奏）+ 把 `default.yaml` 的 `vol_model` 翻成 `garch_arch`。
- **4c**：block bootstrap + 七策略消融全表 + 驗 `full` 已實現波動 σ*±2%。

**4a 的硬邊界：只建模型層與評估，完全不動 `backtest/` engine 與策略。**
`mom_ivol` 維持使用現有 `rolling_std`，直到 4b 才遷移。這讓 4a 的驗收（QLIKE 比較表）能脫離回測獨立跑，並使「模型正確性」與「模型接線」兩件事分開驗證。

### 4a 的 AC（本段驗收）
1. GARCH 與 EWMA 各自對合成/真實序列可 fit + 多步 forecast，數值慣例（INV-4）鎖死。
2. **GARCH vs EWMA 的 QLIKE / MZ-R² 比較表產出**（Phase 4 三個 AC 中的第二個，於 4a 達成）。
3. 已知參數合成序列的估計器回收測試通過（估計器正確，非僅「跑得動」）。

### 已具備、不重做的基礎設施
- `models/volatility/rolling_std.py::annualized_vol`（Phase 3 placeholder）與派發 `estimate_annualized_vol`。4a **不刪**，僅由 `base.py` 體系並列；4b 遷移後 rolling_std 降為消融基線之一。
- `Diagnostics` 的 `sigma_hat` 欄位已存在（Phase 3 由 rolling_std 填）。4a 不改其落盤，僅在 4b 改由 GARCH 供值。

## 1. 模組與介面

依賴方向（CLAUDE.md）：`config ← data ← models ← signals/portfolio ← backtest ← experiments`。
`models/volatility` 為上游純模型層：**收 `pd.Series` 報酬 / 價格，不 import backtest 型別**。

```
models/volatility/
  base.py         # VolatilityModel ABC；×100/÷100 縮放 template method（INV-4 唯一出口）
  garch_arch.py   # GARCH(1,1)-t via arch 套件
  ewma.py         # RiskMetrics λ=0.94（消融基線 + GARCH fallback，同一路徑）
  rolling_std.py  # 保留（Phase 3 placeholder，4b 前 mom_ivol 仍用）
  eval.py         # QLIKE / MZ-R² 純函數
  __init__.py     # 既有 estimate_annualized_vol 保留；新增模型工廠/fallback 封裝
```

### 1.1 VolatilityModel 介面（§5.1）

```python
class VolatilityModel(ABC):
    def fit(self, returns: pd.Series) -> "VolatilityModel": ...
        # 收「報酬」序列（非價格）。base 負責 ×100 縮放後交子類估計。
    def forecast(self, horizon: int) -> np.ndarray: ...
        # 回傳長度 horizon 的「每步變異數」，已還原縮放（報酬變異數尺度）。
    @property
    def standardized_residuals(self) -> pd.Series: ...
        # 供 Phase 5 DCC。4a 只需正確產出，暫無消費者。
    @property
    def params(self) -> dict[str, float]: ...
        # {'omega','alpha','beta','nu',...}，供 model_details 落盤與測試。
```

**縮放 template method（INV-4 的唯一違反點）**：
- `fit(returns)`：base 先 `r_scaled = returns * 100`，呼叫子類 `_estimate(r_scaled)`；估完由 base 檢查 `α+β < 1`（EGARCH 為 |β|<1，v1 不用）。
- `forecast(horizon)`：base 呼叫子類 `_forecast_scaled(horizon)`（×100 尺度的每步變異數），再 `/ 100**2` 還原回報酬變異數尺度後回傳。
- Student-t 分配、參數邊界由子類（GARCH）宣告，base 不假設分配。

子類只實作 `_estimate` 與 `_forecast_scaled`（原始 ×100 尺度）；縮放/慣例檢查絕不外洩到子類，`test_garch_conventions.py` 因此只需守 base。

### 1.2 GARCH(1,1)-t（`garch_arch.py`，§5.2）

- 用 `arch` 套件 `arch_model(r_scaled, mean='Constant', vol='GARCH', p=1, q=1, dist='t')`。
- v1 **固定 GARCH(1,1)-t**，不做 AIC 選規格（§5.2）。GJR 為未來 config 選項，4a 不做。
- `_estimate` 失敗判定 → 拋 `GarchDegenerateError`：
  - 優化器未收斂（arch `convergence_flag != 0`）；或
  - `α + β ≥ 1`（非平穩，多步遞迴會發散）；或
  - 參數落在數值邊界導致 forecast 非有限。
- **決定性**：arch 走 scipy 優化，給定資料與起始值為決定性。固定起始值 / 關閉任何隨機重啟，seed 若有用到走 config 單一 RNG（INV-6）。

### 1.3 EWMA（`ewma.py`，§5.3）

- RiskMetrics `σ²_t = λ·σ²_{t-1} + (1-λ)·r²_{t-1}`，λ=0.94（config `risk.ewma_lambda`，預設 0.94）。
- 多步預測為 flat：EWMA 對 h 步的變異數預測等於當前條件變異數（λ 模型無均值回歸）。
- **雙重身份**：既是 §6.3 消融基線模型，也是 §1.2 GARCH fallback 的目標，兩者共用此一實作。

### 1.4 Fallback 封裝（GARCH 失敗政策）

`__init__.py` 或 `base.py` 提供薄封裝：

```python
def fit_volatility(spec: str, returns: pd.Series) -> FitOutcome:
    # spec='garch_arch'：先試 GARCH；捕捉 GarchDegenerateError → 改用 EWMA。
    # 回傳 FitOutcome(model, fell_back: bool, reason: str | None)
```

- `fell_back` / `reason` 一路帶進 model_details（4b 落盤），可事後統計 fallback 頻率——失敗可審計，不被靜默。
- spec='ewma' / 'rolling_std' 直接建對應模型，無 fallback。

## 2. 多步波動預測（§1.6 Step 1，H=21）

```
σ̂_i(t) = sqrt( (1/H) · Σ_{h=1..H} Var(t+h) ) · sqrt(252)   # H=21，年化
```

- `H` 綁 config（新增 `risk.forecast_horizon: 21`，對齊 `schedule.selection_interval`）。
- GARCH(1,1) 多步變異數用**解析遞迴**（非模擬）：`Var(t+h) = ω' + (α+β)·Var(t+h-1)`（×100 尺度的無條件/遞迴式），base 統一 `/100²` 還原。解析法更快、決定性（符合 INV-6），且 GARCH(1,1) 多步有閉式，無須模擬。
- EWMA 多步為常數（見 1.3）。
- **INV-4 最易錯點**：arch 在 ×100 尺度 forecast，還原需 `/100²`（變異數是二次量）。還原只在 base，子類回傳 ×100 尺度。

## 3. QLIKE / MZ-R² 評估（§5.4）

### 3.1 純損失函數（`models/volatility/eval.py`）

```python
def qlike(realized_var: np.ndarray, forecast_var: np.ndarray) -> float:
    # QLIKE = mean( realized/forecast - log(realized/forecast) - 1 )，對 forecast 偏誤穩健。
def mincer_zarnowitz_r2(realized_var, forecast_var) -> float:
    # realized ~ a + b·forecast 迴歸的 R²。
```

**刻意偏離 §5.4 字面的「metrics.py 需支援」**：`backtest/metrics.py` 位於依賴鏈下游，而 vol 評估是純模型層概念。放 `models/volatility/eval.py` 以維持依賴方向單向（CLAUDE.md：違反即架構錯誤）。記為有理由的規格偏離。

### 3.2 Walk-forward 評估驅動（`experiments/`）

- 對每檔資產，rolling window 每 `selection_interval`（21 日）refit，產 H=21 步預測。
- realized proxy（§5.4）：預測窗對齊之未來 21 日已實現變異數（日報酬平方和 / 21）。
- 對齊 forecast 與 realized，逐資產算 QLIKE 與 MZ-R²。
- **產出**：GARCH vs EWMA 每資產比較表（`comparison.parquet` 或等價），含 fallback 次數欄。這是 4a 的 AC-2 交付物。
- 落地遵循既有 `experiments/tracking.py` 的 manifest/provenance（snapshot_id / git_commit / config_hash，INV-6）。

## 4. Config 變更

`quantcore/config/default.yaml` 的 `risk` 區塊新增（4a 需要）：

```yaml
risk:
  ewma_lambda: 0.94          # §5.3 RiskMetrics
  forecast_horizon: 21       # §1.6 Step 1 的 H，對齊 selection_interval
```

- `vol_model` **不改**（維持 `rolling_std`），4b 才翻 `garch_arch`。
- schema（`config/schema.py`）加對應欄位與驗證（`0 < ewma_lambda < 1`、`forecast_horizon ≥ 1`）。
- 硬性規則：任何參數不得出現在 config 以外（CLAUDE.md）。H、λ 皆入 config。

## 5. 測試（§8：合成資料是關鍵）

`tests/test_models/` 擴充：

1. **已知參數回收**（估計器正確性）：以已知 (ω,α,β,ν) 生成 GARCH-t 序列（足夠長），`garch_arch.fit` 估回真值附近（容差以文獻/樣本量定，如相對誤差 < ~10%，非 parity 的 <1%——parity 是 Phase 6）。
2. **INV-4 慣例**（`test_invariants/test_garch_conventions.py`）：×100 估計 / ÷100² 還原、α+β<1、Student-t。變異測試確認「移除縮放即紅燈」。
3. **Fallback 觸發**：餵會使 GARCH 非平穩/不收斂的序列，斷言 `fit_volatility` 退回 EWMA 且 `fell_back=True`、`reason` 正確。
4. **EWMA 對拍**：λ=0.94 遞迴對 RiskMetrics 定義與手算吻合；多步 flat。
5. **多步預測**：GARCH 解析遞迴對 arch 自身 forecast 吻合；H 步聚合與年化正確；還原尺度正確（值落在合理年化波動區間）。
6. **QLIKE/MZ 純函數**：對已知關係的合成 forecast/realized，QLIKE=0 於完美預測、MZ-R²=1 於 realized=forecast；偏誤時數值方向正確。

合成資料 fixture 置於 `tests/fixtures/synthetic.py`（既有），新增「已知 GARCH 參數生成序列」工具。

## 6. 規格偏離備忘（供 PROGRESS 記錄）

1. **QLIKE/MZ-R² 放 `models/volatility/eval.py` 而非 §5.4 字面的 `metrics.py`**：依賴方向（models 不得依賴 backtest）。
2. **新增 config `risk.ewma_lambda` / `risk.forecast_horizon`**：§7.2 config 範例未列 λ 與 H，但 §5.3/§1.6 需要；避免魔術數字。
3. **多步預測用解析遞迴而非模擬**：更快、決定性（INV-6），GARCH(1,1) 有閉式。
4. **GARCH 失敗退回 EWMA + 標記**（非拋錯中斷、非沿用舊參數）：brainstorming 定案，兼顧誠實（可審計 fallback 頻率）與回測可完成。
5. **4a 不碰 engine/策略；`mom_ivol` 4b 才遷移**：讓模型正確性與接線分開驗證。

## 7. 不做（YAGNI / 留待後段）

- 曝險模組、`voltarget_only`/`full` 策略、engine 接線、refit/filter 節奏 → 4b。
- block bootstrap、七策略消融全表、`full` σ*±2% 驗收 → 4c。
- GJR（槓桿）、AIC 選規格 → 未來 config 選項，消融證明才啟用。
- 手刻 GARCH、parity test → Phase 6。
- DCC 相關模型 → Phase 5（4a 僅確保 `standardized_residuals` 正確產出備用）。
