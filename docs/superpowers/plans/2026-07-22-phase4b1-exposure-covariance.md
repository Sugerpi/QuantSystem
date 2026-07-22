# Phase 4b-1 — 曝險 / 共變異數 / 波動預報器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 4b 的三個基礎模組——`portfolio/exposure.py`（波動目標+更新帶）、`models/covariance.py`（過渡滾動相關共變異數，INV-3）、`models/volatility` 的 refit/filter 波動預報器（有上界滾動窗）——各自純/可測，**不碰策略與 engine**。

**Architecture:** `target_exposure` 為純函數（clip + 帶邏輯）。`covariance` 以「投影 R 為合法 PSD 相關 → Σ=D·R·D」保證 INV-3（對稱/PSD/對角線=個別變異數）。`VolForecaster` 把昂貴的 GARCH 估計（選擇日 refit）與便宜的固定參數濾波（曝險檢查日 filter，經 arch `fix()`）分離，且內部一律切尾端 `garch_window` 根使成本 O(cap) 不隨時間膨脹。

**Tech Stack:** Python 3.11、numpy、pandas、arch 8.0.0、pytest。

**規格來源：** `DEVELOPMENT_GUIDE v1.2.md` §1.6/§1.7/§5.2/§5.3、INV-3。設計文件：`docs/superpowers/specs/2026-07-22-phase4b1-exposure-covariance-design.md`。

**重要背景（給零脈絡的實作者）：**
- 依賴方向（CLAUDE.md）：`config ← data ← models ← signals/portfolio ← backtest ← experiments`。`portfolio/` 與 `models/` 為上游，**不得 import `backtest`**。
- 既有（Phase 4a，勿重寫）：`quantcore/models/volatility/` 有 `base.py`（`VolatilityModel`、`GarchDegenerateError`、`DAYS_PER_YEAR=252`、`_SCALE=100.0`）、`ewma.py`（`Ewma(lam)`）、`garch_arch.py`（`GarchArch`）、`__init__.py`（`fit_volatility(spec, returns, *, ewma_lambda) -> FitOutcome(model, fell_back, reason)`、`annualized_forecast_vol(model, horizon)`）。
- `GarchArch.forecast(h)` 回每步變異數（已 ÷100² 還原）；INV-4 縮放（×100 估計 / ÷100² 還原）在 base。
- arch `fix()` 需**完整 5 參數向量** `[mu, omega, alpha[1], beta[1], nu]`（順序即 `res.params.index`），非 `GarchArch.params` 的 4 鍵 dict——故 Task 4 讓 `GarchArch` 多曝 `arch_params`。
- 硬性規則：任何參數只能在 `config/`；`garch_window` 本計畫入 config（Task 1）。
- 每個 task 結束跑 `uv run pytest -q` 應全綠、`uv run ruff check`/`ruff format --check` 乾淨後才 commit。commit 訊息用繁中、conventional-commit、結尾附 Co-Authored-By trailer。
- 目前基線：全套 **213 passed**。

## 檔案結構

| 檔案 | 責任 | 動作 |
|------|------|------|
| `quantcore/config/schema.py` | `RiskConfig` 加 `garch_window` | 修改 |
| `quantcore/config/default.yaml` | `garch_window: 1000` | 修改 |
| `quantcore/portfolio/exposure.py` | `target_exposure` + `ExposureResult` | 新增 |
| `quantcore/models/covariance.py` | `rolling_correlation`/`build_covariance`/`portfolio_vol`（INV-3） | 新增 |
| `quantcore/models/volatility/base.py` | 加 `annualize_variance_path` | 修改 |
| `quantcore/models/volatility/__init__.py` | `annualized_forecast_vol` 改用新 helper + 匯出 | 修改 |
| `quantcore/models/volatility/garch_arch.py` | 加 `arch_params` 屬性 + `garch_filter_forecast` | 修改 |
| `quantcore/models/volatility/forecaster.py` | `VolForecaster`（refit/filter/窗上界） | 新增 |
| `tests/test_config.py` | garch_window 驗證 | 修改 |
| `tests/test_portfolio/test_exposure.py` | exposure 純函數 | 新增 |
| `tests/test_models/test_covariance.py` | covariance 三性質 + 手算 | 新增 |
| `tests/test_invariants/test_covariance_valid.py` | INV-3 守護（補建） | 新增 |
| `tests/test_models/test_garch_arch.py` | filter helper 一致性 | 修改 |
| `tests/test_models/test_forecaster.py` | refit/filter/窗上界 | 新增 |

---

## Task 1: Config 新增 `risk.garch_window`

