# Phase 4b-2 — 波動目標策略 + engine 接線 設計文件

> 規格來源：`DEVELOPMENT_GUIDE v1.2.md` §1.4 / §1.6 / §1.7 / §5.2 / §5.4 / §6.2 / §6.3。
> 本文件為 brainstorming 定案，作為 writing-plans 的輸入。日期：2026-07-22。

## 0. 範圍與邊界

把 4b-1 的三個基礎模組（`exposure`/`covariance`/`VolForecaster`）組進策略並接進 engine：
- engine 小改（log-only decision），使 band-blocked 曝險檢查能落診斷而不交易。
- `VolTargetStrategy` 基底（曝險機制，`full`/`voltarget_only` 共用）。
- `voltarget_only`、`full` 策略；`mom_ivol` 遷移到 GARCH σ̂。
- Diagnostics 填 `sigma_p/exposure_*/band_blocked` + 新增 `vol_fell_back`/`garch_params`（決策當下落盤，§6.2）。
- `default.yaml` 的 `vol_model` 翻 `garch_arch`；新增 `risk.corr_window`。

**不做**（→ 4c）：block bootstrap、七策略消融全表、σ*±2% 的實際量測。4b-2 只確保策略正確運作且落盤足以支撐 4c 的量測。

### 4b-2 的 AC
1. `voltarget_only`、`full` 在合成快照上端到端跑得完，曝險路徑與權重守恆正確。
2. band 更新帶三路徑（首次/選擇日無帶、allow、block→log-only）行為與落盤正確；log-only 由變異測試鎖住。
3. `mom_ivol` 改用 GARCH σ̂（與 `full` 同估計器，消融 apples-to-apples）。
4. `vol_fell_back`/`garch_params` 決策當下落盤（非事後）。

### 已具備、不重做
- 4b-1：`portfolio/exposure.py::target_exposure`、`models/covariance.py::{rolling_correlation,build_covariance,portfolio_vol}`（label-aligned，回 DataFrame）、`models/volatility/forecaster.py::VolForecaster`（refit/filter，有上界滾動窗）。
- Strategy pattern：`decide(view, event)`、`DecisionEvent.{SELECTION,EXPOSURE_CHECK}`、`MomentumStrategy` 基底（選標的+absmom+相對權重）、`STRATEGIES` 註冊表。
- `Diagnostics` 欄位 `sigma_p/exposure_raw/exposure_applied/band_blocked` 已存在（None 預設）。
- engine：`run_strategy` 已於決策日呼叫 `strategy.decide(view, event)`，回非 None → pending → 執行。
- runner：`_diagnostics_row` 以 `j()`（JSON sort_keys）攤平 per-asset dict 進 `decisions.parquet`。

## 1. Engine 小改：log-only decision（§1.7「不動作」+ §6.2 落盤）

`backtest/strategy.py` 的 `Decision` 加欄位：

```python
@dataclass(frozen=True)
class Decision:
    target_weights: dict[str, float]
    diagnostics: Diagnostics
    execute: bool = True   # False = 只落診斷、不 rebalance（band-blocked 曝險檢查）
```

`backtest/engine.py::run_strategy` 決策日邏輯改為：**回非 None 的 decision 一律落 decision_row（診斷入帳）；只有 `decision.execute` 才建 pending 並在執行日 rebalance**。log-only 的 `execution_date` 記 None（未執行）。

```
if decision is not None:
    exec_day = clock.execution_day(t)
    if exec_day is not None:
        decision_rows.append({... "execution_date": exec_day if decision.execute else None ...})
        if decision.execute:
            if pending is not None: raise ...  # 既有防呆
            pending = _Pending(target=dict(decision.target_weights), execution_day=exec_day)
```

