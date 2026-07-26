# Phase 5a — 相關模型層（DCC / EWMA-corr）設計文件

> 規格來源：`DEVELOPMENT_GUIDE v1.2.md` §1.6 / §5.3 / §5.4 / INV-3 / INV-6。
> 本文件為 brainstorming 定案，作為 writing-plans 的輸入。日期：2026-07-26。

## 0. 範圍與邊界

Phase 5（DCC + ERC）依 brainstorming 切為兩段：

- **5a（本文件）**：相關模型層——`models/correlation/`（base + dcc + ewma_corr）、
  `CorrelationForecaster`（refit/filter，鏡射 `VolForecaster`）、標準化殘差管線、
  `covariance.py` 升為唯一出口且 R 依 `corr_model` 派發。**把 R 的來源從過渡的樣本相關換成
  DCC / EWMA-corr，並做 DCC vs EWMA 消融。**
- **5b**：ERC 權重選項（`portfolio/weighting.py` + 優化器）、接進策略、ERC vs inverse-vol 消融。

**5a 硬邊界：只換「相關矩陣 R 怎麼來」，不碰權重層。** 權重仍是 inverse-vol（§1.6 Step 2）。
相關只透過 `portfolio_vol → σ̂_p → target_exposure` 影響**曝險純量**，不影響 selected/w_risky。
ERC（讓相關影響配置本身）留給 5b。

### 5a 的 AC（本段驗收）

1. **DCC vs EWMA 消融結論明確寫入報告**（規格 §5.3 的 Phase 5 AC）——
   「DCC 無顯著貢獻」也是合格、甚至更誠實的結論。量測兩軸：
   - 風險預測品質：`full`/`voltarget_only` 各跑 `{ewma, dcc-fixed, dcc-reestimate}`，
     量**已實現組合年化波動 vs σ*=10% 的追蹤誤差**（§5.4，vol targeting 的直接成績單）。
   - 最終績效：Sharpe/Calmar 配對 bootstrap CI（複用 Phase 4c 機器）。
2. **手寫 DCC 正確性**：合成回收測試（模擬已知 (a,b,R̄) 的 DCC(1,1) 過程 → QMLE 回收
   參數到容差內）通過；相關矩陣不變量守護（R_t 恆對稱/PSD/單位對角、a+b<1）綠。
3. `corr_model` 由 config 真正派發：`dcc` 與 `ewma` 兩條路徑都跑得完整回測、產出診斷。

### 已具備、不重做

- `GarchArch.standardized_residuals` / `Ewma.standardized_residuals`（4a）：回 `r_t/σ_t` 帶
  `DatetimeIndex`，定義在 GARCH 與 EWMA fallback 資產間一致——**DCC 唯一輸入 4a 已備好**。
- `models/covariance.py`（4b-1）：`build_covariance`(Σ=D·R·D，INV-3 投影)、`portfolio_vol`。
  介面穩定，5a 只換上游 R 來源。
- `VolForecaster`（4b-1）：refit/filter 分離、有上界滾動窗。5a 擴充其快取殘差（見 §1.4）。
- config：`corr_model`（`dcc|ewma`，schema 已有型別）、`corr_window`、`ewma_lambda`、
  `garch_window`、`schedule.selection_interval`(21)/`exposure_check_interval`(5) 皆已存在。
- Phase 4c 的 bootstrap / 消融引擎 / σ* 量測機器：5a 消融直接複用。

## 1. 模組與介面

依賴方向（CLAUDE.md）：`config ← data ← models ← signals/portfolio ← backtest ← experiments`。
`models/correlation/` 為上游純模組，**收 pd.DataFrame（date×ticker 標準化殘差）、回 pd.DataFrame（R），
不 import backtest 型別**。

```
models/correlation/
  base.py         共用遞迴+正規化+PSD 守護；CorrelationModel 契約
  dcc.py          DCC(1,1) 兩步 QMLE
  ewma_corr.py    RiskMetrics λ=0.94（DCC 必須打敗的基線，§5.3）
models/volatility/forecaster.py   VolForecaster 擴充：快取標準化殘差（§1.4）
models/correlation/forecaster.py  CorrelationForecaster：refit/filter，鏡射 VolForecaster
models/covariance.py              R 來源依 corr_model 派發（rolling_correlation 退役）
backtest/strategies/vol_target_base.py   接線：改用 CorrelationForecaster
```

### 1.1 `models/correlation/base.py`（R 的合法性單一出口）

所有相關模型共用「遞迴 → 正規化 → PSD 守護」，封在一處，呼叫端拿不到非法 R：

```python
def normalize_to_correlation(Q: np.ndarray) -> np.ndarray:
    # R = diag(Q)^{-1/2} · Q · diag(Q)^{-1/2}；對稱化；截負特徵值後重正規化對角線=1。
    # 保證輸出對稱、PSD、單位對角（INV-3 在 R 這一層就成立，非只靠 covariance 投影）。
```