**Files:**
- Modify: `quantcore/config/schema.py`（`RiskConfig`）
- Modify: `quantcore/config/default.yaml`（`risk:` 區塊）
- Test: `tests/test_config.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_config.py` 末尾加入：

```python
def test_risk_garch_window_loaded():
    cfg = load_config("quantcore/config/default.yaml")
    assert cfg.risk.garch_window == 1000


def test_risk_garch_window_must_be_at_least_min_obs():
    import pytest
    from tests.fixtures.synthetic import make_cfg

    with pytest.raises(Exception):
        make_cfg(["SPY", "TLT"], risk={"garch_window": 50})  # < 100
```

（`load_config` 已於此檔匯入；若無則於檔頭加 `from quantcore.config import load_config`。）

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_config.py::test_risk_garch_window_loaded -v`
Expected: FAIL（`AttributeError` 或 `ValidationError`）。

- [ ] **Step 3: 加入 schema 欄位**

在 `quantcore/config/schema.py` 的 `RiskConfig`，於 `forecast_horizon` 之後加入：

```python
    garch_window: int = Field(ge=100)  # GARCH 估計滾動窗上限（交易日）；≥ GarchArch._min_obs
```

- [ ] **Step 4: 加入 default.yaml**

在 `quantcore/config/default.yaml` 的 `risk:` 區塊（`forecast_horizon` 之後）加入：

```yaml
  garch_window: 1000                # GARCH 估計滾動窗上限（交易日，~4 年）；界定每次 fit 成本 O(cap)
```

- [ ] **Step 5: 執行確認通過**

Run: `uv run pytest tests/test_config.py -v`
Expected: 全部 PASS。

- [ ] **Step 6: 全測試綠**

Run: `uv run pytest -q`
Expected: 215 passed（213 + 2 新）。

- [ ] **Step 7: Commit**

```bash
git add quantcore/config/schema.py quantcore/config/default.yaml tests/test_config.py
git commit -m "feat(config): risk 加 garch_window（GARCH 估計滾動窗上限，§5.2）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `portfolio/exposure.py` —— 波動目標 + 更新帶

**Files:**
- Create: `quantcore/portfolio/exposure.py`
- Test: `tests/test_portfolio/test_exposure.py`

**設計要點：** 純函數。`raw = σ*/σ̂_p`，`clipped = clip(raw, e_min, 1.0)`。`e_current is None`（首次/選擇日）或 `|clipped − e_current| > band` → 套用 `clipped`、`band_blocked=False`；否則沿用 `e_current`、`band_blocked=True`。`σ̂_p ≤ 0`/非有限 → `ValueError`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_portfolio/test_exposure.py`：

```python
"""target_exposure：clip、更新帶、首次無帶、誠實失敗（規格 §1.6/§1.7）。"""

from __future__ import annotations

import pytest

from quantcore.portfolio.exposure import ExposureResult, target_exposure


def test_first_application_no_band():
    # e_current=None → 直接套用 clip 後值，band_blocked=False
    r = target_exposure(sigma_p=0.20, sigma_star=0.10, e_min=0.10, band=0.10, e_current=None)
    assert isinstance(r, ExposureResult)
    assert r.exposure_raw == pytest.approx(0.5)
    assert r.exposure_applied == pytest.approx(0.5)
    assert r.band_blocked is False


def test_clip_upper_bound():
    # σ̂_p < σ* → raw>1 → clip 到 1.0
    r = target_exposure(sigma_p=0.05, sigma_star=0.10, e_min=0.10, band=0.10, e_current=None)
    assert r.exposure_raw == pytest.approx(2.0)
    assert r.exposure_applied == pytest.approx(1.0)


def test_clip_lower_bound():
    # σ̂_p 很大 → raw<e_min → clip 到 e_min
    r = target_exposure(sigma_p=2.0, sigma_star=0.10, e_min=0.10, band=0.10, e_current=None)
    assert r.exposure_raw == pytest.approx(0.05)
    assert r.exposure_applied == pytest.approx(0.10)


def test_band_blocks_small_change():
    # |clipped − e_current| ≤ band → 沿用舊值、band_blocked=True
    # σ̂_p=0.20 → clipped=0.5；e_current=0.55，差 0.05 ≤ 0.10 → 擋
    r = target_exposure(sigma_p=0.20, sigma_star=0.10, e_min=0.10, band=0.10, e_current=0.55)
    assert r.exposure_applied == pytest.approx(0.55)
    assert r.band_blocked is True


def test_band_allows_large_change():
    # 差 > band → 套用新值
    # clipped=0.5；e_current=0.30，差 0.20 > 0.10 → 套新
    r = target_exposure(sigma_p=0.20, sigma_star=0.10, e_min=0.10, band=0.10, e_current=0.30)
    assert r.exposure_applied == pytest.approx(0.5)
    assert r.band_blocked is False


