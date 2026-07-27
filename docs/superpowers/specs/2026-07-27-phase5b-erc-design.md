# Phase 5b — ERC 權重（等風險貢獻）設計文件

> 規格來源：`DEVELOPMENT_GUIDE v1.2.md` §1.6 / §5.3 / §6.3。
> 本文件為 brainstorming 定案，作為 writing-plans 的輸入。日期：2026-07-27。
> 前置：Phase 5a（相關模型層）已完成——Σ = D·R·D 由 `build_covariance` 唯一出口提供。

## 0. 範圍與邊界

Phase 5 = 5a（相關模型層，✅）+ **5b（ERC 權重，本文件）**。

5b 加入 **ERC（等風險貢獻）作為 inverse-vol 的替代權重方案**（§1.6/§5.3）。ERC 需要完整
共變異數 Σ（不只 σ̂）與優化器。**設計決定：ERC 走獨立策略 `full_erc`，不改動已 5a-硬化的
`full` inverse_vol 熱路徑**——ERC 很可能被消融證明無顯著貢獻（§5.3 明言「文獻顯示兩者績效差距
通常很小」），沒理由為它重排已證主路徑。

**5b 硬邊界：**
- `full` 及其 inverse_vol 權重路徑**行為不變**（僅接受純提取重構，見 §1.3）。
- 不新增 config 開關（ERC 是獨立策略，選策略即選權重方案；求解器容差/迭代上限為演算法常數）。
- 不碰選股層、σ̂ 估計層、相關層、曝險機制——`full_erc` 與 `full` **apples-to-apples**，只差權重。

### 5b 的 AC（本段驗收）

1. **ERC vs inverse-vol 消融結論明確寫入報告**（規格 §5.3/§6.3）——「ERC 無顯著貢獻、v1 續用
   inverse-vol」也是合格、甚至更誠實的結論。量測：`full`（inverse_vol）vs `full_erc`（ERC）的
   Sharpe/Calmar 配對 bootstrap CI（複用 4c 機器）+ 平均曝險 + 實現波動。
2. **`erc_weights` 正確性**：合成測試——等相關 Σ 的解析解、風險貢獻確實相等、單資產退化=1.0、
   收斂穩健（長單、Σw=1）。
3. **apples-to-apples 結構守護**：同一 view 上 `full` 與 `full_erc` 的 selected/σ̂/Σ 相等、
   僅 w_risky 不同（消融只隔離權重層由結構保證）。

### 已具備、不重做（Phase 5a / 4b）
- `build_covariance(sigma_hat, R) -> Σ`（INV-3，PSD/對稱/對角=個別變異數）、`portfolio_vol`。
- `CorrelationForecaster` refit/filter、`VolForecaster` refit/filter（+ 標準化殘差快取）。
- `momentum_select`（選股+absmom 單一來源）、`target_exposure`（曝險+帶）、`Diagnostics`/log-only。
- `vol_target_base` 的 `_collect_std_residuals`（殘差新鮮度斷言）、`ticker_returns`。
- Phase 4c 消融引擎（`run_ablation` 掃策略清單）、配對 bootstrap、σ* 量測。

## 1. 模組與介面

依賴方向（CLAUDE.md）：`config ← data ← models ← signals/portfolio ← backtest ← experiments`。

### 1.1 `portfolio/weighting.py` 加 `erc_weights`（純函數）

```python
def erc_weights(cov: pd.DataFrame) -> dict[str, float]:
    """等風險貢獻權重（長單、Σw=1）：找 w 使各檔風險貢獻 w_i·(Σw)_i 相等。

    Spinu(2013) 循環座標下降（CCD）：最小化 f(w)=½ w'Σw − c·Σ ln w_i（c 為等風險預算），
    座標更新解一元二次取正根，迭代至收斂後正規化 w/Σw。長單天然由 ln 障壁保證、決定性（INV-6）。
    """
```

- **演算法（CCD，plan 定死數值細節）**：對每檔 i 固定其餘，令 `β_i = Σ_{j≠i} Σ_ij w_j`，解
  `Σ_ii w_i² + β_i w_i − c = 0` 取正根 `w_i = (−β_i + sqrt(β_i² + 4 Σ_ii c)) / (2 Σ_ii)`；
  掃完所有 i 為一輪，迭代至 `‖Δw‖ < tol` 或達 `max_iter`；最後 `w /= Σw`。
