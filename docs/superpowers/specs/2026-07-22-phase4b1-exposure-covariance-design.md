# Phase 4b-1 — 曝險 / 共變異數 / 波動預報器 設計文件

> 規格來源：`DEVELOPMENT_GUIDE v1.2.md` §1.6 / §1.7 / §5.2 / §5.3 / INV-3。
> 本文件為 brainstorming 定案，作為 writing-plans 的輸入。日期：2026-07-22。

## 0. 範圍與邊界

Phase 4b 依 brainstorming 切為兩段：

- **4b-1（本文件）**：三個基礎模組——`portfolio/exposure.py`（波動目標+帶）、`models/covariance.py`（過渡共變異數，INV-3）、`models/volatility` 的 refit/filter 波動預報器。**各自純/可測，不碰策略與 engine。**
- **4b-2**：把三模組組進 `voltarget_only`/`full` 策略、`mom_ivol` 遷移到 GARCH、Diagnostics 填 `sigma_p/exposure_*/band_blocked`、engine refit/filter 接線、`default.yaml` 翻 `garch_arch`。

**4b-1 硬邊界：只建三個基礎模組與其守護測試，不動 `backtest/`、不改任何策略、不翻 config 的 `vol_model`。**
這讓每個模組能以合成資料獨立驗收，與「接線」分離。

### 4b-1 的 AC（本段驗收）
1. `target_exposure` 對 clip / 帶擋 / 首次無帶 三條路徑正確，純函數。
2. `covariance` 產出的 Σ 恆對稱、PSD、對角線 = 個別變異數（INV-3），並補建 `test_covariance_valid.py` 守護。
3. `VolForecaster` 的 refit 與 filter 對合成序列都算得出合理 σ̂；filter 以固定參數（不跑 MLE）且結果與同參數的直接濾波一致；refit/filter 恆只用尾端 `garch_window` 根（成本 O(cap) 上界，非展開窗）。

### 已具備、不重做
- `models/volatility`（4a）：`fit_volatility`、`annualized_forecast_vol`、`GarchArch`、`Ewma`、`VolatilityModel`、`GarchDegenerateError`。
- `Diagnostics`（`backtest/strategy.py`）欄位 `sigma_p/exposure_raw/exposure_applied/band_blocked` 已存在（None 預設）；4b-1 不碰，4b-2 才填。
- config：`risk.vol_target_annual`(σ*)、`risk.exposure_band`、`risk.exposure_min`(E_min)、`risk.forecast_horizon`(H)、`risk.ewma_lambda`、`schedule.selection_interval`、`schedule.exposure_check_interval` 皆已存在。

## 1. 模組與介面

依賴方向（CLAUDE.md）：`config ← data ← models ← signals/portfolio ← backtest ← experiments`。
`portfolio/exposure.py` 與 `models/covariance.py` 為上游純模組，**收 dict/ndarray/DataFrame，不 import backtest 型別**。

```
portfolio/exposure.py         # 純函數 + ExposureResult
  target_exposure(sigma_p, sigma_star, e_min, band, e_current) -> ExposureResult

models/covariance.py          # Σ 的唯一出口（INV-3）
  rolling_correlation(returns_window) -> (R: np.ndarray, tickers: list[str])
  build_covariance(sigma_hat, R, tickers) -> np.ndarray
  portfolio_vol(w_risky, cov, tickers) -> float

models/volatility/forecaster.py   # 有狀態 refit/filter 預報器
  class VolForecaster
models/volatility/garch_arch.py   # 加固定參數濾波 helper（見 §3）
```

### 1.1 `portfolio/exposure.py`（§1.6 Step 3、§1.7）

```python
@dataclass(frozen=True)
class ExposureResult:
    exposure_raw: float       # σ*/σ̂_p（clip 與帶寬判定前）
    exposure_applied: float   # 實際 E(t)
    band_blocked: bool        # 本次調整是否被更新帶擋下

def target_exposure(
    sigma_p: float, sigma_star: float, e_min: float, band: float,
    e_current: float | None,
) -> ExposureResult: ...
```

- `raw = sigma_star / sigma_p`；`clipped = min(max(raw, e_min), 1.0)`。
- `e_current is None`（首次 / 選擇日）→ `ExposureResult(raw, clipped, band_blocked=False)`。
- 否則（曝險檢查日）：`abs(clipped - e_current) > band` → 套用 `clipped`、`band_blocked=False`；否則沿用 `e_current`、`band_blocked=True`。
- 誠實失敗：`sigma_p <= 0` 或非有限 → `ValueError`（曝險無定義，不靜默）。
- **帶只作用於曝險檢查日**：選擇日由呼叫端（4b-2 策略）傳 `e_current=None` 強制套用（§1.7：選擇日完整重算、換手內生）。

### 1.2 `models/covariance.py`（INV-3，Σ 的唯一出口）

