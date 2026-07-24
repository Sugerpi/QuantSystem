# Phase 4c — Block Bootstrap + 七策略消融 + AC 量測 設計文件

> 規格來源：`DEVELOPMENT_GUIDE v1.2.md` §6.3 / §6.4 / §7.3 / §9 Phase 4 AC / INV-6。
> 本文件為 brainstorming 定案，作為 writing-plans 的輸入。日期：2026-07-22。

## 0. 範圍與邊界

4c 是 Phase 4 的最後一段，**收割全部 AC**：

- 先還 4b-2 的 backlog：抽 `momentum_select` 共用，使 full/mom_ivol/mom_only 的選擇一致由**結構**保證。
- `metrics.py` 加 stationary block bootstrap（CI + **配對差異檢定**）與平均曝險。
- 子期間分析（2005-2009 / 2010-2019 / 2020-）。
- σ*±2% AC 量測（`voltarget_only` 全期；`full` 條件式日層級子集）。
- 七策略 × §7.3 參數格消融全表（真實快照，本機閘門）。

**不做**：Phase 5（DCC/ERC）、Phase 6（手刻 GARCH）、Phase 7（dashboard）。4c 只產出資料與表，視覺化留 Phase 7。

### 4c 的 AC（即 Phase 4 剩餘 AC）
1. **七策略消融全表產出**（§9）——含 bootstrap CI 與 `full` vs 各消融版的配對差異檢定。
2. **已實現波動落 σ*±2%**（條件化定義，見 §4）——`voltarget_only` 全期落 8-12%；`full` 在 absmom 大致全過的日子落 8-12%。
3. 子期間分析產出（§6.4）。

### 已具備、不重做
- `backtest/metrics.py`：`annualized_return`/`sharpe`/`sortino`/`max_drawdown`/`calmar`/`annualized_turnover`/`compute_metrics`（**無 bootstrap、無平均曝險**）。
- `experiments/ablation.py`：`run_ablation(base_cfg, snapshot, strategy_ids, param_grid, out_root, label)` 通用引擎——建 cells（baseline + 一次動一參數）、`_evaluate` 以全策略 warmup 最大值建單一 `EventClock`（**所有策略同一活躍期間，消融 apples-to-apples**）、輸出 `comparison.parquet` + provenance manifest、單格驗證失敗只記錄不拖垮整批。
- run 產物：`nav.parquet`(date/strategy_id/nav/turnover/cost)、`weights.parquet`(date/strategy_id/ticker/weight)、`decisions.parquet`（含 event/absmom/w_risky/sigma_p/exposure_*/band_blocked/vol_fell_back/garch_params，dict 欄為 JSON 字串）。
- 七策略齊備並註冊；`vol_model` 預設 `garch_arch`。

## 1. 先還 backlog：抽 `momentum_select` 共用

**問題**（4b-2 holistic review）：選標的序列（eligible→動量→取 K→absmom）在 `MomentumStrategy.decide` 與 `Full._select_and_weight` 各一份，只靠交叉引用註解 + 等價回歸測試守。消融是本階段的科學交付物，一致性應由結構保證。

新增 `backtest/strategies/momentum_selection.py`：

```python
@dataclass(frozen=True)
class MomentumSelection:
    eligible: list[str]
    scores: dict[str, float]      # 全體合格資產的 12-1 分數（§6.2「不只前 K」）
    selected: list[str]
    absmom: dict[str, bool]       # 入選資產的絕對動量 pass/fail

def momentum_select(view: PointInTimeView, cfg: QuantConfig) -> MomentumSelection | None:
    """eligible→動量→取 K→absmom。無合格資產回 None。full/mom_only/mom_ivol 共用唯一實作。"""
```

`MomentumStrategy.decide` 與 `Full._select_and_weight` 改為呼叫它。4b-2 的等價回歸測試 `test_full_and_mom_ivol_share_selection_layer` **保留**（此後成為結構性事實的守護，仍有防呆價值）。

## 2. `metrics.py`：Stationary Block Bootstrap + 平均曝險

### 2.1 Stationary bootstrap（§6.4，INV-6）

```python
def stationary_bootstrap_indices(n: int, mean_block: int, n_reps: int, rng) -> np.ndarray:
    """Politis-Romano：回 (n_reps, n) 的索引矩陣。

    每步以機率 1/mean_block 跳到新隨機起點，否則沿用前一索引 +1（circular wrap）。
    日報酬有自相關，iid 重抽的 CI 系統性偏窄（§6.4），故用 stationary bootstrap。
    """
```

- `mean_block = 21`、`n_reps = 1000`（規格 §6.4 定值，入 config 見 §6）。
- **RNG 由 `cfg.seed` 驅動**（INV-6：所有隨機性走單一 seeded RNG，seed 進 config）。同 (config, snapshot, commit) 三元組 → 同 CI。