def test_nonpositive_sigma_p_raises():
    with pytest.raises(ValueError):
        target_exposure(sigma_p=0.0, sigma_star=0.10, e_min=0.10, band=0.10, e_current=None)
    with pytest.raises(ValueError):
        target_exposure(sigma_p=float("nan"), sigma_star=0.10, e_min=0.10, band=0.10, e_current=None)
```

（若 `tests/test_portfolio/__init__.py` 不存在則建空檔——比照既有 test 套件結構。）

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_portfolio/test_exposure.py -v`
Expected: FAIL（`ModuleNotFoundError: quantcore.portfolio.exposure`）。

- [ ] **Step 3: 實作 exposure.py**

Create `quantcore/portfolio/exposure.py`：

```python
"""波動目標 + 更新帶（規格 §1.6 Step 3、§1.7）。全系統唯一曝險出口。純函數。

依賴方向：portfolio 上游於 backtest，只認基本型別。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ExposureResult:
    exposure_raw: float       # σ*/σ̂_p（clip 與帶寬判定前）
    exposure_applied: float   # 實際 E(t)
    band_blocked: bool        # 本次調整是否被更新帶擋下


def target_exposure(
    sigma_p: float,
    sigma_star: float,
    e_min: float,
    band: float,
    e_current: float | None,
) -> ExposureResult:
    """E(t) = clip(σ*/σ̂_p, e_min, 1)，含更新帶。

    e_current is None（首次 / 選擇日）→ 直接套用，不受帶約束。
    否則（曝險檢查日）：|clipped − e_current| > band 才調整，否則沿用 e_current。
    """
    if not math.isfinite(sigma_p) or sigma_p <= 0.0:
        raise ValueError(f"σ̂_p={sigma_p} 非正或非有限，曝險無定義")
    raw = sigma_star / sigma_p
    clipped = min(max(raw, e_min), 1.0)
    if e_current is None or abs(clipped - e_current) > band:
        return ExposureResult(raw, clipped, band_blocked=False)
    return ExposureResult(raw, e_current, band_blocked=True)
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_portfolio/test_exposure.py -v`
Expected: 全部 PASS（6 項）。

- [ ] **Step 5: Commit**