```python
def rolling_correlation(returns_window: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    # 收 date × ticker 的報酬窗，回 (樣本相關矩陣 R, 欄位 ticker 序)。
    # 欄序固定（sorted），供 build_covariance/portfolio_vol 對齊。

def build_covariance(
    sigma_hat: dict[str, float], R: np.ndarray, tickers: list[str]
) -> np.ndarray:
    # 先把 R 投影為合法 PSD 相關矩陣（對稱、PSD、單位對角），再 Σ = D·R·D，
    # D = diag(sigma_hat[tickers 順序])。congruence 保 PSD、R_ii=1 保 Σ_ii=σ_i²。

def portfolio_vol(w_risky: dict[str, float], cov: np.ndarray, tickers: list[str]) -> float:
    # sqrt(w' Σ w)，w 依 tickers 順序取自 w_risky。回年化組合波動 σ̂_p。
```

- `R` 為入選資產報酬滾動窗的樣本相關（窗長由 4b-2 決定，通常 ≥ K 使 R 滿秩、PSD 自然）。
- **INV-3 三性質靠「投影 R 而非投影 Σ」自然同時成立**（避免「投影 Σ 後又強制對角線」互相打架）：
  1. 對 R 對稱化 `(R+R')/2` → `eigh` 截負特徵值（≥ 0）重建 → 重正規化 `R_ij / sqrt(R_ii·R_jj)` 使對角線回 1（仍為合法相關矩陣）。
  2. `Σ = D·R_psd·D`。D 為正對角，congruence 變換保 PSD；`R_ii = 1` ⇒ **對角線恆 = `σ_i²`**（個別變異數，來自 GARCH，精確不受投影微擾）。
- 正常情形（樣本 R 已 PSD、單位對角）投影為近乎恆等；投影只在 R 因窗短/雜訊略微失格時作用。
- 單資產（K=1，如 `voltarget_only`）：R = [[1]]，Σ = [[σ²]]，σ̂_p = σ。退化情形不特判、走同一路徑。
- `sigma_hat` 缺 ticker 或含非正/非有限 → `ValueError`。

### 1.3 `models/volatility/forecaster.py`（refit/filter，§5.2）

有狀態元件，策略每 run 持有一個實例（比照 `bh_spy._decided`，不破 INV-6）：

```python
class VolForecaster:
    def __init__(self, spec: str, ewma_lambda: float, horizon: int, garch_window: int): ...
    def refit(self, ticker: str, returns: pd.Series) -> float:
        # 選擇日：對 returns 尾端 garch_window 根做完整 fit_volatility（含 GARCH→EWMA fallback），
        # 快取 (spec_used, params, fell_back)，回年化 σ̂（annualized_forecast_vol，H 步）。
    def filter(self, ticker: str, returns: pd.Series) -> float:
        # 曝險檢查日：以該 ticker 快取的 params 對 returns 尾端 garch_window 根濾波（GARCH 走 fix()，
        # 不跑 MLE），回年化 σ̂。無快取則退化為 refit。fallback 到 EWMA 的 ticker：filter 重跑 EWMA。
    def last_fell_back(self, ticker: str) -> bool: ...   # 供 4b-2 落盤 model_details
```

- **成本上界由預報器保證**：refit/filter 收「可用完整報酬序列」，**內部一律切到尾端 `garch_window` 根**（`returns.iloc[-garch_window:]`）。每次 refit/filter 成本恆為 **O(garch_window)、不隨回測時間膨脹**——避免展開窗（O(t)）在後期爆炸。切窗集中在此一處，不由呼叫端各自負責。
- 早期史料不足 `garch_window` 時用可用全部（展開窗，252→cap），達 cap 後為固定滾動窗。回測起點由動量 warmup（`momentum_lookback+1`）決定，**不受 garch_window 影響**（2008 壓力期恆在回測內）。
- refit 昂貴（MLE）、filter 便宜（濾波）——§5.2 的成本分離。4c 消融格點若每個決策日都 refit 會慢 ~5×，故此分離為效能必要，非僅忠實度。
- 快取以 `ticker` 為 key；重選（選擇日換入新資產）時對新資產 refit、既有資產覆寫。

### 1.4 Config 新增

`quantcore/config/schema.py` 的 `RiskConfig` 與 `default.yaml` 新增：

```yaml
risk:
  garch_window: 1000    # GARCH 估計滾動窗上限（交易日，~4 年）；界定每次 fit 成本 O(cap)
```

- schema 驗證：`garch_window > 0`，且 `garch_window >= 100`（≥ `GarchArch._min_obs`，保證滿窗時 GARCH 可 fit）。
- 4c 消融可掃 `garch_window ∈ {500, 1000, 1500}`（bias-variance）。
- **不改** `vol_model`（仍 `rolling_std`），4b-2 才翻 `garch_arch`。

## 2. 固定參數 GARCH 濾波 helper（§1.3 filter 的機制）

`filter` 的 GARCH 路徑需要「以已知 params 對新窗算條件變異數/預測，不跑最佳化」。在 `garch_arch.py` 加：