- 常數 `_ERC_TOL`、`_ERC_MAX_ITER`、初始 `w0`（如 1/n 或 inverse-vol 暖啟）為 module 常數
  （演算法常數，比照 DCC 的 `_A_START`/GARCH 的 `_min_obs`，不進 config）。
- 依賴方向：只收 `pd.DataFrame`（label-aligned Σ）、回 dict，不 import backtest 型別。
- **正確性/收斂守護**：Σ 由 `build_covariance` 已保證 PSD+對稱+正對角（ERC 的 CCD 對正定 Σ 收斂）；
  非有限或非正定的極端輸入誠實拋錯（比照 `inverse_vol`/`portfolio_vol` 的誠實失敗）。
- 單資產（K=1）：直接回 `{ticker: 1.0}`（β=0、退化解，走同一路徑或明確特判，plan 定）。

### 1.2 新策略 `backtest/strategies/full_erc.py`

`FullErc`——與 `Full` apples-to-apples，只差權重層。**獨立 `decide()`**（不呼叫 base 的
inverse_vol decide()，避免 corr 被 double-refit / cadence 亂），但**共用 base 的抽取 helper**
（§1.3）與所有既有純元件：

```
FullErc.decide(view, event)：
  選擇日 SELECTION：
    sel = momentum_select(view, cfg)              # 同 full（單一來源）
    if sel is None: return None
    σ̂, garch_params, fell_back = forecast_selected(forecaster, view, sel.selected)  # refit
    cov = self._build_cov(view, sel.selected, event)   # 殘差→corr.refit→build_covariance
    w_risky = erc_weights(cov)                    # ← 與 full 唯一差異
    state = RiskyState(..., w_risky=w_risky, sigma_hat=σ̂, ...)
    self._cache = state; e_current = None
  曝險檢查日 EXPOSURE_CHECK：
    if self._cache is None: return None
    state = self._refilter(view, self._cache)     # 更新 σ̂（filter），沿用快取 w_risky
    cov = self._build_cov(view, state.selected, event)  # corr.filter
    e_current = self._e_current
  return self._exposure_decision(state, cov, e_current)   # 共用尾段（§1.3）
```

- `strategy_id = "full_erc"`；`warmup_days` 同 `Full`。
- 有狀態（forecaster/corr/e_current/cache），引擎每 run 新建（比照 full，不破 INV-6）。
- 曝險檢查日沿用選擇日的 ERC 權重（維持「權重選擇日定、期內只動曝險」語意，同 base）。

### 1.3 `vol_target_base` 抽兩個「行為不變」的共用 helper

從現有 `VolTargetStrategy.decide()` **純提取**（不改 inverse_vol 行為，現有測試守）：

```python
def _build_cov(self, view, selected, event) -> pd.DataFrame:
    """殘差 → corr.refit(選擇日)/filter(曝險檢查日) → build_covariance。每次決策呼叫一次。"""
    std_resid = self._collect_std_residuals(view, selected)
    R = self._corr.refit(std_resid) if event is DecisionEvent.SELECTION else self._corr.filter(std_resid)
    return build_covariance(<sigma_hat by selected>, R)

def _exposure_decision(self, state, cov, e_current) -> Decision:
    """σ̂_p=portfolio_vol → target_exposure → 最終權重 + 現金 + Diagnostics + log-only Decision。"""
    ...（現有 decide() 尾段原樣搬入，含 band_blocked→execute、_e_current 更新）
```

- `Full`/`voltarget_only` 的 `decide()` 改為：`state=_select_and_weight → cov=_build_cov(...) →
  return _exposure_decision(state, cov, e_current)`。**inverse_vol 的 w_risky 仍在 `_select_and_weight`
  早算，順序與行為不變**——這只是把尾段包成方法，非重排權重。
- `_build_cov` 需要 σ̂（`state.sigma_hat`）；`FullErc` 在呼叫 `_build_cov` 時 σ̂ 已由 forecast_selected
  算好（選擇日）或 _refilter（曝險檢查日）——與 base 一致。簽名細節（傳 state 或 sigma_hat）plan 定。
- **關鍵：corr.refit/filter 只在 `_build_cov` 內呼叫一次**，full 與 full_erc 各自的 decide() 都只
  呼叫 `_build_cov` 一次 → cadence 正確、不 double-refit。

## 2. Config

**不新增 config 欄位。** `full_erc` 註冊進 `STRATEGIES`（`backtest/strategies/__init__.py`）。
ERC 求解器常數（tol/max_iter/w0）為 module 常數。消融以「策略清單含 full_erc」表達，非 config 開關。

