# 統計嚴謹性補洞：DSR / PBO / 蒙地卡羅置換檢定

- 日期：2026-08-16
- 狀態：設計（待實作）
- 規格對照：`DEVELOPMENT_GUIDE v1.2.md` §6（統計驗證）；本設計為 spec 未涵蓋的**新增**穩健性檢定
- 不變量：INV-1（無 look-ahead）、INV-6（可重現：config+snapshot+commit 決定輸出）

## 1. 動機

系統已有 stationary block bootstrap 配對差異 CI（`metrics.py`）、交易成本敏感度掃描與子期間分析。缺口在於**多重檢定校正**：消融跑了大量參數格、七策略比較後選出 `full`，但現有 bootstrap CI 未校正「試了很多次」造成的假顯著。本階段補三個方法，讓「full 勝出」的結論在搜尋次數校正後仍站得住。

**本階段交付範圍**：純函式引擎 + 編排 CLI + run 目錄產物 + 測試。不含 web dashboard 呈現（留待數字出來後再決定）。

## 2. 架構與依賴

依賴方向遵守 `config ← data ← models ← signals/portfolio ← backtest ← experiments`。

| 檔案 | 角色 | 說明 |
|------|------|------|
| `quantcore/backtest/significance.py` | 純函式（新） | 與 `metrics.py` 同層。無檔案 IO，RNG 由呼叫端傳入。 |
| `quantcore/experiments/significance_report.py` | 編排 + CLI（新） | 讀消融 run 目錄 → 自動數 N、抽 returns 矩陣 → 呼叫純函式 → 落 `significance.json`。RNG 走 `cfg.seed`。 |
| `quantcore/experiments/ablation.py` | 修改 | 多落 `cell_returns.parquet`（PBO 需每格日報酬矩陣）。 |
| `quantcore/config/schema.py` + 三份 yaml | 修改 | `StatsConfig` 新增四個參數。 |

## 3. 統計方法定義

**共同約定**：所有 Sharpe 一律以**每期（非年化）**值進入公式（annualized ÷ √252）；n = 觀測日數；kurt 為非超額峰態（常態 = 3）。參考 Bailey & López de Prado。

### 3.1 PSR / DSR（方法 A）

- `psr(sr, n, skew, kurt, sr_benchmark) = Φ( (sr − sr_benchmark)·√(n−1) / √(1 − skew·sr + ((kurt−1)/4)·sr²) )`
- `expected_max_sharpe(sr_variance, N) = √V·[ (1−γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) ]`
  - γ = 0.5772156649…（Euler-Mascheroni）；Z⁻¹ = 標準常態反 CDF。
- `deflated_sharpe_ratio(...)` = 以 `expected_max_sharpe` 為 benchmark 的 PSR。
  - **N** = 消融格數（自動數 `comparison.parquet` 之 `cell_label` 唯一值數）。
  - **V** = 那 N 格中目標策略（`significance_strategy`，預設 `full`）Sharpe 的橫斷面變異（ddof=1）。
  - 判讀：DSR > 0.95 → 目標策略 Sharpe 在校正搜尋次數後仍顯著 > 0。

### 3.2 PBO via CSCV（方法 B）

Bailey, Borwein, López de Prado, Zhu (2017)。**鎖定 `full` 一個策略、以消融格為候選集**。

- 輸入：`full` 在各消融格的日報酬矩陣 M（T×N）。
- 程序：
  1. T 列切成 S 塊（S = `pbo_n_splits`，偶數；不整除時尾端餘列丟棄並記錄）。
  2. 列舉 C(S, S/2) 種對半組合，各取 S/2 塊為 IS、其餘為 OOS。
  3. 每組：IS 拼接算各格 Sharpe，取最佳格 n\*；OOS 算各格 Sharpe，求 n\* 的 OOS 相對排名 ω ∈ (0,1)；logit λ = ln(ω/(1−ω))。
  4. **PBO** = λ ≤ 0 的組合比例。
- 判讀：PBO < 0.5 才算沒過擬合，越低越好。
- 邊界：N < 2 或 S 為奇數 → 回 NaN 並記錄原因（不崩潰）。

### 3.3 蒙地卡羅置換檢定（方法 C）