- **INV 守護**：變異測試——把「blocked 也執行」（強制 execute=True）改回即紅燈（band 的抗換手目的落空、實現波動偏離）。
- `runner._flatten_decisions` 已處理 `execution_date` 為 None（現有 dtype 容 null）；新增 `execute` 欄不需落盤（可由 band_blocked 反推），但 decision_row 仍記 band_blocked。

## 2. `VolTargetStrategy` 基底（曝險機制）

`backtest/strategies/vol_target_base.py`（新檔）。有狀態，引擎每 run 新建實例（比照 bh_spy，不破 INV-6）。

```python
class VolTargetStrategy(Strategy):
    """波動目標曝險機制。full/voltarget_only 共用。子類實作 _select_and_weight。"""
    def __init__(self, cfg):
        super().__init__(cfg)
        self._forecaster = VolForecaster(
            cfg.risk.vol_model, cfg.risk.ewma_lambda, cfg.risk.forecast_horizon, cfg.risk.garch_window
        )
        self._e_current: float | None = None
        self._cache: _RiskyState | None = None   # 上次選擇日的 selected/w_risky/absmom/sigma_hat

    def decide(self, view, event) -> Decision | None: ...
    @abstractmethod
    def _select_and_weight(self, view) -> _RiskyState | None:
        """選擇日：回 (selected, w_risky Σ=1, sigma_hat, absmom, garch_params, fell_back)；
        內部對每檔 forecaster.refit。無合格資產回 None。"""
```

`decide(view, event)` 流程：
- **SELECTION**：`state = self._select_and_weight(view)`；`None` → 回 None（不改狀態）。快取 `state`。曝險用 `e_current=None`（選擇日無帶）。
- **EXPOSURE_CHECK**：`self._cache is None`（首次選擇前）→ 回 None。否則 `state = 快取的 selected/w_risky/absmom`，但 `sigma_hat` 以 `forecaster.filter` 對每檔更新（`garch_params`/`fell_back` 沿用快取）。曝險用 `e_current=self._e_current`。
- **共用尾段**（見 §3 權重公式）：
  1. `R = rolling_correlation(view 報酬窗[selected, 尾端 corr_window])`
  2. `Σ = build_covariance(sigma_hat, R)`；`σ̂_p = portfolio_vol(w_risky, Σ)`
  3. `exp = target_exposure(σ̂_p, σ*, e_min, band, e_current)`
  4. 組最終權重 + cash；填 Diagnostics。
  5. `band_blocked` 為真且事件為 EXPOSURE_CHECK → `execute=False`（log-only，`_e_current` 不變）；否則 `execute=True` 且 `_e_current = exp.exposure_applied`。

`_RiskyState`（dataclass）：`selected, w_risky, sigma_hat, absmom, garch_params, fell_back`。

## 3. `full` 權重公式（§1.6 Step 3 字面）

選擇日 `_select_and_weight`：
1. 動量選 K（`cross_sectional_momentum` + `select_top_k`，比照 `MomentumStrategy`）。
2. 每檔 `sigma_hat[t] = forecaster.refit(t, view 報酬[t])`；記 `garch_params[t]`（`forecaster.last_params`）、`fell_back[t]`（`forecaster.last_fell_back`）。
3. `w_risky = inverse_vol(sigma_hat)`（Σ=1，全 selected）。
4. `absmom = absolute_momentum(...)`（每檔 pass/fail）。

尾段曝險與最終權重：
- `σ̂_p = portfolio_vol(w_risky, Σ)`（**用全 selected 的 w_risky**，Σ=1）。
- `E = exp.exposure_applied`。
- 最終：passing 檔 `w_i = E × w_risky_i`；failing 檔的 `E × w_risky_i` 轉現金。
- `cash = 1 − E × Σ_{pass} w_risky_i`（= (1−E) + E×Σ_{fail} w_risky_i，守恆總和=1）。

`voltarget_only`：`_select_and_weight` 恆回 `selected=["SPY"]`、`w_risky={SPY:1}`、`sigma_hat={SPY:refit}`、`absmom={SPY:True}`（不套 absmom，恆持有）。單資產 → `R=[[1]]`、`σ̂_p=σ̂_SPY`，走同一 covariance/exposure 路徑不特判。