```bash
git add quantcore/portfolio/exposure.py tests/test_portfolio/test_exposure.py
git commit -m "feat(portfolio): target_exposure 波動目標 + 更新帶（§1.6/§1.7）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `models/covariance.py` —— 過渡共變異數（INV-3）

**Files:**
- Create: `quantcore/models/covariance.py`
- Test: `tests/test_models/test_covariance.py`

**設計要點：** `Σ = D·R_psd·D`。先把 R 投影為合法 PSD 相關（對稱化→截負特徵值→重正規化對角線為 1），再乘 `D=diag(σ̂)`。congruence 保 PSD、`R_ii=1` 保 `Σ_ii=σ_i²`。`portfolio_vol = sqrt(w'Σw)`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_models/test_covariance.py`：

```python
"""過渡共變異數：INV-3 三性質 + 手算 + 單資產退化（規格 §1.6、INV-3）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantcore.models.covariance import build_covariance, portfolio_vol, rolling_correlation


def test_rolling_correlation_returns_sorted_tickers_and_symmetric_R():
    rng = np.random.default_rng(0)
    df = pd.DataFrame(rng.normal(0, 0.01, (300, 3)), columns=["B", "A", "C"])
    R, tickers = rolling_correlation(df)
    assert tickers == ["A", "B", "C"]  # 排序
    assert R.shape == (3, 3)
    assert np.allclose(R, R.T)
    assert np.allclose(np.diag(R), 1.0)


def test_build_covariance_hand_computation():
    # 已知 R 與 σ̂，Σ = D R D 逐元比對
    sigma = {"A": 0.2, "B": 0.3}
    R = np.array([[1.0, 0.5], [0.5, 1.0]])
    Sigma = build_covariance(sigma, R, ["A", "B"])
    expected = np.array(
        [[0.2 * 0.2 * 1.0, 0.2 * 0.3 * 0.5], [0.3 * 0.2 * 0.5, 0.3 * 0.3 * 1.0]]
    )
    assert np.allclose(Sigma, expected)


def test_build_covariance_inv3_symmetric_psd_diag():
    sigma = {"A": 0.2, "B": 0.3, "C": 0.25}
    rng = np.random.default_rng(1)
    df = pd.DataFrame(rng.normal(0, 0.01, (300, 3)), columns=["A", "B", "C"])
    R, tickers = rolling_correlation(df)
    Sigma = build_covariance(sigma, R, tickers)
    assert np.allclose(Sigma, Sigma.T)  # 對稱
    assert np.linalg.eigvalsh(Sigma).min() >= -1e-10  # PSD
    for i, t in enumerate(tickers):
        assert Sigma[i, i] == pytest.approx(sigma[t] ** 2)  # 對角線=個別變異數


def test_build_covariance_projects_non_psd_R():
    # 刻意非 PSD 的 R（有負特徵值），投影後 Σ 仍 PSD 且對角線正確
    sigma = {"A": 0.2, "B": 0.2, "C": 0.2}
    R_bad = np.array([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]])
    assert np.linalg.eigvalsh(R_bad).min() < 0  # 確認輸入非 PSD
    Sigma = build_covariance(sigma, R_bad, ["A", "B", "C"])
    assert np.linalg.eigvalsh(Sigma).min() >= -1e-10  # 投影後 PSD
    for i in range(3):
        assert Sigma[i, i] == pytest.approx(0.2**2)  # 對角線仍=σ²


def test_portfolio_vol_hand_computation():
    Sigma = np.array([[0.04, 0.03], [0.03, 0.09]])
    w = {"A": 0.5, "B": 0.5}
    sp = portfolio_vol(w, Sigma, ["A", "B"])
    expected = float(np.sqrt(0.25 * 0.04 + 0.25 * 0.09 + 2 * 0.25 * 0.03))
    assert sp == pytest.approx(expected)


def test_portfolio_vol_single_asset_equals_sigma():
    Sigma = build_covariance({"SPY": 0.15}, np.array([[1.0]]), ["SPY"])
    assert portfolio_vol({"SPY": 1.0}, Sigma, ["SPY"]) == pytest.approx(0.15)


def test_build_covariance_rejects_bad_sigma():
    with pytest.raises(ValueError):
        build_covariance({"A": 0.2}, np.array([[1.0, 0.0], [0.0, 1.0]]), ["A", "B"])  # 缺 B
    with pytest.raises(ValueError):
        build_covariance({"A": -0.2, "B": 0.2}, np.eye(2), ["A", "B"])  # 非正
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_models/test_covariance.py -v`
Expected: FAIL（`ModuleNotFoundError: quantcore.models.covariance`）。

- [ ] **Step 3: 實作 covariance.py**

Create `quantcore/models/covariance.py`：

```python
"""過渡共變異數（規格 §1.6、INV-3）。Σ 的唯一出口。

Phase 4b 的相關 R 為滾動樣本相關（DCC 為 Phase 5，此為 placeholder，
比照 Phase 3 的 rolling_std→GARCH）。INV-3（對稱/PSD/對角線=個別變異數）靠
「投影 R 為合法 PSD 相關 → Σ=D·R·D」自然同時成立。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_correlation(returns_window: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """收 date×ticker 報酬窗，回 (樣本相關 R, 排序後 ticker 序)。欄序固定供對齊。"""
    cols = sorted(returns_window.columns)
    w = returns_window[cols].dropna()
    if len(w) < 2:
        raise ValueError("rolling_correlation 需至少 2 筆觀測")
    R = np.atleast_2d(np.corrcoef(w.to_numpy(), rowvar=False))
    return R, cols


def _project_to_psd_correlation(R: np.ndarray) -> np.ndarray:
    """對稱化 → 截負特徵值 → 重正規化對角線為 1（合法 PSD 相關矩陣）。"""
    R = (R + R.T) / 2.0
    vals, vecs = np.linalg.eigh(R)
    vals = np.clip(vals, 0.0, None)
    R_psd = (vecs * vals) @ vecs.T
    d = np.sqrt(np.diag(R_psd))
    d[d == 0.0] = 1.0  # 退化列避免除零
    R_corr = R_psd / np.outer(d, d)
    return (R_corr + R_corr.T) / 2.0  # 數值再對稱化


def build_covariance(
    sigma_hat: dict[str, float], R: np.ndarray, tickers: list[str]
) -> np.ndarray:
    """Σ = D·R_psd·D，D = diag(σ̂[tickers 順序])。INV-3 三性質成立。"""
    for t in tickers:
        s = sigma_hat.get(t)
        if s is None or not np.isfinite(s) or s <= 0.0:
            raise ValueError(f"σ̂[{t}]={s} 缺失/非正/非有限")
    R_psd = _project_to_psd_correlation(np.atleast_2d(np.asarray(R, dtype="float64")))
    d = np.array([sigma_hat[t] for t in tickers], dtype="float64")
    return (d[:, None] * R_psd) * d[None, :]  # D R D


def portfolio_vol(w_risky: dict[str, float], cov: np.ndarray, tickers: list[str]) -> float:
    """sqrt(w'Σw)，w 依 tickers 順序取自 w_risky（缺者為 0）。回年化組合波動 σ̂_p。"""
    w = np.array([w_risky.get(t, 0.0) for t in tickers], dtype="float64")
    var = float(w @ np.asarray(cov, dtype="float64") @ w)
    return float(np.sqrt(max(var, 0.0)))  # 數值噪音可能使 var 微負
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_models/test_covariance.py -v`
Expected: 全部 PASS（7 項）。

- [ ] **Step 5: 全測試綠 + lint**

Run: `uv run pytest -q` 與 `uv run ruff check quantcore/models tests/test_models` + `uv run ruff format --check quantcore/models tests/test_models`
Expected: 綠、乾淨。

- [ ] **Step 6: Commit**

```bash
git add quantcore/models/covariance.py tests/test_models/test_covariance.py
git commit -m "feat(models): 過渡共變異數 Σ=D·R·D（滾動相關，INV-3）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: INV-3 守護測試（`test_covariance_valid.py`）

**Files:**
- Create: `tests/test_invariants/test_covariance_valid.py`

**背景：** CLAUDE.md 不變量表列此檔為 INV-3 守護，但**目前不存在**（與 INV-4 同）。本 task 補建，含 mutation-style 的有牙齒守護。

- [ ] **Step 1: 寫測試**

Create `tests/test_invariants/test_covariance_valid.py`：

```python
"""INV-3：共變異數矩陣永遠對稱、PSD、對角線=個別變異數（規格 §3 INV-3）。"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.models.covariance import build_covariance


def test_covariance_symmetric_psd_diag_on_valid_R():
    sigma = {"A": 0.2, "B": 0.3, "C": 0.25}
    R = np.array([[1.0, 0.4, 0.2], [0.4, 1.0, 0.3], [0.2, 0.3, 1.0]])
    tickers = ["A", "B", "C"]
    Sigma = build_covariance(sigma, R, tickers)
    assert np.allclose(Sigma, Sigma.T)  # 對稱
    assert np.linalg.eigvalsh(Sigma).min() >= -1e-10  # PSD
    for i, t in enumerate(tickers):
        assert Sigma[i, i] == pytest.approx(sigma[t] ** 2)  # 對角線=個別變異數


def test_covariance_projection_has_teeth_on_non_psd_R():
    # 有牙齒守護：對刻意非 PSD 的 R，輸出仍須 PSD 且對角線精確=σ_i²。
    # 若拿掉 build_covariance 的 R PSD 投影/單位對角重正規化，此測試轉紅。
    sigma = {"A": 0.2, "B": 0.2, "C": 0.2}
    R_bad = np.array([[1.0, 0.95, -0.95], [0.95, 1.0, 0.95], [-0.95, 0.95, 1.0]])
    assert np.linalg.eigvalsh(R_bad).min() < 0  # 輸入確實非 PSD
    Sigma = build_covariance(sigma, R_bad, ["A", "B", "C"])
    assert np.linalg.eigvalsh(Sigma).min() >= -1e-10  # 投影後 PSD
    for i in range(3):
        assert Sigma[i, i] == pytest.approx(0.2**2)  # 對角線嚴守


def test_covariance_single_asset_is_variance():
    Sigma = build_covariance({"SPY": 0.15}, np.array([[1.0]]), ["SPY"])
    assert Sigma.shape == (1, 1)
    assert Sigma[0, 0] == pytest.approx(0.15**2)
```

- [ ] **Step 2: 執行確認通過**

Run: `uv run pytest tests/test_invariants/test_covariance_valid.py -v`
Expected: 全部 PASS（3 項）。

- [ ] **Step 3: 全測試綠**

Run: `uv run pytest -q`
Expected: 綠。

- [ ] **Step 4: Commit**

```bash
git add tests/test_invariants/test_covariance_valid.py
git commit -m "test(inv): INV-3 共變異數合法性守護測試（補上缺席的守護）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `garch_arch` 加固定參數濾波 + `annualize_variance_path` 抽取

**Files:**
- Modify: `quantcore/models/volatility/garch_arch.py`（加 `arch_params` 屬性 + `garch_filter_forecast`）
- Modify: `quantcore/models/volatility/base.py`（加 `annualize_variance_path`）
- Modify: `quantcore/models/volatility/__init__.py`（`annualized_forecast_vol` 改用 helper + 匯出）
- Test: `tests/test_models/test_garch_arch.py`（續加一致性測試）

**設計要點：** `garch_filter_forecast(fixed_params, returns, horizon)` 以 arch `fix()`（不跑 MLE）對 returns 濾波，回每步變異數（已 ÷100² 還原）。`fixed_params` 為完整 arch 向量（含 mu），故 `GarchArch` 多曝 `arch_params`。`annualize_variance_path` 抽取聚合公式供 forecaster 與 `annualized_forecast_vol` 共用（DRY）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_models/test_garch_arch.py` 加入（檔頭已有 `import numpy as np`、`GarchArch`、`make_garch_t_returns`）：

```python
def test_garch_filter_forecast_matches_fit_forecast():
    # filter 正確性錨：以 fit 出的完整參數對同序列濾波，結果須與 fit().forecast() 一致。
    from quantcore.models.volatility.garch_arch import garch_filter_forecast

    r = make_garch_t_returns(1500, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=13)
    m = GarchArch().fit(r)
    filtered = garch_filter_forecast(m.arch_params, r, 21)
    assert filtered.shape == (21,)
    assert np.allclose(filtered, m.forecast(21))


def test_arch_params_full_vector_length_five():
    r = make_garch_t_returns(1000, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=1)
    m = GarchArch().fit(r)
    # 完整 arch 向量 [mu, omega, alpha[1], beta[1], nu]
    assert m.arch_params.shape == (5,)
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_models/test_garch_arch.py::test_garch_filter_forecast_matches_fit_forecast -v`
Expected: FAIL（`AttributeError: arch_params` 或 `ImportError: garch_filter_forecast`）。

- [ ] **Step 3: base.py 加 `annualize_variance_path`**

在 `quantcore/models/volatility/base.py` 末尾（class 外）加入：

```python
def annualize_variance_path(per_step_var: np.ndarray) -> float:
    """每步變異數 → 年化波動：sqrt(mean(Var))·sqrt(252)（規格 §1.6 Step 1 的聚合）。"""
    return float(np.sqrt(np.mean(per_step_var)) * np.sqrt(DAYS_PER_YEAR))
```

- [ ] **Step 4: `__init__.py` 的 `annualized_forecast_vol` 改用 helper**

在 `quantcore/models/volatility/__init__.py`：把 `annualized_forecast_vol` 改為：

```python
def annualized_forecast_vol(model: VolatilityModel, horizon: int) -> float:
    """σ̂ = sqrt( (1/H)·Σ Var(t+h) )·sqrt(252)（規格 §1.6 Step 1）。"""
    return annualize_variance_path(model.forecast(horizon))
```

並在檔頭 import 補上 `annualize_variance_path`：

```python
from quantcore.models.volatility.base import (
    DAYS_PER_YEAR,
    GarchDegenerateError,
    VolatilityModel,
    annualize_variance_path,
)
```

且把 `annualize_variance_path` 加入 `__all__`。

**注意**：此重構把 `annualized_forecast_vol` 唯一的 `np.sqrt` 用法移除，`__init__.py` 的 `import numpy as np` 會變成未使用（ruff F401）。若 `np` 在 `__init__.py` 別無他用，一併移除該 import（跑 `uv run ruff check` 確認）。`DAYS_PER_YEAR` 仍在 `__all__` 中（re-export），不會被判未使用，保留。

- [ ] **Step 5: `garch_arch.py` 加 `arch_params` 與 `garch_filter_forecast`**

在 `quantcore/models/volatility/garch_arch.py` 的 `_estimate` 末尾（`self._scaled = scaled_returns` 之後）加：

```python
        self._arch_params = np.asarray(res.params.to_numpy(), dtype="float64")
```

在 `GarchArch` 加屬性（置於 `params` 屬性附近）：

```python
    @property
    def arch_params(self) -> np.ndarray:
        """完整 arch 參數向量 [mu, omega, alpha[1], beta[1], nu]，供 fix() 濾波。"""
        return np.asarray(self._arch_params, dtype="float64")
```

在檔案末尾（class 外）加模組函式：

```python
_SCALE = 100.0  # ×100 估計 / ÷100² 還原，慣例同 base（INV-4）；一致性由下方 test 鎖住


def garch_filter_forecast(
    fixed_params: np.ndarray, returns: pd.Series, horizon: int
) -> np.ndarray:
    """以固定 arch 參數對 returns 濾波（不跑 MLE），回每步變異數（已 ÷100² 還原）。

    fixed_params 為完整 arch 向量（GarchArch.arch_params）。§5.2 的便宜濾波路徑。
    """
    from arch import arch_model

    r = returns.astype("float64").dropna()
    am = arch_model(r.to_numpy() * _SCALE, mean="Constant", vol="GARCH", p=1, q=1, dist="t")
    res = am.fix(np.asarray(fixed_params, dtype="float64"))
    fc = res.forecast(horizon=horizon, method="analytic", reindex=False)
    return np.asarray(fc.variance.to_numpy()[-1], dtype="float64") / (_SCALE**2)
```

- [ ] **Step 6: 執行確認通過**

Run: `uv run pytest tests/test_models/test_garch_arch.py tests/test_models/test_fit_volatility.py -v`
Expected: 全部 PASS（含新 2 項與既有 annualized_forecast_vol 測試）。

- [ ] **Step 7: 全測試綠 + lint**

Run: `uv run pytest -q` 與 `uv run ruff check quantcore/models tests/test_models` + `uv run ruff format --check quantcore/models tests/test_models`
Expected: 綠、乾淨。

- [ ] **Step 8: Commit**

```bash
git add quantcore/models/volatility/garch_arch.py quantcore/models/volatility/base.py quantcore/models/volatility/__init__.py tests/test_models/test_garch_arch.py
git commit -m "feat(models): GARCH 固定參數濾波 helper + 年化聚合抽取（§5.2 filter）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `forecaster.py` —— refit/filter 波動預報器

**Files:**
- Create: `quantcore/models/volatility/forecaster.py`
- Test: `tests/test_models/test_forecaster.py`

**設計要點：** 有狀態元件（策略每 run 持有一實例）。`refit`（選擇日）走 `fit_volatility` 完整估計並快取；`filter`（曝險檢查日）以快取 params 走 `garch_filter_forecast`（GARCH）或重跑 EWMA。**內部一律切尾端 `garch_window` 根**使成本 O(cap)。fallback ticker 的 filter 重跑 EWMA。無快取的 filter 退化為 refit。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_models/test_forecaster.py`：

```python
"""VolForecaster：refit/filter、窗上界、fallback、無快取退化（規格 §5.2）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantcore.models.volatility.forecaster import VolForecaster
from tests.fixtures.synthetic import make_garch_t_returns


def _returns(n=1500, seed=5):
    return make_garch_t_returns(n, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=seed)


def test_refit_returns_reasonable_annualized_vol():
    f = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    s = f.refit("AAA", _returns())
    assert 0.01 < s < 2.0  # 合理年化波動
    assert f.last_fell_back("AAA") is False


def test_filter_matches_garch_filter_forecast():
    from quantcore.models.volatility.base import annualize_variance_path
    from quantcore.models.volatility.garch_arch import GarchArch, garch_filter_forecast

    r = _returns()
    f = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    f.refit("AAA", r)  # 快取 arch 參數
    got = f.filter("AAA", r)
    # 與直接用 fit 出的參數濾波再年化一致
    params = GarchArch().fit(r.iloc[-1000:]).arch_params
    expected = annualize_variance_path(garch_filter_forecast(params, r.iloc[-1000:], 21))
    assert got == expected


def test_window_cap_slices_tail_only():
    # 前段插極端值、後段正常：refit 應只用尾端 garch_window 根 → 等同只餵尾端
    r = _returns(n=1500, seed=7)
    r_spiked = r.copy()
    r_spiked.iloc[:500] = 5.0  # 前 500 根極端值（應被切掉）
    f_full = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=800)
    f_tail = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=800)
    s_full = f_full.refit("X", r_spiked)
    s_tail = f_tail.refit("X", r_spiked.iloc[-800:])
    assert s_full == s_tail  # 前段被切掉，兩者相同


