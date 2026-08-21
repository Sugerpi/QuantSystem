# 顯著性檢定 · 巢狀消融階梯 + 分指標結論

- 日期：2026-08-21
- 狀態：設計（待實作）
- 規格對照：`DEVELOPMENT_GUIDE v1.2.md` §6.3（驗收邏輯）、§6.5（顯著性檢定）
- 不變量：INV-6（可重現）

## 1. 動機

首次真快照讀數（見 [[significance-testing-first-read]]）結論不清楚，根因有二：
1. 置換對照混入非殘缺版（bh_spy/ew_menu/sixty_forty），稀釋「每一層有沒有貢獻」的問題。
2. 結論綁在 Sharpe，但 full 的 edge 其實在 MaxDD/Calmar。

本階段讓 `significance_report` 針對**巢狀消融階梯的相鄰步**、**分指標**（Sharpe / Calmar / MaxDD）產出 CI + 置換 p-value，讓報告能寫出一句乾淨結論：「哪一層在哪個指標上顯著加分」。

**交付範圍**：延伸既有 `significance_report`（新增 `ladder` 區塊）+ 一個 MaxDD 陣列版 metric + config 宣告階梯 + 測試。不碰 web。

## 2. 巢狀階梯定義（經核實 §6.3 策略組成）

每一步只加一層：

| 步 | simpler → richer | 新增的層 |
|----|------------------|----------|
| 1 | `bh_spy` → `mom_only` | 橫斷面動量選股 |
| 2 | `mom_only` → `mom_ivol` | inverse-vol 定倉 |
| 3 | `mom_ivol` → `full` | 組合波動目標（總曝險控制） |

`voltarget_only`（SPY + vol-target、無動量）**不在**線性階梯上，屬旁支消融，本階段不納入 ladder（仍可由既有 full-vs-all 置換區塊看到）。階梯為 config 宣告的有序清單（simple→rich），預設 `[bh_spy, mom_only, mom_ivol, full]`。

## 3. Config 新增

`StatsConfig`（`schema.py`）+ 三份 yaml：

```yaml
stats:
  # ...既有...
  ablation_ladder: [bh_spy, mom_only, mom_ivol, full]   # 巢狀階梯（simple→rich）
```

驗證：`min_length=2`、元素為非空字串。策略存在性於 report 端對 run 實際策略集檢查（與既有 `significance_strategy` 一致，避免 config 反向依賴 backtest）。

## 4. 新增純函式

`quantcore/backtest/metrics.py` 新增陣列版 MaxDD（供 bootstrap/置換共用，比照既有 `metric_calmar`）：

```python
def metric_max_drawdown(r: np.ndarray, rf: np.ndarray) -> float:
    """報酬陣列版 MaxDD（供 significance；rf 未用）。回負值或 0。"""
    return max_drawdown(_nav_from_returns(r))
```

方向約定：MaxDD 為負值，**越接近 0 越好**。ladder 的 observed = metric(richer) − metric(simpler)，故 MaxDD 的正 diff = 回撤改善。CI 排除 0 表示該層在該指標上有顯著差異。

## 5. `significance_report` 延伸

新增 `_ladder_analysis(cfg, snapshot, cell_ret, rng)`：
- 讀 baseline cell 各階梯策略的日報酬（來源同既有置換：`cell_label == "baseline"`）。
- 對每個相鄰對 `(simpler, richer)` × 每個 metric ∈ {sharpe, calmar, max_drawdown}：
  - **block bootstrap 配對差異 CI**：重用 `paired_metric_diff_ci` + `stationary_bootstrap_indices`（索引由 richer 序列長度、`cfg.stats.bootstrap_*` 建，RNG 走 `cfg.seed`）。
  - **置換 p-value**：重用 `permutation_test_paired`（`cfg.stats.mc_permutations`、`bootstrap_mean_block`）。
- 產出列：`{step, simpler, richer, added_layer, metric, observed, ci_lo, ci_hi, ci_excludes_zero, p_value}`。
- `added_layer` 為人可讀字串（step→層名對照表放模組內常數，非魔術數字：屬標籤映射）。

存在性：階梯策略若不在 run 中 → `ValueError`（清楚列出缺哪個）。

`significance.json` 新增頂層鍵 `ladder`（list）。既有 `dsr` / `pbo` / `permutation` / `provenance` 不動。

RNG 使用順序固定（先跑既有 permutation 區塊或 ladder 區塊，順序寫死於程式並以測試鎖定），確保 INV-6 位元可重現。

## 6. 測試（AC：全綠才算數）

`tests/test_backtest/test_metrics.py`（或既有 significance 測試檔）：
- `metric_max_drawdown`：對已知報酬序列手算 golden，且 = `max_drawdown(_nav_from_returns(r))`。

`tests/test_experiments/test_significance_report.py`（擴充，沿用既有合成快照 fixture）：
- `significance.json` 新增 `ladder` 鍵；每列含全部欄位；`step` 覆蓋 len(ladder)−1 步。
- 每步的 `metric` 覆蓋 {sharpe, calmar, max_drawdown}。
- 階梯策略缺席 → `ValueError`。
- INV-6：同 seed 兩次跑 `significance.json` 位元一致（含新 ladder 區塊）。

## 7. 非目標（YAGNI）

- 分子期間顯著性（第 2 步，另立）。
- walk-forward OOS + embargo（第 3 步，另立）。
- web 呈現。
- 把 `voltarget_only` 硬塞進線性階梯（它非線性巢狀，混入會讓「加一層」失真）。

## 8. 參考

- Bailey et al.（見 §6.5 與附錄 B）。既有 stationary bootstrap / 置換基礎設施重用，不重造。