**warmup（重要，決定回測起點）**：warmup 由「首次 GARCH refit 所需的最小史料」與動量需求取大，**不是 `garch_window`**——`garch_window` 只是窗上限（cap），VolForecaster 早期用展開窗（從 warmup 起、達 cap 後滾動）。`voltarget_only.warmup_days = cfg.universe.min_history_days`（252，SPY 有足夠史料 refit GARCH）；`full.warmup_days = max(cfg.signal.momentum_lookback + 1, cfg.universe.min_history_days)`（253）。兩者 ~252-253，回測起點約 2006、**2008 壓力期恆在回測內**（不受 cap 影響）。GARCH 首次 fit 落在 252 根 ≥ `GarchArch._min_obs`(100)。

## 4. `mom_ivol` 遷移到 GARCH σ̂

`mom_ivol`（無波動目標，E=1）**不繼承** `VolTargetStrategy`，維持 `MomentumStrategy`，只把 `_risky_weights` 的 σ̂ 來源從 `estimate_annualized_vol(rolling_std)` 換成一個 `VolForecaster`（`refit` 每檔，只在 SELECTION）。目的：`full` vs `mom_ivol` 的消融只差「曝險層」、vol 估計器一致（apples-to-apples）。`mom_ivol` 無曝險檢查、不需 filter。同時填 `sigma_hat/vol_fell_back/garch_params` 診斷。

## 5. Diagnostics 落盤（§6.2 決策當下記錄）

`backtest/strategy.py` 的 `Diagnostics` 加兩欄（維持既有 per-asset dict 攤平模式）：

```python
    vol_fell_back: dict[str, bool] | None = None      # 每檔 GARCH 是否退回 EWMA
    garch_params: dict[str, dict[str, float]] | None = None  # 每檔 {omega,alpha,beta,nu}；EWMA/fallback 檔為 None
```

`runner._diagnostics_row` 加兩行 `"vol_fell_back": j(diag.vol_fell_back)`、`"garch_params": j(diag.garch_params)`（`j` 為現有 JSON sort_keys 攤平）。

`VolForecaster` 小擴充（4b-2）：加 `last_params(ticker) -> dict[str, float] | None`——GARCH ticker 回 `{omega,alpha,beta,nu}`（自快取的 arch 向量取 index 1-4，或 refit 時另存可讀 dict），EWMA/fallback 回 None。

**原則**：dashboard page-3（GARCH 參數軌跡隨 refit 演變）與 fallback 頻率所需的資料，於決策當下記入 `decisions.parquet`，Phase 7 讀取而非重跑（§6.2）。

## 6. Config 變更

`default.yaml`：
- `risk.vol_model: rolling_std` → **`garch_arch`**（GARCH 轉正為預設 vol 來源）。
- 新增 `risk.corr_window: 252`（滾動相關窗，交易日）。

`config/schema.py`：`RiskConfig` 加 `corr_window: int = Field(ge=2)`（≥2 可算相關；實務 ≫ top_k 保 R 滿秩）。

- `vol_window`（rolling_std 用）保留，`vol_model=garch_arch` 時不使用（EWMA/rolling 基線仍需）。
- 4c 消融可掃 `corr_window ∈ {126, 252}`。

## 7. AC 重新定義（σ*±2%，隔離受測機制）

**背景**：`full` 的絕對動量會把 fail 檔配額轉現金（§1.4），故 2008 這類危機年份組合實現波動遠低於 σ*——這是兩層防禦的**正確行為**，但用「全期實現波動落 σ*±2%」量會不公平判死刑。