def test_fallback_ticker_filter_reruns_ewma():
    # 造 GARCH 退化 → fell_back；filter 重跑 EWMA 不拋錯、回合理值
    import pytest

    from quantcore.models.volatility import base
    from quantcore.models.volatility.garch_arch import GarchArch

    r = _returns()
    f = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    orig = GarchArch._estimate

    def _boom(self, scaled):
        raise base.GarchDegenerateError("造退化")

    GarchArch._estimate = _boom
    try:
        f.refit("BBB", r)
        assert f.last_fell_back("BBB") is True
        s = f.filter("BBB", r)
        assert 0.01 < s < 2.0
    finally:
        GarchArch._estimate = orig


def test_filter_without_cache_falls_back_to_refit():
    f = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    s = f.filter("NEW", _returns())  # 從未 refit
    assert 0.01 < s < 2.0
    assert "NEW" in f._cache  # filter 已代為 refit 並快取
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_models/test_forecaster.py -v`
Expected: FAIL（`ModuleNotFoundError: quantcore.models.volatility.forecaster`）。

- [ ] **Step 3: 實作 forecaster.py**

Create `quantcore/models/volatility/forecaster.py`：

```python
"""refit/filter 波動預報器（規格 §5.2）。

昂貴的 GARCH 估計（選擇日 refit）與便宜的固定參數濾波（曝險檢查日 filter）分離。
內部一律切尾端 garch_window 根，成本 O(cap) 不隨回測時間膨脹。
有狀態：策略每 run 持有一實例（比照 bh_spy，引擎每 run 新建，不破 INV-6）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantcore.models.volatility import annualized_forecast_vol, fit_volatility
from quantcore.models.volatility.base import annualize_variance_path
from quantcore.models.volatility.garch_arch import GarchArch, garch_filter_forecast


class VolForecaster:
    def __init__(self, spec: str, ewma_lambda: float, horizon: int, garch_window: int) -> None:
        self._spec = spec
        self._ewma_lambda = ewma_lambda
        self._horizon = horizon
        self._window = garch_window
        # ticker -> (kind: 'garch'|'ewma', arch_params 或 None, fell_back)
        self._cache: dict[str, tuple[str, np.ndarray | None, bool]] = {}

    def _tail(self, returns: pd.Series) -> pd.Series:
        return returns.iloc[-self._window :]

    def refit(self, ticker: str, returns: pd.Series) -> float:
        """選擇日：完整估計（含 fallback），快取，回年化 σ̂。"""
        outcome = fit_volatility(self._spec, self._tail(returns), ewma_lambda=self._ewma_lambda)
        if isinstance(outcome.model, GarchArch):
            self._cache[ticker] = ("garch", outcome.model.arch_params, outcome.fell_back)
        else:
            self._cache[ticker] = ("ewma", None, outcome.fell_back)
        return annualized_forecast_vol(outcome.model, self._horizon)

    def filter(self, ticker: str, returns: pd.Series) -> float:
        """曝險檢查日：以快取參數濾波（GARCH 走 fix()，EWMA 重跑）。無快取則 refit。"""
        if ticker not in self._cache:
            return self.refit(ticker, returns)
        kind, params, _ = self._cache[ticker]
        window = self._tail(returns)
        if kind == "garch":
            return annualize_variance_path(garch_filter_forecast(params, window, self._horizon))
        outcome = fit_volatility("ewma", window, ewma_lambda=self._ewma_lambda)
        return annualized_forecast_vol(outcome.model, self._horizon)

    def last_fell_back(self, ticker: str) -> bool:
        """該 ticker 上次 refit 是否退回 EWMA（供 4b-2 落盤 model_details）。"""
        return self._cache[ticker][2]
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_models/test_forecaster.py -v`
Expected: 全部 PASS（5 項）。

- [ ] **Step 5: 全測試綠 + lint**

Run: `uv run pytest -q` 與 `uv run ruff check quantcore tests` + `uv run ruff format --check quantcore tests`
Expected: 綠、乾淨。

- [ ] **Step 6: Commit**

```bash
git add quantcore/models/volatility/forecaster.py tests/test_models/test_forecaster.py
git commit -m "feat(models): VolForecaster refit/filter 分離 + 有上界滾動窗（§5.2）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: 更新 PROGRESS.md（4b-1 完成紀錄）

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: 記錄 4b-1 完成**

在 `PROGRESS.md` 的 Phase 4 區塊把已完成的 4b-1 子項打勾（`portfolio/exposure.py`），並在「變更紀錄」加一行，記：
- 完成項：`exposure.py`（波動目標+帶）、`covariance.py`（過渡滾動相關 Σ，INV-3）、`VolForecaster`（refit/filter + 有上界滾動窗 garch_window）、`garch_filter_forecast`。
- **補建缺席的 INV-3 守護測試 `test_covariance_valid.py`**（此前不存在，與 INV-4 同）。
- 4 處規格偏離（見設計文件 §4）+ 補 garch_window 窗上界（避免展開窗爆炸）。
- 邊界：未碰策略/engine，待 4b-2 組裝。

- [ ] **Step 2: 全測試綠 + 格式檢查**

Run: `uv run pytest -q && uv run ruff format --check quantcore tests && uv run ruff check quantcore tests`
Expected: 測試綠、ruff 乾淨。

- [ ] **Step 3: Commit**

```bash
git add PROGRESS.md
git commit -m "docs(phase4b1): 曝險/共變異數/波動預報器完成 + 補建 INV-3 守護

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 完成後

4b-1 完成後，`feature/phase4-volatility` 上應有三個獨立可測的基礎模組（exposure/covariance/forecaster）+ INV-3 守護。**策略與 engine 未動**。

下一步為 4b-2（把三模組組進 `voltarget_only`/`full`、`mom_ivol` 遷移 GARCH、Diagnostics 落盤、engine refit/filter 接線、`default.yaml` 翻 garch_arch），另開 brainstorming → spec → plan。