- `_project_to_psd_correlation`（現於 covariance.py）移來此處共用——covariance 的 Σ 投影與
  correlation 的 R 正規化本是同一數學，統一單一出口。
- 單資產（K=1，如 `voltarget_only`）：R=[[1]]，遞迴/正規化走同一路徑不特判。

### 1.2 `models/correlation/dcc.py`（DCC(1,1) 兩步 QMLE）

Step 1 的單變量 σ_t 已由既有 GARCH 提供（標準化殘差為輸入）；本模組只做 Step 2：

```python
@dataclass(frozen=True)
class DccParams:
    a: float
    b: float
    q_bar: np.ndarray        # 標準化殘差的（shrink 後）樣本相關 Q̄

def estimate_dcc(std_resid: pd.DataFrame, fixed_ab: tuple[float, float]) -> DccParams:
    # Q̄ = shrink(sample_corr(std_resid))；QMLE 估 (a,b)：
    #   scipy.optimize.minimize，約束 a≥0, b≥0, a+b<1−eps。
    #   QMLE 目標 = DCC 準似然（僅相關部分：Σ_t log|R_t| + ε_t' R_t^{-1} ε_t）。
    # QMLE 不收斂 / a+b≥1 / 非有限 → 退回 fixed_ab（誠實 fallback，比照 4a GARCH→EWMA）。

def dcc_recursion(std_resid: pd.DataFrame, params: DccParams) -> np.ndarray:
    # Q_t = (1−a−b)·Q̄ + a·ε_{t−1}ε_{t−1}' + b·Q_{t−1}，Q_0 = Q̄。
    # 回最後一日的 R_t = normalize_to_correlation(Q_T)。
```

- **對稱化、Q̄ 的 shrinkage、R 正規化全封在模組內**（§5.3；§2.1 反例表「DCC 對稱化忘了就爆」→
  呼叫端無法拿到非法矩陣）。
- Q̄ shrinkage：向單位對角收縮（Ledoit-Wolf 式的輕量版，避免小樣本 Q̄ 病態）；係數入 config 或
  用固定保守值，plan 階段定。
- 決定性（INV-6）：`scipy.optimize` 給定起點與資料決定性；QMLE 起點固定（如 fixed_ab 或
  (0.02, 0.95)），不吃亂數。

### 1.3 `models/correlation/ewma_corr.py`（基線，§5.3）

```python
def ewma_correlation(std_resid: pd.DataFrame, lam: float) -> np.ndarray:
    # S_t = (1−λ)·ε_{t−1}ε_{t−1}' + λ·S_{t−1}，S_0 = sample_cov(std_resid)。
    # 回 normalize_to_correlation(S_T)。無待估參數（λ 固定 0.94，RiskMetrics）。
```

- **DCC 必須在消融中打敗它**（風險預測品質 + 最終績效兩維度），否則 v1 出貨用 EWMA、
  DCC 留研究章節（§5.3）。這是「複雜度自證其值」最重要的一次應用。

### 1.4 標準化殘差管線（複用 VolForecaster，不重估）

DCC/EWMA-corr 的輸入 = selected 資產的標準化殘差矩陣（date×ticker，按日交集對齊）。
**不讓相關層重跑一次單變量 GARCH**（貴），改為擴充 `VolForecaster` 在 refit/filter 時
一併快取殘差序列：

```python
class VolForecaster:
    def last_standardized_residuals(self, ticker: str) -> pd.Series: ...
    # refit：fit 後存 model.standardized_residuals（帶 DatetimeIndex）。
    # filter：以 fix() 濾波後同樣導出標準化殘差並更新快取。
```

- `vol_target_base` 對 selected 逐檔取殘差序列 → 組 date×ticker 矩陣（`dropna` 取交集日）→
  餵 `CorrelationForecaster`。矩陣列數 ≤ garch_window（殘差只在 fit 窗上存在）。
- fallback 到 EWMA 的資產：`Ewma.standardized_residuals` 同樣定義（4a 已保證一致），無縫混入。

### 1.5 `models/correlation/forecaster.py`（refit/filter，鏡射 §5.2）

DCC 與 GARCH 同構——**貴的估計（(a,b) QMLE）週期性做、便宜的濾波（Q_t 遞迴）每次決策做**：