### 2.2 兩種用法

```python
def bootstrap_metric_ci(values, rf, metric_fn, indices, alpha=0.05) -> tuple[float, float]:
    """單一策略指標的百分位 CI。"""

def paired_metric_diff_ci(values_a, values_b, rf, metric_fn, indices, alpha=0.05) -> dict:
    """配對差異 CI：對兩序列抽**同一組**索引，逐次算 metric(a)−metric(b)。
    回 {point, lo, hi, excludes_zero}。CI 不含 0 才算「優勢站得住」（§6.3）。"""
```

**為何配對**：§6.3 要求「`full` 優於每個殘缺版，且優勢在 bootstrap CI 下站得住」。獨立抽樣後比兩條 CI 是否重疊在統計上是錯的（會低估顯著性且忽略共變）。對同一組塊索引重抽兩條序列、逐次取差，才是差異的正確抽樣分布。

### 2.3 平均曝險（§6.4 缺的指標）

```python
def average_exposure(weights: pd.DataFrame) -> float:
    """mean over days of (1 − CASH 權重) = 平均風險曝險 E。"""
```

`compute_metrics` 增回傳 `average_exposure`（新增選填參數 `weights: pd.DataFrame | None`；未傳時該欄為 None，維持既有呼叫端相容）。

**接線**：`ablation._evaluate` 與 `experiments/runner.py` 目前呼叫 `compute_metrics` 未傳 weights，但 `run_strategy` 本就回傳 `(nav, weights, decisions)` 三張表——4c 把 weights 接進去，使消融表與 run 的 `metrics.json` 都含平均曝險。

## 3. 子期間分析（§6.4）

切三段：**2005-2009 / 2010-2019 / 2020-（含）**。每段對每策略跑同一組 `compute_metrics`。動量策略績效高度 regime 依賴，單一全期數字會說謊（§6.4）。切點入 config（見 §6），非硬編。

## 4. σ*±2% AC 量測（條件化，4b-2 §7 定義的操作化）

新增 `experiments/vol_target_ac.py`——**讀 run 產物、不重跑回測**。

### 4.1 `voltarget_only`：全期乾淨測
無 absmom，波動目標獨自負責 → 全期實現年化波動 = `std(日報酬) × √252`，判定落 **8%–12%**。

### 4.2 `full`：日層級閾值子集
1. 自 `decisions.parquet` 取 `event == "selection"` 的列，解析 `absmom` 與 `w_risky`（JSON），算該次決策的 **absmom 轉現金比例** `c = Σ_{t: absmom[t] is False} w_risky[t]`。
2. 對每個活躍日，取「管轄它的那次選擇」= **`execution_date ≤ 該日` 的最後一筆 selection 決策**（absmom 為選擇日量、持續到下次選擇；曝險檢查不改 absmom）。以其 `c` 標記該日。
3. **納入 `c ≤ 0.10` 的日子**（≥90% 風險額度過關 → 第二層實質未介入）。
4. 實現波動 = `std(該子集的日報酬) × √252`，判定落 **8%–12%**。
5. **另報嚴格版** `c == 0`（全過）當敏感度，兩者並陳。

閾值 0.10 入 config（見 §6）。輸出 `vol_target_ac.json`：兩策略、兩變體（閾值/嚴格）的實現波動、納入日數、判定通過與否。

## 5. 七策略消融全表（AC）

用既有 `run_ablation`，`strategy_ids` = 七策略全體，`param_grid` = §7.3：

```python
{"signal.top_k": [3, 5, 8],
 "risk.vol_target_annual": [0.08, 0.10, 0.12],
 "signal.momentum_lookback": [126, 252],
 "costs.per_side_bps": [0, 5, 10, 20]}
```

一次動一參數。**格數**：既有 `_build_cells` 不去重（baseline + 每個 (key,value) 對），故為 **baseline + 12 = 13 格**；其中與 baseline 同值的格（如 `top_k=5`）會重現 baseline，無害且保留（不改既有引擎語意）。

**預估時間 30-45 分鐘**（視格而異）：每格跑 7 策略，`full` 約 226 選擇日 × K 檔 GARCH refit + ~905 曝險檢查日 filter ≈ 100 秒、`mom_ivol` ≈ 60 秒（僅 refit）、`voltarget_only` ≈ 20 秒，其餘可忽略 → 單格約 3 分鐘 × 13 格。`top_k=8` 的格更慢。此為一次性 AC 交付，可接受。

**擴充 `run_ablation` 的輸出**：baseline 格外加一張 `bootstrap.parquet`——`full` vs 每個消融版（bh_spy/ew_menu/sixty_forty/mom_only/voltarget_only/mom_ivol）的 Sharpe 與 Calmar **配對差異 CI**（§2.2），欄含 `point/lo/hi/excludes_zero`。參數格不做 bootstrap（成本高且非 §6.3 所需）。

