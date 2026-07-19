# Phase 3 — 訊號與組合層 設計文件

> 規格來源：`DEVELOPMENT_GUIDE v1.2.md` §1.3 / §1.4 / §1.6（Step 2）/ §1.7 / §6.2 / §6.3 / §7.3。
> 本文件為 brainstorming 定案，作為 writing-plans 的輸入。日期：2026-07-19。

## 0. 範圍

Phase 3 完成「持有什麼（選標的）」與「相對權重」兩層，**不含**波動目標與 GARCH（Phase 4）。
產出策略：`sixty_forty`、`mom_only`、`mom_ivol`；波動率暫用 63 日滾動標準差當 GARCH 的 placeholder。

AC（PROGRESS）：
1. 消融跑得動並產出比較表
2. 決策 diagnostics 完整落盤

### 已具備、不重做的基礎設施
- `Diagnostics` 全欄位已 Optional，`decisions.parquet` 落盤（`experiments/runner.py::_flatten_decisions` / `_diagnostics_row`）。
- Strategy pattern（`decide(view, event)` + `DecisionEvent`）、`portfolio/selection.py::eligible_assets`、`STRATEGIES` 註冊表。

## 1. 模組與介面

依賴方向（CLAUDE.md）：`config ← data ← models ← signals/portfolio ← backtest ← experiments`。
`signals` 與 `models` 為上游純函數，**收 DataFrame/Series，不 import backtest 型別**（比照現有 `selection.py`）。

```
signals/momentum.py                         # 純函數
  cross_sectional_momentum(prices, lookback, skip) -> dict[ticker, float]
  absolute_momentum(prices, rates, lookback)        -> dict[ticker, bool]

portfolio/selection.py                      # 既有 eligible_assets 保留，新增：
  select_top_k(momentum_scores, k)                  -> list[str]

portfolio/weighting.py                      # 新檔
  inverse_vol(sigma_hat)                            -> dict[ticker, float]   # Σ=1
  equal_weight(assets)                              -> dict[ticker, float]   # Σ=1
  route_absmom_to_cash(w_risky, absmom_pass)        -> (weights, cash)

models/volatility/rolling_std.py            # 最小 placeholder（Phase 4 base.py 收編）
  annualized_vol(adj_close, window)                 -> float
```

策略層（`backtest/strategies/`）為**組合根**：`elig → momentum → topK → σ̂ → weighting → absmom → cash`。
backtest 在所有層下游，可 import signals / portfolio / models。

## 2. 訊號計算（§1.3 / §1.4）

### 橫斷面動量（12-1）
每檔以其 ≤ t 的 `adj_close`（含息總報酬指數）計算：
```
M_i(t) = adj_close[t − skip] / adj_close[t − lookback] − 1     # 預設 skip=21, lookback=252
```
- offset 為「bar 位移」（交易日），以 per-ticker 歷史的 iloc 位置取值。
- 需 ≥ `lookback + 1` 根 bar 才算得出 `t − lookback`；不足者不產生分數。

### 絕對動量（§1.4）
```
AbsMom_i(t) = TR_i 過去 lookback 日總報酬 − 同期 T-bill 累積報酬
TR_i        = adj_close[t] / adj_close[t − lookback] − 1        # 全窗，不套 skip
pass        = AbsMom_i(t) > 0
```
- T-bill 累積：DTB3 日利率（÷100 ÷252）於同一 lookback 窗複利累積，假日 ffill。
- **回看窗沿用 `momentum_lookback`（252）**，不新增參數。

## 3. 選擇與權重（§1.3 / §1.6 Step 2）

### 排序取 K（`select_top_k`）
- 依分數降序，**平手以 ticker 字母序升序**（決定性），取前 K。

### 相對權重與絕對動量歸一（**核心語意，已定案**）
兩策略曝險 E = 1.0（無波動目標）。流程：
1. `w_risky` **在前 K 檔上算完，Σ = 1**：
   - `mom_only`：等權 `1/K`
   - `mom_ivol`：`inverse_vol`（`w_i = (1/σ̂_i) / Σ(1/σ̂_j)`）
2. 逐檔查絕對動量，**fail 檔的 w_risky 整份挪入 CASH**（**不**在 pass 檔上重新歸一）。
3. `target_weights = {pass 檔: 各自 w_risky} + {CASH: Σ fail 檔 w_risky}`，Σ 仍為 1。