```python
class CorrelationForecaster:
    def __init__(self, corr_model, ewma_lambda, refit_interval, fixed_ab): ...
    def refit(self, std_resid: pd.DataFrame, when: date) -> pd.DataFrame:
        # 選擇日呼叫。dcc + reestimate 模式且距上次 refit ≥ refit_interval 交易日：
        #   estimate_dcc（QMLE (a,b) + Q̄），快取。否則沿用快取 (a,b)、僅重算 Q̄。
        # dcc + fixed 模式（refit_interval==0）：(a,b)=fixed_ab，僅算 Q̄。
        # ewma：無 (a,b)，直接算 R。
        # 一律回當日 R_t。
    def filter(self, std_resid: pd.DataFrame, when: date) -> pd.DataFrame:
        # 曝險檢查日：沿用快取 (a,b, Q̄)，僅把 Q_t 遞迴推進到當日，回 R_t（不重估）。
```

- **資產集會輪動**（每 21 日重選）：Q̄ 為「當下 selected 殘差」的樣本相關，故每次選擇日重算 Q̄；
  (a,b) 才受 `refit_interval` 節奏管轄（63 日 = 3×selection_interval 才重跑 QMLE）。
  此「Q̄ 每選重算、(a,b) 週期重估」的拆法明確記為 5a 的建模決定（見 §4-2）。
- **有狀態**，策略每 run 持有一實例（比照 `VolForecaster`/`bh_spy`，引擎每 run 新建，不破 INV-6）。
- 遞迴每次決策在窗上重算（給定 (a,b,Q̄,矩陣) 決定性）→ INV-6；成本 O(window·K²) 便宜。

### 1.6 `models/covariance.py`（R 來源派發）

`rolling_correlation` **退役出生產路徑**（Phase 4 過渡 placeholder，§5.3 基線改為 EWMA-corr）。
`build_covariance`/`portfolio_vol` 不動。R 由策略持有的 `CorrelationForecaster` 依 `corr_model` 提供。
`covariance.py` 拿掉「過渡」docstring；`_project_to_psd_correlation` 移入 `correlation/base.py` 共用。

### 1.7 接線：`backtest/strategies/vol_target_base.py`

[vol_target_base.py:102-104](quantcore/backtest/strategies/vol_target_base.py:102) 現為
`window = _selected_returns_window(...)` → `R = rolling_correlation(window)`。改為：

```python
std_resid = self._collect_std_residuals(view, state.selected)   # date×ticker（§1.4）
R = self._corr_forecaster.refit(std_resid, when) if SELECTION else \
    self._corr_forecaster.filter(std_resid, when)
cov = build_covariance(state.sigma_hat, R)   # 不變
```

- 選擇日 refit、曝險檢查日 filter，與 `VolForecaster` 的 refit/filter 節奏同步。
- `full` 與 `voltarget_only` 皆自動受惠（共用基底）；`voltarget_only`（K=1）R=[[1]]，DCC/EWMA 皆退化為純量、與現況一致。

## 2. Config 新增 / 變更

`quantcore/config/schema.py` `RiskConfig` 與 `default.yaml`：

```yaml
risk:
  corr_model: ewma            # 【變更】dcc→ewma：DCC 未經消融證明前，預設用已證的簡單基線（§5.3 紀律）
  dcc_refit_interval: 63      # 【新增】>0 = 每 N 交易日重估 (a,b)；0 = 固定模式（不估）
  dcc_fixed_ab: [0.01, 0.96]  # 【新增】固定模式的 (a,b)（舊系統值）；亦為重估不收斂時 fallback
```

- schema：`dcc_refit_interval: int ≥ 0`；`dcc_fixed_ab: tuple[float,float]`，各 ∈ [0,1) 且 a+b<1。
- **`corr_model` 預設翻 `ewma`**（D1）：接線後預設路徑改由已證基線走，DCC 若在 5a 消融勝出再翻回。
- **`rolling` 不入 `CorrModel`**（D2）：`Literal["dcc","ewma"]` 維持；rolling 退役不作為選項。
- 消融維度：`corr_model ∈ {ewma, dcc}` × `dcc_refit_interval ∈ {0, 63}`（fixed vs reestimate）。

## 3. 消融與 AC 量測（5a）

複用 Phase 4c：`experiments/ablation.py` 掃 `corr_model`/`dcc_refit_interval`；
`experiments/vol_target_ac.py` 量已實現波動 vs σ*。

- **風險預測品質軸**：對 `full` 與 `voltarget_only`，比較三配置的「已實現組合年化波動 − σ*」
  追蹤誤差（RMSE）。DCC 若更準，追蹤誤差應更小（相關預測更好 → σ̂_p 更準 → 曝險更貼目標）。
- **最終績效軸**：`full` 三配置的 Sharpe/Calmar 配對 bootstrap CI（full-dcc vs full-ewma）。
- **結論寫入 PROGRESS/報告骨架**：無論顯著與否，明確陳述——§5.3 明言「無顯著貢獻也合格」。
- 以 `requires_snapshot` 本機閘門守護（比照 Phase 4 AC），CI 無快照乾淨 skip。

## 4. 規格偏離備忘（供 PROGRESS 記錄）