重新定義 Phase 4 的「已實現波動落 σ*±2%」AC：
- **`voltarget_only`（無 absmom）= 波動目標的乾淨測試**：全期實現年化波動落 **8%–12%**。第二層不存在，波動目標獨自負責。
- **`full` = 條件式**：僅在「absmom 大致全過」的期間（第二層未介入）量實現波動、落 8%–12%。這隔離受測機制、測得更準。

操作化（門檻定義、期間切法、如何用 `decisions.parquet` 的 absmom + 曝險重建「大致全過」期間）留 **4c**。4b-2 的責任：**落盤足夠**（absmom per-asset、exposure_applied、sigma_p 皆已入 decisions.parquet）使 4c 能重建這些期間。

## 8. 測試（合成快照端到端）

`tests/test_backtest/`、`tests/test_experiments/`：
- **exposure 機制**：合成資料上 `voltarget_only`/`full` 跑完整 clock；斷言曝險路徑合理、`E∈[e_min,1]`、band 三路徑（首次無帶、allow 換 E、block→execute=False 且 band_blocked 落盤）。
- **權重守恆**：`full` 每個執行日權重總和=1（含 cash）；absmom fail 檔配額入現金；`E × Σ_pass w_risky + cash = 1`。
- **log-only 變異測試**：強制 band-blocked 也 execute=True → 換手/實現波動改變即紅燈（鎖 §1.7）。
- **mom_ivol GARCH**：σ̂ 走 VolForecaster（非 rolling_std）；診斷含 `garch_params`/`vol_fell_back`。
- **Diagnostics 落盤**：`decisions.parquet` 含 `sigma_p/exposure_*/band_blocked/vol_fell_back/garch_params`，決策當下值正確。
- **單資產路徑**：`voltarget_only` 的 `σ̂_p = σ̂_SPY`（R=[[1]]）。
- 合成快照沿用 `tests/fixtures/synthetic.py`；GARCH 需足夠長序列（≥ garch_window 級距，或測試用較小 garch_window override）。

## 9. 規格偏離備忘（供 PROGRESS 記錄）

1. **`Decision.execute` 旗標 + log-only decision**：§6.1 無此概念，但 §1.7「帶內不動作」與 §6.2「band_blocked 落盤」兩者需並存——不執行卻要記診斷。engine 分離「落診斷」與「執行」。
2. **新增 `risk.corr_window`（252）**：§1.6 Step 3 的 Σ 需相關 R，其窗長規格未列；4b-1 備忘推遲至此定案。252 偏穩定、≫ top_k 保 R 滿秩。可消融 {126,252}。
3. **`vol_fell_back`/`garch_params` 決策當下落盤**（非 Phase 7）：修正 4b-1 備忘「留 model_details 到 Phase 7」與 §6.2「決策當下記錄」的矛盾；`VolForecaster.last_params` 為此擴充。
4. **σ*±2% AC 條件化**：`voltarget_only` 全期量（乾淨）、`full` 僅在 absmom 大致全過期間量（隔離波動目標層）。因 absmom 轉現金會正確地壓低危機期波動，全期量不公平。實際量測 4c。
5. **`mom_ivol` 遷移到 GARCH σ̂**：Phase 3 用 rolling_std placeholder；改用 VolForecaster 使 full vs mom_ivol 消融只差曝險層。
6. **`vol_model` 預設翻 `garch_arch`**：Phase 3 暫設 rolling_std，GARCH 到位後轉正（§5.2）。

## 10. 不做（YAGNI / 留待後段）

- block bootstrap、七策略消融全表、σ*±2% 實際量測與子期間分析 → 4c。
- GARCH 參數軌跡的 dashboard 視覺化、Decision Explorer UI → Phase 7（4b-2 只負責落盤）。
- DCC/EWMA 相關、ERC → Phase 5（`build_covariance` 介面已預留換 R）。
- `garch_params` 於曝險檢查日（filter，參數未變）重複落盤：僅選擇日 refit 時記；曝險檢查日沿用快取值一併記（決定性、供每列自足），不另優化。