理由：§1.3 先把配額配給前 K，§1.4 再把 fail 檔「部位配額轉入現金」。保留原配額語意。

### σ̂（`mom_ivol` 用）
- `rolling_std.annualized_vol(adj_close, window=vol_window)`：末 `window` 日報酬標準差 × √252。

## 4. 策略清單（本階段新增三支）

| strategy_id | 邏輯 | Diagnostics 填寫 |
|-------------|------|-----------------|
| `sixty_forty` | 每選擇日重平衡回 `{SPY:0.6, IEF:0.4, CASH:0}` | eligible/selected = [SPY, IEF] |
| `mom_only` | 選 K + 等權 + 絕對動量 | + momentum_scores(全合格)、selected、absmom、w_risky=等權；sigma_hat=None |
| `mom_ivol` | 選 K + inverse-vol + 絕對動量（無波動目標） | 同上 + sigma_hat、w_risky=inverse-vol |

- 曝險欄（`sigma_p` / `exposure_raw` / `exposure_applied` / `band_blocked`）維持 None，Phase 4 才有。
- 三支均只在 `DecisionEvent.SELECTION` 動作（無曝險層）。
- `warmup_days`：mom 策略 = `momentum_lookback + 1`（確保首個決策日算得出動量）。

## 5. Config 改動

- `VolModel = Literal["garch_arch", "garch_own", "ewma", "rolling_std"]`
- `RiskConfig` 新增 `vol_window: int = Field(gt=0)`
- `config/default.yaml`：
  - `risk.vol_window: 63`
  - `risk.vol_model: rolling_std`（**Phase 3 暫定**，唯一實作的 vol 模型；Phase 4 翻回 `garch_arch`）
- vol 工廠對尚未實作的 `garch_arch` / `garch_own` / `ewma` 丟 `NotImplementedError`（誠實，不靜默）。

> 規格偏離備忘：§7.2 config 範例的 `vol_model` 為 `garch_arch`；Phase 3 因 GARCH 未實作暫設 `rolling_std`。記入 PROGRESS。

## 6. 消融引擎（`experiments/ablation.py`，§7.3）

- **通用引擎**：收 `base config + 參數格 + strategy 清單`，逐格跑，跟得上多少策略跑多少。
- 逐格以 `run_strategy` in-memory 計算 metrics（**不**為每格開 run 目錄），彙整成單一比較表。
- 輸出：`runs/<ts>_ablation/comparison.parquet` + 終端摘要表。
- Phase 3 參數格：策略 = 全部已註冊可跑者（5 支）；敏感度 `top_k ∈ {3,5,8}`、`momentum_lookback ∈ {126,252}`、`cost_bps ∈ {0,5,10,20}`。
- `vol_target` 敏感度留 Phase 4（無波動目標可調）。
- **紀律**（§7.3）：敏感度表用途是確認結論穩健，不是挑最好一格回填 config。

## 7. 測試策略（TDD）

**單元**
- momentum：手算 golden；bar 不足回傳缺分數。
- absmom：已知 tbill 序列下 pass/fail 邊界。
- `select_top_k`：分數與平手（字母序）決定性。
- `inverse_vol`：高 σ̂ → 低權重、Σ=1。
- `rolling_std.annualized_vol`：已知報酬序列數值。
- `route_absmom_to_cash`：權重守恆（Σ=1），全 fail → 全現金。

**策略級**（合成迷你快照）
- `mom_only` / `mom_ivol` 產出預期 target_weights。
- diagnostics 欄位齊全（AC-2）：mom_ivol 的 momentum_scores / absmom / sigma_hat / w_risky 皆落盤非空。

**不變量**
- INV-1 結構性已守（momentum 只吃 `view.prices ≤ t`）；沿用既有 `test_no_lookahead.py`。

**消融**
- smoke test：合成快照上跑得動並產出非空 `comparison.parquet`（AC-1）。

## 8. 邊界與已知限制

- momentum 需 ≥ `lookback + 1` 根 bar；`min_history_days=252` 只保證 252 根 → 合格但 bar 不足者不產生 momentum_score、排序時排除（不 selected）。
- Phase 3 無波動目標：`mom_ivol` 全程滿倉（E=1），與 `full` 的差異（曝險控制）留待 Phase 4 消融驗證。
- `rolling_std` 為粗糙估計，僅作 placeholder；Phase 4 以 QLIKE/MZ-R²（§5.4）評估後由 GARCH 取代預設。