1. **手寫 DCC（無可信 Python 套件）**：`arch` 僅單變量 GARCH、無 DCC。DCC 第二步（(a,b) QMLE +
   Q_t 遞迴 + R 正規化）自寫。單變量 GARCH 仍用 arch（Phase 4）。此為缺替代品，非 Phase 6 的
   手刻學習里程碑。正確性以合成回收 + 不變量建立信心（無 arch 那樣的 parity 參照）。
2. **Q̄ 每選重算、(a,b) 週期重估**：資產集每 21 日輪動，Q̄（selected 殘差樣本相關）必隨之重算；
   `dcc_refit_interval`(63) 只管轄 (a,b) 的 QMLE 重跑節奏。文獻標準 DCC 為固定宇宙，此為
   對輪動宇宙的明確適配。
3. **`corr_model` 預設翻 `ewma`（D1）**：Phase 4 default 為 `dcc` 但從未接線（宣告未生效）。
   5a 接線後依「DCC 須先打敗 EWMA」紀律預設用基線。
4. **`rolling_correlation` 退役（D2）**：Phase 4 過渡 placeholder；§5.3 基線為 EWMA-corr。
   保留 `{dcc, ewma}` 兩選項乾淨。
5. **`dcc_refit_interval` 單鍵收攏 fixed/reestimate（D3）**：`>0` 重估、`0` 固定，消融掃單一參數。
6. **標準化殘差複用 VolForecaster**：擴充其快取殘差，避免相關層重跑單變量 GARCH（成本、且確保
   vol 與 corr 用同一組殘差、一致）。

## 5. 測試（§8：合成資料 + 不變量）

`tests/test_models/test_correlation.py`：
- `normalize_to_correlation` 對非 PSD 輸入回合法相關（對稱/PSD/單位對角）；已合法者近乎恆等。
- `dcc_recursion` 對已知 (a,b,Q̄) 手算前幾步 Q_t/R_t 逐元比對。
- `ewma_correlation` 對已知 λ 手算前幾步比對；λ→1 趨近靜態樣本相關。
- 單資產（K=1）：DCC/EWMA 皆回 [[1]]。

`tests/test_models/test_dcc_recovery.py`（**合成回收，正確性核心**）：
- 以固定 seed 模擬 DCC(1,1) 過程（已知 a*,b*,R̄*，多變量 t 或高斯）→ `estimate_dcc` 回收
   (a,b) 相對誤差 < 容差（如 10–15%，QMLE 於有限樣本的合理界，plan 定）。
- QMLE 不收斂 / a+b≥1 的退化輸入 → 誠實退回 fixed_ab 並可標記（不拋錯中斷回測）。

`tests/test_invariants/test_covariance_valid.py`（**擴充**）：
- 新增：R 來自 DCC/EWMA 遞迴時，`build_covariance` 的 Σ 仍恆對稱/PSD/對角線=σ_i²（INV-3）。
- mutation-style：拿掉 `normalize_to_correlation` 的 PSD 截斷 → 對刻意病態輸入轉紅（有牙齒）。

`tests/test_models/test_correlation_forecaster.py`：
- refit/filter 對合成殘差矩陣回合法 R；filter 沿用快取 (a,b) 不重估（以「refit 後改資料只跑
   filter，(a,b) 不變」驗證）。
- reestimate 模式：距上次未達 refit_interval 交易日 → (a,b) 沿用；達到 → 重估。
- fixed 模式（refit_interval=0）：(a,b) 恆 = fixed_ab，永不 QMLE。
- 資產集輪動：selected 換檔後 Q̄ 重算、維度隨新集合。

`tests/test_config.py`（續加）：
- `dcc_refit_interval ≥ 0`、`dcc_fixed_ab` a+b<1 的驗證；`corr_model` 預設為 `ewma`。

`tests/test_experiments/`（消融端到端，`requires_snapshot`）：
- `corr_model=dcc` 與 `=ewma` 各跑完整 mini 回測、產出 decisions/metrics，σ̂_p 有限、Σ 合法。

## 6. 不做（YAGNI / 留 5b 或後續）

- **ERC 權重 + 優化器** → 5b（相關影響「配置」的通道）。5a 權重仍 inverse-vol。
- **相關預測的獨立 QLIKE/多變量損失表**：5a 的風險品質軸以「波動目標追蹤誤差」量（§5.4 直接、
   且已有機器）；多變量相關 QLIKE 若 5b/報告需要再補，非 5a 必需。
- **DCC 的 GJR / 非對稱相關（DECO、cDCC 變體）**：v1 固定 DCC(1,1)，比照 GARCH 固定 (1,1)-t。
- **手刻單變量 GARCH** → Phase 6。
- **`mom_ivol` 是否也吃相關**：`mom_ivol` 無曝險層、不用 σ̂_p，相關對它無通道，維持不變。