## 3. 消融與 AC 量測（5b）

複用 Phase 4c：`run_ablation` 的策略清單加入 `full_erc`；配對 bootstrap 已支援 full vs 其他策略。

- **權重方案軸**：`full`（inverse_vol）vs `full_erc`（ERC）的 Sharpe/Calmar 配對 bootstrap CI
  （full 為 anchor，full_erc 為對照）+ 平均曝險 + 實現波動。相關模型固定為預設（ewma）。
- **結論寫入 PROGRESS/報告**：無論顯著與否明確陳述——§5.3 明言「ERC 無顯著貢獻也合格」。
  預期（規格）：ERC 對 inverse-vol 無顯著績效優勢 → v1 續用 inverse-vol、ERC 留研究/選項。
- **附帶觀察（次要，不擴大 AC）**：ERC 讓相關結構**首次影響配置本身**（inverse_vol 下相關只
  影響曝險純量）；可順帶記 DCC 在 ERC 下是否比在 inverse_vol 下更有作用，作為研究章節素材。
- 以 `requires_snapshot` 本機閘門守護（比照 5a）。

## 4. 規格偏離備忘（供 PROGRESS 記錄）

1. **ERC 走獨立策略 `full_erc` 而非 config 開關**：§5.3 說「作為 config 選項」，但為不動已 5a-硬化的
   inverse_vol 熱路徑（ERC 很可能被消融證明無貢獻），改以獨立策略隔離；選策略即選權重方案，語意等價
   且更安全。base 僅純提取尾段/cov-building 為共用 helper（行為不變）。
2. **無新 config 欄位**：ERC 求解器常數為演算法常數（比照 DCC `_A_START`）。
3. **CCD 而非 scipy 優化器**：長單 ERC 的 CCD 收斂穩健、無優化器失敗模式、決定性、無外部依賴
   （§5.3「inverse-vol 沒有優化器收斂失敗模式」的精神——ERC 也選最穩健的解法）。

## 5. 測試（§8：合成資料 + 不變量）

`tests/test_portfolio/test_weighting.py`（續加）：
- `erc_weights` 對**等相關等波動 Σ** → 等權（解析解，逐元比對）。
- 對已知 Σ，驗**風險貢獻相等**：`rc_i = w_i·(Σw)_i` 全檔相等（至 tol）。
- **不等波動**：高波動檔權重較低（inverse-risk 方向正確）。
- 單資產 Σ=[[σ²]] → {t:1.0}。
- 長單 + Σw=1 恆成立；非有限/非正定 Σ 誠實拋錯。
- 決定性：同 Σ 兩次呼叫位元級相同（INV-6）。

`tests/test_backtest/test_full_erc.py`：
- `full_erc` 選擇日決策：權重和=1、σ̂_p>0、band/log-only 行為同 full。
- **apples-to-apples 回歸**：同一 view 上 `Full` 與 `FullErc` 的 `selected`/`sigma_hat`/`Σ` 相等、
  僅 `w_risky` 不同（任一份選股/σ̂/相關序列漂移即紅燈——取代 Phase 4「full vs mom_ivol 共用選擇層」）。
- 曝險檢查日沿用選擇日 ERC 權重（不重算權重、只更新 σ̂/曝險）。

`tests/test_backtest/`（既有 full/voltarget 測試）：
- base 尾段/cov-building 提取為 helper 後，`full`/`voltarget_only`/`mom_ivol` 行為不回歸（既有測試綠）。

`tests/test_experiments/test_phase5b_ac.py`（`requires_snapshot`）：
- `full` 與 `full_erc` 皆跑完整回測；產出 full vs full_erc 配對 bootstrap；實現波動皆落 σ*±2%。

## 6. 不做（YAGNI）

- **risk.weighting config 開關**：改用獨立策略（§4-1）。
- **ERC 的風險預算非等權變體（risk budgeting）**：v1 只做等風險貢獻（equal RC）。
- **scipy/外部優化器**：CCD 手寫足夠且更穩健。
- **mom_ivol 加 ERC**：mom_ivol 無 cov 層（無曝險/相關），ERC 無通道，維持 inverse_vol。
- **改 voltarget_only**：K=1 時 ERC≡inverse_vol≡100%，不新增 voltarget_erc。
- **Phase 6/7 內容**：手刻 GARCH、dashboard。