**紀律**（§7.3，寫進輸出的 README/註解）：敏感度表用於檢驗結論對參數擾動是否穩健，**不是用來挑最好的一格回填 config**。

**誠實結論**：若 `full` 未能在 CI 下顯著優於某層的消融版，那就是「該層無貢獻」的合格結論（§6.3 明言可移除該層），照實記錄，不調參數硬湊。

## 6. Config 新增

`RiskConfig` / 新 `StatsConfig`（置於 root，§6.4 統計參數）：

```yaml
stats:
  bootstrap_mean_block: 21          # §6.4 stationary bootstrap 平均塊長（交易日）
  bootstrap_reps: 1000              # §6.4 重抽次數
  bootstrap_alpha: 0.05             # 百分位 CI 的雙尾水準
  subperiods:                       # §6.4 子期間切點（起始年，含）
    - [2005, 2009]
    - [2010, 2019]
    - [2020, 9999]
  absmom_cash_threshold: 0.10       # §4.2 full 的 σ* 量測納入閾值（absmom 轉現金比例上限）
```

schema 驗證：`bootstrap_mean_block ≥ 1`、`bootstrap_reps ≥ 1`、`0 < bootstrap_alpha < 1`、`0 ≤ absmom_cash_threshold ≤ 1`、`subperiods` 非空且每段 `start ≤ end`。

## 7. 測試

`tests/test_backtest/test_metrics_bootstrap.py`：
- `stationary_bootstrap_indices`：形狀 (n_reps, n)、索引皆在 [0,n)、同 seed 決定性、塊結構（連續索引比例約 1−1/mean_block）。
- `bootstrap_metric_ci`：對已知常數序列 CI 退化為點；對雜訊序列 lo < point < hi。
- `paired_metric_diff_ci`：兩序列相同 → 差異 CI 含 0 且 point≈0、`excludes_zero=False`；b = a − 常數正偏移 → point>0 且 `excludes_zero=True`。**配對性守護**：對同一組索引重抽（非各自獨立）——以「相同序列的差異恆為 0」鎖住（若誤用獨立抽樣，差異會有雜訊、CI 不會退化）。
- `average_exposure`：手算合成 weights。
- INV-6：同 seed 兩次 → CI 完全相同。

`tests/test_experiments/test_vol_target_ac.py`：
- 合成 decisions/nav：absmom 全過 → 全期納入；部分決策 `c=0.5` → 對應日子被排除；閾值邊界 `c == 0.10` 納入（`≤`）。
- 「管轄決策」對應正確：日子落在兩次 selection 之間時用前一次的 `c`。
- 嚴格版（`c==0`）子集 ⊆ 閾值版子集。

`tests/test_backtest/test_momentum_selection.py`：
- `momentum_select` 對合成 view 回正確 eligible/scores/selected/absmom；無合格資產回 None。
- 抽取後 `full` 與 `mom_ivol` 的既有等價測試仍綠（結構性一致）。

消融全表與 AC 量測的真實快照跑為 **本機閘門**（`requires_snapshot`，CI 無快照乾淨 skip，比照 Phase 2 AC-3）。

## 8. 規格偏離備忘（供 PROGRESS 記錄）

1. **σ*±2% AC 條件化 + 日層級閾值操作化**：§9 只寫「`full` 已實現波動落 σ*±2%」；因 absmom 轉現金會正確壓低危機期波動，全期量對 `full` 不公平。改為 `voltarget_only` 全期乾淨測 + `full` 在 absmom 轉現金比例 ≤ `absmom_cash_threshold`(0.10) 的日子量，另報嚴格版敏感度。
2. **bootstrap 用配對差異檢定**：§6.3 只說「優勢在 CI 下站得住」，未指定做法；獨立 CI 比重疊在統計上是錯的，改為對同一組塊索引重抽兩序列、逐次取差。
3. **新增 `stats` config 區塊**：§7.2 未列 bootstrap/子期間/閾值參數；避免魔術數字。
4. **bootstrap 只對 baseline 格做**：參數格 9 格 × 7 策略 × 1000 次重抽成本過高，且 §6.3 的驗收邏輯只針對 baseline 的 `full` vs 消融版。
5. **`momentum_select` 抽取**（4b-2 backlog）：選擇一致性由結構保證而非測試，消融 apples-to-apples 的地基。
6. **`average_exposure` 補入 metrics**：§6.4 列為必附但 Phase 2 的 `compute_metrics` 未含。

## 9. 不做（YAGNI / 留待後段）

- 消融結果的視覺化、小倍數 NAV 圖、敏感度熱圖 → Phase 7（§11.2 第 6 頁）。
- DCC vs EWMA 相關消融 → Phase 5。
- 手刻 GARCH parity → Phase 6。
- 最終研究報告文字 → Phase 7c（4c 只產出表與判定，報告以此為骨架）。