- `full` vs 各殘缺版的配對 Sharpe / Calmar 差異，做**區塊符號置換**：塊長 = `bootstrap_mean_block`，每塊隨機決定是否對調兩序列（尊重自相關）→ 建 null 分布。
- 雙尾 p-value = null 中 |diff| ≥ |observed| 的比例。
- 與既有 bootstrap CI 交叉驗證：CI 排除 0 且 permutation p < 0.05 兩者一致才踏實。

## 4. Config 新增

`StatsConfig`（`schema.py`）與三份 yaml（`default` / `canonical_ewma` / `canonical_dcc`）同步新增：

```yaml
stats:
  # ...既有...
  significance_strategy: full     # DSR/PBO 鎖定的策略（須為已註冊策略）
  psr_benchmark_sr: 0.0           # PSR 資訊性 benchmark（每期，非年化）
  pbo_n_splits: 16                # CSCV 塊數 S（偶數，ge=2）
  mc_permutations: 1000           # 置換次數（ge=1）
```

schema 驗證：`pbo_n_splits` 偶數且 ≥ 2；`mc_permutations` ≥ 1；`significance_strategy` 非空字串（存在性於 report 端對 `STRATEGIES` 檢查，避免 config 反向依賴 backtest）。

## 5. 落盤產物

### 5.1 `cell_returns.parquet`（`ablation.py` 新增）

long 格式：`cell_label`（str）、`strategy_id`（str）、`date`（datetime64）、`ret`（float64）。各格同一 clock、等長。與既有 `comparison.parquet` / `manifest.json` 併存於同一 run 目錄。

### 5.2 `significance.json`（`significance_report.py` 產出）

```json
{
  "provenance": {"git_commit": "...", "config_hash": "...", "snapshot_id": "...", "N": 10},
  "dsr": {"strategy": "full", "sr": 0.0, "psr": 0.0, "expected_max_sr": 0.0,
          "dsr": 0.0, "n_days": 0, "skew": 0.0, "kurt": 0.0, "sr_variance": 0.0},
  "pbo": {"value": 0.0, "n_splits": 16, "n_candidates": 10, "n_combinations": 12870},
  "permutation": [{"vs": "mom_only", "metric": "sharpe", "observed": 0.0, "p_value": 0.0}]
}
```

JSON `sort_keys=True`、`ensure_ascii=False`，供位元級可重現比對。

## 6. 測試（AC：全綠才算數）

`tests/test_backtest/test_significance.py`：
- PSR 退化解析驗證：skew=0、kurt=1 時分母=1，`psr == Φ(sr·√(n−1))`（sr_benchmark=0）。（常態 kurt=3 分母為 √(1+0.5·sr²)，不退化。）
- `expected_max_sharpe` 對小 N（如 N=2、10）手算比對。
- PBO 合成資料：純噪音矩陣 → PBO ≈ 0.5；單欄真實壓倒其餘 → PBO ≈ 0。
- permutation：固定 seed 決定性；observed 與 `paired_metric_diff_ci` 的 point 一致。
- 邊界：N<2 / 奇數 S → NaN 且不崩潰。

`tests/test_experiments/test_significance_report.py`：
- 小 fixture 消融 run → CLI 產出合法 `significance.json`（schema 完整）。
- INV-6：同 seed 兩次跑，`significance.json` 位元一致。

`tests/test_experiments/test_ablation.py`（擴充）：
- `cell_returns.parquet` schema 正確；各格對齊（同 clock、等長）。

## 7. 非目標（YAGNI）

- web dashboard 呈現（本階段不做）。
- 非線性滑價 / 成本 MC（屬「成本穩健性」階段）。
- 全因子消融格（維持既有 one-at-a-time 網格；CSCV 不要求因子完整）。
- Purged k-fold CV：系統為 walk-forward-by-construction、無重疊標籤 k-fold，教科書 purged CV 不適用。

## 8. 參考

- Bailey & López de Prado (2012) — Probabilistic Sharpe Ratio.
- Bailey & López de Prado (2014) — Deflated Sharpe Ratio.
- Bailey, Borwein, López de Prado & Zhu (2017) — PBO / CSCV.
- Politis & Romano (1994) — stationary bootstrap（既有）。