```python
def garch_filter_forecast(params: dict, returns: pd.Series, horizon: int) -> np.ndarray:
    # 以 arch 的 fix(params) 對 returns 濾波（no MLE），回每步變異數（已 ÷100² 還原）。
    # 縮放（×100 / ÷100²）沿用 base 的慣例，確保與 GarchArch.forecast 同尺度。
```

- 用 `arch_model(returns*100, ...).fix([...])` 取得 result，其 `forecast(horizon, method="analytic", reindex=False)` 給 ×100 尺度每步變異數，再 ÷100² 還原。
- **一致性守護**：對同一序列，`garch_filter_forecast(fitted_params, series, H)` 應與 `GarchArch().fit(series).forecast(H)` 數值一致（同 params、同資料 → 同濾波）。此為 §1.3 filter 正確性的錨。

## 3. 測試（§8：合成資料）

`tests/test_portfolio/test_exposure.py`：
- clip 上下界（raw>1 → 1；raw<e_min → e_min）。
- 首次（e_current=None）直接套用、band_blocked=False。
- 帶擋：|clipped−e_current| ≤ band → 沿用舊值、band_blocked=True；> band → 套新值。
- σ̂_p ≤ 0 / 非有限 → ValueError。

`tests/test_models/test_covariance.py`：
- `build_covariance` 產出對稱、PSD（最小特徵值 ≥ −tol）、對角線 = σ̂_i²。
- 給定已知 R 與 σ̂ 手算 Σ 逐元比對。
- `portfolio_vol` 對已知 Σ、w 手算 sqrt(w'Σw)；單資產退化 = σ。
- 刻意餵非 PSD 的近似 R（如雜訊擾動），投影後仍 PSD 且對角線還原正確。

`tests/test_invariants/test_covariance_valid.py`（**補建缺席的 INV-3 守護**）：
- Σ 恆對稱、PSD（最小特徵值 ≥ −tol）、對角線 = 個別變異數 σ_i²。
- mutation-style（有牙齒）：對一個刻意非 PSD 的 R，斷言輸出 Σ 仍 PSD 且對角線精確 = σ_i²——若拿掉 R 的 PSD 投影/單位對角重正規化，此測試轉紅。

`tests/test_models/test_forecaster.py`：
- refit 對合成 GARCH-t 序列回合理年化 σ̂；filter 用固定 params，結果與 `garch_filter_forecast` 一致。
- fallback ticker（造退化）：refit 記 fell_back=True，filter 重跑 EWMA 不拋錯。
- 無快取 ticker 的 filter 退化為 refit。
- **窗上界**：餵一條長度 > garch_window 的序列，斷言 refit/filter 實際只用尾端 garch_window 根——例如以「前段插入極端值、後段正常」的序列，結果應等同「只餵尾端 garch_window 根」，證明前段被切掉、成本 O(cap) 而非 O(t)。

`tests/test_models/test_garch_arch.py`（續加）：
- `garch_filter_forecast(fitted_params, series, H)` 與 `GarchArch().fit(series).forecast(H)` 數值一致（filter 正確性錨）。

## 4. 規格偏離備忘（供 PROGRESS 記錄）

1. **過渡 covariance 用滾動樣本相關**：DCC（§5.3）為 Phase 5，4b 先以樣本相關填 R（比照 Phase 3 的 rolling_std→GARCH placeholder）；`build_covariance`/`portfolio_vol` 介面穩定，Phase 5 只換 R 來源。
2. **補建 INV-3 守護測試 `test_covariance_valid.py`**：CLAUDE.md 列它為 INV-3 守護，但此前不存在（與 INV-4 同）。
3. **VolForecaster 有狀態**：refit/filter 分離為 §5.2 的成本設計，且為 4c 消融格點效能必要（~5×）。有狀態比照 bh_spy，引擎每 run 建新實例，不破 INV-6。
4. **帶只作用於曝險檢查日**（選擇日傳 e_current=None）：§1.7 表格把帶列於曝險檢查日；選擇日完整重算、換手內生。
5. **新增 config `risk.garch_window`（1000）+ 有上界滾動窗**：§5.2 只給 warmup=252（估計下限）未給估計窗上限；展開窗會使後期 refit 成本 O(t) 膨脹（回測+消融格點爆炸）。改為尾端 `garch_window` 根的有上界滾動窗，成本恆 O(cap)。回測起點仍由動量 warmup 決定、不受 cap 影響（2008 恆在內）。

## 5. 不做（YAGNI / 留待後段）

- 策略（`voltarget_only`/`full`）、`mom_ivol` 遷移、Diagnostics 落盤、engine refit/filter 接線、`default.yaml` 翻 garch_arch → 4b-2。
- block bootstrap、七策略消融全表、`full` σ*±2% 驗收 → 4c。
- DCC / EWMA 相關、ERC 權重 → Phase 5（4b-1 的 `build_covariance` 介面為其預留）。
- 滾動相關的窗長參數化與 `mom_ivol` 是否改用 covariance → 4b-2 決定。
