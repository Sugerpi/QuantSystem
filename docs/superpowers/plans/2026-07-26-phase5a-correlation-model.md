# Phase 5a — 相關模型層（DCC / EWMA-corr）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把組合波動用的相關矩陣 R 從過渡樣本相關換成可切換的 DCC(1,1) / EWMA-corr，並做 DCC vs EWMA 消融，達成 Phase 5a AC。

**Architecture:** 鏡射 Phase 4 的 `VolForecaster`——`CorrelationForecaster` 分離「貴的 (a,b) QMLE 週期重估」與「便宜的 Q_t 遞迴每次濾波」。DCC 第二步（QMLE + 遞迴 + 正規化）手寫（arch 無 DCC），單變量 σ_t 仍用既有 GARCH。標準化殘差複用 `VolForecaster`（不重跑單變量 GARCH）。相關只透過 `portfolio_vol → σ̂_p → 曝險純量` 影響結果，權重仍 inverse-vol（ERC 留 5b）。

**Tech Stack:** Python 3.12、uv、numpy、pandas、scipy.optimize、arch（僅單變量 GARCH）、pytest、ruff format。

**規格/設計來源：** `DEVELOPMENT_GUIDE v1.2.md` §1.6/§5.3/§5.4/INV-3/INV-6；設計文件 `docs/superpowers/specs/2026-07-26-phase5a-correlation-model-design.md`。

---

## 執行中修訂（post-Task-3 review amendments）

1. **Task 1 hardening**（已於 commit `e518f2c` 完成）：`normalize_to_correlation` 對零變異數對角線塌陷改為**拋 ValueError**（不再靜默 `d==0→1` 產出 R_ii=0）。理由：新的 EWMA/DCC 走 `np.cov`，常數欄給 0 逃過 `build_covariance` 的 finiteness 檢查 → 靜默腐蝕下游變異數（相對舊 rolling 路徑經 `np.corrcoef`→NaN→拋錯 為安全退步）。誠實失敗，比照 `portfolio_vol`/`inverse_vol`。

2. **`DccParams` `eq=False`**（已於 commit `14a79bb` 完成）：frozen dataclass 含 ndarray 欄位，預設 `__eq__/__hash__` 會拋錯；作值載體、以身分比較即可。

3. **Q̄ shrinkage 進 config（`_QBAR_SHRINK` 移除，改顯式 `shrink` 參數串接）**（Task 3 已改 `q_bar(std_resid, shrink)`，commit `14a79bb`）。CLAUDE.md 硬規則：影響相關估計的建模超參數（設計文件明言可消融）不得在 config 外。以下 task 據此調整：
   - **Task 4**：`estimate_dcc(std_resid, fixed_ab, shrink)`；內部 `q_bar(std_resid, shrink)`；退化 fallback 分支 Q̄=I 不需 shrink。測試以 `shrink=0.10` 呼叫。
   - **Task 7**：`CorrelationForecaster.__init__(..., qbar_shrink)`；`refit` 內 `estimate_dcc(std_resid, self._fixed_ab, self._qbar_shrink)` 與沿用分支 `q_bar(std_resid, self._qbar_shrink)`。測試以 `qbar_shrink=0.10` 建構。
   - **Task 8**：config 加 `risk.dcc_qbar_shrink: 0.10`；schema `dcc_qbar_shrink: float = Field(ge=0, lt=1)`。default.yaml 一併加。
   - **Task 9**：`vol_target_base` 建 `CorrelationForecaster` 時傳 `cfg.risk.dcc_qbar_shrink`。

4. **延後到 Task 11 前的 profiling pass 的效能項**（review 指出，皆非正確性、先量再優化）：
   - `_dcc_negloglik` 內迴圈每步跑 eigh-based `normalize_to_correlation`，但 Q_t 本就 PD——可換便宜的對角 rescale（`R=Q/outer(√diagQ,√diagQ)`），公開 API 仍用 normalize。
   - `VolForecaster.filter` 的 GARCH 分支每次呼叫 `garch_filter_forecast` 與 `garch_filter_residuals` 各建一次 arch+`fix()`（同窗同參數，2×）。可合成單一 `fix()` 同時回 (variance_path, std_resid)。filter 每 5 交易日/每持有檔跑一次，ablation 重跑多次會放大。
   - profiling 若顯示這兩處佔比小則不動（避免臆測性優化）。

5. **Task 9 review checkpoint（殘差新鮮度契約）**：`last_standardized_residuals` 讀快取、無新鮮度守護。Task 9 的 `_collect_std_residuals` 組完 date×ticker 矩陣後須**斷言矩陣最後一列日期＝決策當日**（view 的 as-of），把「漏對某 selected 檔 refit/filter → 吃到前一次 selection 的 stale 殘差」變成誠實失敗（INV-3 只驗 Σ 代數性質、驗不到輸入新鮮度）。

---

## File Structure

**新建：**
- `quantcore/models/correlation/__init__.py` — 子套件出口
- `quantcore/models/correlation/base.py` — `normalize_to_correlation`（R 合法性單一出口）
- `quantcore/models/correlation/ewma_corr.py` — `ewma_correlation`（基線）
- `quantcore/models/correlation/dcc.py` — `DccParams` / `_q_bar` / `dcc_recursion` / `estimate_dcc`
- `quantcore/models/correlation/forecaster.py` — `CorrelationForecaster`（refit/filter）
- `tests/test_models/test_correlation.py`
- `tests/test_models/test_dcc_recovery.py`（合成回收，正確性核心）
- `tests/test_models/test_correlation_forecaster.py`

**修改：**
- `quantcore/models/covariance.py` — `_project_to_psd_correlation` 改引用 `correlation/base`；`rolling_correlation` 退役；docstring 去「過渡」
- `quantcore/models/volatility/garch_arch.py` — 加 `garch_filter_residuals`
- `quantcore/models/volatility/forecaster.py` — 快取殘差 + `last_standardized_residuals`
- `quantcore/config/schema.py` — `RiskConfig` 加 `dcc_refit_interval` / `dcc_fixed_ab`
- `quantcore/config/default.yaml` — `corr_model: dcc→ewma`，加兩鍵
- `quantcore/backtest/strategies/vol_target_base.py` — 接 `CorrelationForecaster` + `_collect_std_residuals`
- `tests/test_invariants/test_covariance_valid.py` — 擴充 DCC/EWMA R 來源
- `tests/test_config.py` — 新鍵驗證
- `tests/test_backtest/test_vol_target_base.py`（或既有對應檔）— 接線後仍綠

**依賴方向檢查（CLAUDE.md）：** `correlation/` 屬 `models`，收/回 numpy·pandas，不 import backtest 型別。`vol_target_base` 屬 backtest，可 import models。✅

---

## Task 1: `correlation/base.py` — R 合法性單一出口

**Files:**
- Create: `quantcore/models/correlation/__init__.py`（空檔）
- Create: `quantcore/models/correlation/base.py`
- Test: `tests/test_models/test_correlation.py`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_models/test_correlation.py
import numpy as np

from quantcore.models.correlation.base import normalize_to_correlation


def test_normalize_valid_correlation_is_near_identity():
    # 已是合法相關矩陣：正規化近乎恆等
    R = np.array([[1.0, 0.3, -0.2], [0.3, 1.0, 0.1], [-0.2, 0.1, 1.0]])
    out = normalize_to_correlation(R)
    assert np.allclose(out, R, atol=1e-10)


def test_normalize_projects_non_psd_to_valid_correlation():
    # 刻意非 PSD（最小特徵值 < 0）→ 輸出對稱、PSD、單位對角
    bad = np.array([[1.0, 0.9, 0.9], [0.9, 1.0, -0.9], [0.9, -0.9, 1.0]])
    out = normalize_to_correlation(bad)
    assert np.allclose(out, out.T, atol=1e-12)  # 對稱
    assert np.min(np.linalg.eigvalsh(out)) >= -1e-10  # PSD
    assert np.allclose(np.diag(out), 1.0, atol=1e-10)  # 單位對角


def test_normalize_covariance_like_input_returns_correlation():
    # 非單位對角的 Q（DCC 的 Q_t）→ 正規化為相關矩陣
    Q = np.array([[4.0, 1.0], [1.0, 9.0]])
    out = normalize_to_correlation(Q)
    assert np.allclose(np.diag(out), 1.0)
    assert np.isclose(out[0, 1], 1.0 / np.sqrt(4.0 * 9.0))
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_models/test_correlation.py -v`
Expected: FAIL（`ModuleNotFoundError: quantcore.models.correlation`）

- [ ] **Step 3: 建子套件與 base.py**

```python
# quantcore/models/correlation/__init__.py
# （空檔，標記子套件）
```

```python
# quantcore/models/correlation/base.py
"""相關矩陣合法性的單一出口（規格 §5.3、INV-3）。

DCC 的 Q_t 與 EWMA 的 S_t 都經此正規化為合法相關矩陣（對稱/PSD/單位對角）——
呼叫端拿不到非法 R。與 covariance.build_covariance 的 Σ 投影本是同一數學，統一於此。
"""

from __future__ import annotations

import numpy as np


def normalize_to_correlation(M: np.ndarray) -> np.ndarray:
    """收對稱（近似）方陣 M（相關或 Q_t/S_t），回合法相關矩陣。

    對稱化 → 截負特徵值（PSD）→ 正規化對角線為 1。輸出恆對稱、PSD、單位對角。
    """
    M = (np.asarray(M, dtype="float64") + np.asarray(M, dtype="float64").T) / 2.0
    vals, vecs = np.linalg.eigh(M)
    vals = np.clip(vals, 0.0, None)
    M_psd = (vecs * vals) @ vecs.T
    d = np.sqrt(np.diag(M_psd))
    d[d == 0.0] = 1.0  # 僅整列落在被截零特徵空間才觸發；正常資料不可達
    R = M_psd / np.outer(d, d)
    return (R + R.T) / 2.0  # 數值再對稱化
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_models/test_correlation.py -v`
Expected: PASS（3 項）

- [ ] **Step 5: commit**

```bash
git add quantcore/models/correlation/__init__.py quantcore/models/correlation/base.py tests/test_models/test_correlation.py
git commit -m "feat(phase5a): correlation/base normalize_to_correlation（R 合法性單一出口，INV-3）"
```

---

## Task 2: `correlation/ewma_corr.py` — EWMA 相關基線

**Files:**
- Create: `quantcore/models/correlation/ewma_corr.py`
- Test: `tests/test_models/test_correlation.py`（續加）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_models/test_correlation.py（append）
import pandas as pd

from quantcore.models.correlation.ewma_corr import ewma_correlation


def _resid_frame():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2020-01-01", periods=200, freq="B")
    data = rng.standard_normal((200, 3))
    return pd.DataFrame(data, index=idx, columns=["B", "A", "C"])


def test_ewma_correlation_returns_valid_labeled_correlation():
    R = ewma_correlation(_resid_frame(), lam=0.94)
    assert list(R.columns) == ["A", "B", "C"]  # 依 label 排序
    assert list(R.index) == ["A", "B", "C"]
    assert np.allclose(np.diag(R.to_numpy()), 1.0)
    assert np.min(np.linalg.eigvalsh(R.to_numpy())) >= -1e-10


def test_ewma_first_step_matches_hand_recursion():
    # S_0 = 樣本共變異數；S_1 = (1-λ) e_0 e_0' + λ S_0；R = normalize(S_last)
    idx = pd.date_range("2020-01-01", periods=3, freq="B")
    E = pd.DataFrame([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], index=idx, columns=["A", "B"])
    lam = 0.9
    arr = E.to_numpy()
    S = np.cov(arr, rowvar=False)
    for t in range(1, len(arr)):
        e = arr[t - 1][:, None]
        S = (1 - lam) * (e @ e.T) + lam * S
    from quantcore.models.correlation.base import normalize_to_correlation

    expected = normalize_to_correlation(S)
    got = ewma_correlation(E, lam=lam).to_numpy()
    assert np.allclose(got, expected, atol=1e-12)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_models/test_correlation.py -k ewma -v`
Expected: FAIL（`ModuleNotFoundError` / `ImportError`）

- [ ] **Step 3: 實作**

```python
# quantcore/models/correlation/ewma_corr.py
"""RiskMetrics EWMA 相關（λ=0.94，規格 §5.3）。DCC 必須在消融中打敗此基線。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantcore.models.correlation.base import normalize_to_correlation


def ewma_correlation(std_resid: pd.DataFrame, lam: float) -> pd.DataFrame:
    """收 date×ticker 標準化殘差，回 EWMA 相關矩陣（label-aligned，依 ticker 排序）。

    S_0 = 樣本共變異數；S_t = (1−λ)·ε_{t−1}ε_{t−1}' + λ·S_{t−1}；R = normalize(S_last)。
    無待估參數（λ 固定）。
    """
    if not 0 < lam < 1:
        raise ValueError(f"EWMA λ 必須落在 (0,1)，收到 {lam}")
    cols = sorted(std_resid.columns)
    E = std_resid[cols].dropna().to_numpy(dtype="float64")
    if len(E) < 2:
        raise ValueError("ewma_correlation 需至少 2 筆觀測")
    S = np.atleast_2d(np.cov(E, rowvar=False))
    for t in range(1, len(E)):
        e = E[t - 1][:, None]
        S = (1 - lam) * (e @ e.T) + lam * S
    R = normalize_to_correlation(S)
    return pd.DataFrame(R, index=cols, columns=cols)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_models/test_correlation.py -v`
Expected: PASS

- [ ] **Step 5: commit**

```bash
git add quantcore/models/correlation/ewma_corr.py tests/test_models/test_correlation.py
git commit -m "feat(phase5a): ewma_correlation 相關基線（§5.3，DCC 須打敗它）"
```

---

## Task 3: `correlation/dcc.py` — Q̄、Q_t 遞迴、R 正規化

**Files:**
- Create: `quantcore/models/correlation/dcc.py`
- Test: `tests/test_models/test_correlation.py`（續加）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_models/test_correlation.py（append）
from quantcore.models.correlation.dcc import DccParams, dcc_recursion, q_bar


def test_q_bar_shrinks_toward_identity():
    E = _resid_frame()
    Q = q_bar(E)
    assert np.allclose(Q, Q.T)
    assert np.min(np.linalg.eigvalsh(Q)) > 0  # shrink 後正定
    # 對角線 ≈ 1（相關矩陣 shrink 到單位對角仍為 1）
    assert np.allclose(np.diag(Q), 1.0, atol=1e-10)


def test_dcc_recursion_first_step_matches_hand():
    idx = pd.date_range("2020-01-01", periods=3, freq="B")
    E = pd.DataFrame([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], index=idx, columns=["A", "B"])
    Qbar = q_bar(E)
    a, b = 0.05, 0.90
    Q = Qbar.copy()
    arr = E.to_numpy()
    for t in range(1, len(arr)):
        e = arr[t - 1][:, None]
        Q = (1 - a - b) * Qbar + a * (e @ e.T) + b * Q
    from quantcore.models.correlation.base import normalize_to_correlation

    expected = normalize_to_correlation(Q)
    got = dcc_recursion(E, DccParams(a=a, b=b, q_bar=Qbar)).to_numpy()
    assert np.allclose(got, expected, atol=1e-12)


def test_dcc_recursion_returns_valid_labeled_correlation():
    R = dcc_recursion(_resid_frame(), DccParams(a=0.05, b=0.9, q_bar=q_bar(_resid_frame())))
    assert list(R.columns) == ["A", "B", "C"]
    assert np.allclose(np.diag(R.to_numpy()), 1.0)
    assert np.min(np.linalg.eigvalsh(R.to_numpy())) >= -1e-10
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_models/test_correlation.py -k "dcc or q_bar" -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 實作**

```python
# quantcore/models/correlation/dcc.py
"""DCC(1,1) 兩步 QMLE 的第二步（規格 §5.3）。

單變量 σ_t 由既有 GARCH 提供（標準化殘差為輸入）；本模組做 Q̄、Q_t 遞迴、
(a,b) QMLE、R 正規化。對稱化/shrinkage/正規化全封在此——呼叫端拿不到非法矩陣。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantcore.models.correlation.base import normalize_to_correlation

_QBAR_SHRINK = 0.10  # Q̄ 向單位對角收縮係數（小樣本病態防護；plan 值，可消融）


@dataclass(frozen=True)
class DccParams:
    a: float
    b: float
    q_bar: np.ndarray  # 標準化殘差的（shrink 後）樣本相關


def _resid_matrix(std_resid: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    cols = sorted(std_resid.columns)
    E = std_resid[cols].dropna().to_numpy(dtype="float64")
    if len(E) < 2:
        raise ValueError("DCC 需至少 2 筆觀測")
    return cols, E


def q_bar(std_resid: pd.DataFrame) -> np.ndarray:
    """Q̄ = (1−δ)·樣本相關 + δ·I（δ=_QBAR_SHRINK），對稱正定。"""
    _, E = _resid_matrix(std_resid)
    C = np.atleast_2d(np.corrcoef(E, rowvar=False))
    if not np.isfinite(C).all():
        raise ValueError("Q̄：標準化殘差樣本相關含非有限值（零變異數殘差）")
    k = C.shape[0]
    return (1 - _QBAR_SHRINK) * C + _QBAR_SHRINK * np.eye(k)


def dcc_recursion(std_resid: pd.DataFrame, params: DccParams) -> pd.DataFrame:
    """Q_t = (1−a−b)Q̄ + a·ε_{t−1}ε_{t−1}' + b·Q_{t−1}，Q_0=Q̄；回 last 的 R（label-aligned）。"""
    cols, E = _resid_matrix(std_resid)
    a, b, Qbar = params.a, params.b, params.q_bar
    Q = Qbar.copy()
    for t in range(1, len(E)):
        e = E[t - 1][:, None]
        Q = (1 - a - b) * Qbar + a * (e @ e.T) + b * Q
    R = normalize_to_correlation(Q)
    return pd.DataFrame(R, index=cols, columns=cols)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_models/test_correlation.py -v`
Expected: PASS

- [ ] **Step 5: commit**

```bash
git add quantcore/models/correlation/dcc.py tests/test_models/test_correlation.py
git commit -m "feat(phase5a): DCC Q̄/Q_t 遞迴/R 正規化（§5.3，第二步核心）"
```

---

## Task 4: `correlation/dcc.py` — `estimate_dcc`（QMLE (a,b)）

**Files:**
- Modify: `quantcore/models/correlation/dcc.py`
- Test: `tests/test_models/test_correlation.py`（續加）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_models/test_correlation.py（append）
from quantcore.models.correlation.dcc import estimate_dcc


def test_estimate_dcc_returns_valid_params():
    params = estimate_dcc(_resid_frame(), fixed_ab=(0.01, 0.96))
    assert params.a >= 0 and params.b >= 0
    assert params.a + params.b < 1.0
    assert params.q_bar.shape == (3, 3)


def test_estimate_dcc_degenerate_falls_back_to_fixed():
    # 單筆有效觀測（dropna 後 < 2）→ 誠實退回 fixed_ab（不拋錯中斷）
    idx = pd.date_range("2020-01-01", periods=2, freq="B")
    E = pd.DataFrame([[np.nan, np.nan], [1.0, 1.0]], index=idx, columns=["A", "B"])
    params = estimate_dcc(E, fixed_ab=(0.01, 0.96))
    assert (params.a, params.b) == (0.01, 0.96)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_models/test_correlation.py -k estimate -v`
Expected: FAIL（`ImportError: cannot import name 'estimate_dcc'`）

- [ ] **Step 3: 實作（append 到 dcc.py）**

```python
# quantcore/models/correlation/dcc.py（append）
from scipy.optimize import minimize

_A_START, _B_START = 0.02, 0.95  # QMLE 固定起點（決定性，不吃亂數，INV-6）
_AB_UPPER = 0.999  # a+b 上界（保平穩）


def _dcc_negloglik(theta: np.ndarray, E: np.ndarray, Qbar: np.ndarray) -> float:
    """DCC 準似然（僅相關部分）：Σ_t [log|R_t| + ε_t' R_t^{-1} ε_t]。"""
    a, b = float(theta[0]), float(theta[1])
    if a < 0 or b < 0 or a + b >= _AB_UPPER:
        return 1e12  # 不可行區重罰
    Q = Qbar.copy()
    total = 0.0
    for t in range(len(E)):
        if t > 0:
            e_prev = E[t - 1][:, None]
            Q = (1 - a - b) * Qbar + a * (e_prev @ e_prev.T) + b * Q
        R = normalize_to_correlation(Q)
        e = E[t][:, None]
        sign, logdet = np.linalg.slogdet(R)
        if sign <= 0 or not np.isfinite(logdet):
            return 1e12
        quad = float(e.T @ np.linalg.solve(R, e))
        total += logdet + quad
    return total


def estimate_dcc(std_resid: pd.DataFrame, fixed_ab: tuple[float, float]) -> DccParams:
    """QMLE 估 (a,b)；不收斂 / a+b≥1 / 非有限 → 退回 fixed_ab（誠實 fallback，比照 4a）。"""
    try:
        cols, E = _resid_matrix(std_resid)
        Qbar = q_bar(std_resid)
    except ValueError:
        # 樣本不足以估 Q̄：用 fixed_ab + 退化 Q̄=I（維度取自欄數）
        k = len(std_resid.columns)
        return DccParams(*fixed_ab, np.eye(k))
    res = minimize(
        _dcc_negloglik,
        x0=np.array([_A_START, _B_START], dtype="float64"),
        args=(E, Qbar),
        method="SLSQP",
        bounds=[(0.0, _AB_UPPER), (0.0, _AB_UPPER)],
        constraints=[{"type": "ineq", "fun": lambda x: _AB_UPPER - x[0] - x[1]}],
        options={"maxiter": 200, "ftol": 1e-8},
    )
    a, b = float(res.x[0]), float(res.x[1])
    ok = bool(res.success) and np.isfinite([a, b]).all() and a >= 0 and b >= 0 and a + b < 1.0
    if not ok:
        return DccParams(*fixed_ab, Qbar)
    return DccParams(a=a, b=b, q_bar=Qbar)
```

同步更新 dcc.py 頂部 import：把 `from scipy.optimize import minimize` 併到檔案頂端 import 區（不要留在檔中段）。

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_models/test_correlation.py -v`
Expected: PASS

- [ ] **Step 5: commit**

```bash
git add quantcore/models/correlation/dcc.py tests/test_models/test_correlation.py
git commit -m "feat(phase5a): estimate_dcc QMLE (a,b) + 誠實 fallback"
```

---

## Task 5: 合成回收測試（DCC 正確性核心）

**Files:**
- Create: `tests/test_models/test_dcc_recovery.py`

- [ ] **Step 1: 寫測試（先 RED：容差內回收）**

```python
# tests/test_models/test_dcc_recovery.py
"""合成回收：模擬已知 (a*,b*,R̄*) 的 DCC(1,1) 過程，QMLE 應回收到容差內。

手寫 DCC 無 arch 那樣的 parity 參照，故以「已知真值 → 能否估回」建立正確性信心（§5a AC-2）。
"""

import numpy as np
import pandas as pd

from quantcore.models.correlation.dcc import estimate_dcc


def _simulate_dcc(a, b, R_bar, n, seed):
    """以 DCC(1,1) 動態生成標準化殘差 ε_t（單位條件變異數，相關由 R_t 驅動）。"""
    rng = np.random.default_rng(seed)
    k = R_bar.shape[0]
    Q = R_bar.copy()
    Qbar = R_bar.copy()
    E = np.empty((n, k), dtype="float64")
    e_prev = np.zeros((k, 1))
    for t in range(n):
        Q = (1 - a - b) * Qbar + a * (e_prev @ e_prev.T) + b * Q
        d = np.sqrt(np.diag(Q))
        R = Q / np.outer(d, d)
        L = np.linalg.cholesky(R + 1e-10 * np.eye(k))
        z = rng.standard_normal((k, 1))
        e = L @ z
        E[t] = e.ravel()
        e_prev = e
    idx = pd.date_range("2005-01-03", periods=n, freq="B")
    return pd.DataFrame(E, index=idx, columns=["A", "B", "C"])


def test_qmle_recovers_known_ab_within_tolerance():
    a_true, b_true = 0.05, 0.90
    R_bar = np.array([[1.0, 0.4, 0.2], [0.4, 1.0, 0.3], [0.2, 0.3, 1.0]])
    E = _simulate_dcc(a_true, b_true, R_bar, n=3000, seed=42)
    params = estimate_dcc(E, fixed_ab=(0.01, 0.96))
    # QMLE 於 3000 樣本的合理界；persistence (a+b) 通常較 a/b 個別更準
    assert abs(params.a - a_true) < 0.04
    assert abs(params.b - b_true) < 0.06
    assert abs((params.a + params.b) - (a_true + b_true)) < 0.03
```

- [ ] **Step 2: 跑測試**

Run: `uv run pytest tests/test_models/test_dcc_recovery.py -v`
Expected: PASS（若容差過緊致偶發失敗，先確認 point estimate 方向正確再放寬容差註明——不可為過關而放寬到失去鑑別力；容差須仍能抓出「回收到完全錯的參數」）。

- [ ] **Step 3: commit**

```bash
git add tests/test_models/test_dcc_recovery.py
git commit -m "test(phase5a): DCC 合成回收（已知 a,b 於 3000 樣本可估回，正確性核心）"
```

---

## Task 6: `VolForecaster` 快取標準化殘差

**Files:**
- Modify: `quantcore/models/volatility/garch_arch.py`（加 `garch_filter_residuals`）
- Modify: `quantcore/models/volatility/forecaster.py`
- Test: `tests/test_models/test_forecaster.py`（續加）、`tests/test_models/test_garch_arch.py`（續加）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_models/test_forecaster.py（append）
import numpy as np
import pandas as pd

from quantcore.models.volatility.forecaster import VolForecaster


def _garch_like_series(n=400, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    return pd.Series(rng.standard_normal(n) * 0.01, index=idx)


def test_refit_caches_standardized_residuals_with_index():
    fc = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    r = _garch_like_series()
    fc.refit("SPY", r)
    resid = fc.last_standardized_residuals("SPY")
    assert isinstance(resid, pd.Series)
    assert isinstance(resid.index, pd.DatetimeIndex)
    assert np.isfinite(resid.to_numpy()).all()
    # 標準化殘差量級 ~O(1)
    assert 0.3 < resid.std() < 3.0


def test_filter_updates_standardized_residuals_cache():
    fc = VolForecaster("garch_arch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    r = _garch_like_series()
    fc.refit("SPY", r)
    r2 = pd.concat([r, _garch_like_series(5, seed=2).tail(5)])
    fc.filter("SPY", r2)
    resid = fc.last_standardized_residuals("SPY")
    assert resid.index[-1] == r2.index[-1]  # filter 後殘差含最新日
```

```python
# tests/test_models/test_garch_arch.py（append）
def test_garch_filter_residuals_matches_scale():
    from quantcore.models.volatility.garch_arch import GarchArch, garch_filter_residuals

    rng = np.random.default_rng(3)
    idx = pd.date_range("2018-01-01", periods=300, freq="B")
    r = pd.Series(rng.standard_normal(300) * 0.01, index=idx)
    m = GarchArch().fit(r)
    resid = garch_filter_residuals(m.arch_params, r)
    # 同參數同資料 → 與 fit 的 standardized_residuals 一致
    assert np.allclose(resid.to_numpy(), m.standardized_residuals.to_numpy(), atol=1e-8)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_models/test_forecaster.py -k residual tests/test_models/test_garch_arch.py -k filter_residuals -v`
Expected: FAIL（`AttributeError: last_standardized_residuals` / `ImportError: garch_filter_residuals`）

- [ ] **Step 3: 實作 garch_filter_residuals**

```python
# quantcore/models/volatility/garch_arch.py（append，緊鄰 garch_filter_forecast）
def garch_filter_residuals(fixed_params: np.ndarray, returns: pd.Series) -> pd.Series:
    """以固定 arch 參數濾波，回標準化殘差 r_t/σ_t（帶 DatetimeIndex，供 DCC）。

    與 GarchArch.standardized_residuals 同定義（scaled_return / 條件波動），
    但用固定參數（不跑 MLE）——曝險檢查日的便宜路徑。
    """
    r = returns.astype("float64").dropna()
    am = _build_arch_model(r.to_numpy() * _SCALE)
    res = am.fix(np.asarray(fixed_params, dtype="float64"))
    cond_vol = np.asarray(res.conditional_volatility, dtype="float64")
    return pd.Series(r.to_numpy() * _SCALE / cond_vol, index=r.index)
```

- [ ] **Step 4: 實作 VolForecaster 殘差快取**

```python
# quantcore/models/volatility/forecaster.py
# 4-1. import 區加：
from quantcore.models.volatility.garch_arch import (
    GarchArch,
    garch_filter_forecast,
    garch_filter_residuals,
)

# 4-2. __init__ 加殘差快取：
        self._resid: dict[str, pd.Series] = {}

# 4-3. refit 末段（return 前）加：
        self._resid[ticker] = outcome.model.standardized_residuals

# 4-4. filter 的 garch 分支：算 σ̂ 前後補殘差快取
        if entry.kind == "garch":
            self._resid[ticker] = garch_filter_residuals(entry.arch_params, window)
            return annualize_variance_path(
                garch_filter_forecast(entry.arch_params, window, self._horizon)
            )
        outcome = fit_volatility("ewma", window, ewma_lambda=self._ewma_lambda)
        self._resid[ticker] = outcome.model.standardized_residuals
        return annualized_forecast_vol(outcome.model, self._horizon)

# 4-5. 新增方法：
    def last_standardized_residuals(self, ticker: str) -> pd.Series:
        """該 ticker 上次 refit/filter 的標準化殘差序列（供 CorrelationForecaster）。"""
        return self._resid[ticker]
```

> 注意：`refit` 內 `outcome` 在 GARCH/EWMA 兩分支都存在（見現有碼），故 4-3 放在兩分支之後、
> `return annualized_forecast_vol(...)` 之前即可涵蓋兩路。

- [ ] **Step 5: 跑測試確認通過**

Run: `uv run pytest tests/test_models/test_forecaster.py tests/test_models/test_garch_arch.py -v`
Expected: PASS（含既有測試不回歸）

- [ ] **Step 6: commit**

```bash
git add quantcore/models/volatility/garch_arch.py quantcore/models/volatility/forecaster.py tests/test_models/test_forecaster.py tests/test_models/test_garch_arch.py
git commit -m "feat(phase5a): VolForecaster 快取標準化殘差 + garch_filter_residuals（DCC 輸入管線）"
```

---

## Task 7: `CorrelationForecaster`（refit/filter + 節奏 + fixed/reestimate）

**Files:**
- Create: `quantcore/models/correlation/forecaster.py`
- Test: `tests/test_models/test_correlation_forecaster.py`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_models/test_correlation_forecaster.py
import numpy as np
import pandas as pd

from quantcore.models.correlation.forecaster import CorrelationForecaster


def _resid(cols, n=200, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame(rng.standard_normal((n, len(cols))), index=idx, columns=cols)


def test_ewma_mode_returns_valid_correlation():
    fc = CorrelationForecaster("ewma", 0.94, refit_interval=63, fixed_ab=(0.01, 0.96), selection_interval=21)
    R = fc.refit(_resid(["A", "B", "C"]))
    assert np.allclose(np.diag(R.to_numpy()), 1.0)
    assert np.min(np.linalg.eigvalsh(R.to_numpy())) >= -1e-10


def test_fixed_mode_never_reestimates():
    fc = CorrelationForecaster("dcc", 0.94, refit_interval=0, fixed_ab=(0.01, 0.96), selection_interval=21)
    fc.refit(_resid(["A", "B"], seed=1))
    assert fc.last_params().a == 0.01 and fc.last_params().b == 0.96
    fc.refit(_resid(["A", "B"], seed=2))  # 換資料再選
    assert fc.last_params().a == 0.01 and fc.last_params().b == 0.96  # a,b 恆不變


def test_reestimate_cadence_every_third_selection():
    # refit_interval=63, selection_interval=21 → 每 3 次選擇重估 (a,b)
    fc = CorrelationForecaster("dcc", 0.94, refit_interval=63, fixed_ab=(0.01, 0.96), selection_interval=21)
    fc.refit(_resid(["A", "B"], seed=1))  # 第 1 次：估
    ab1 = (fc.last_params().a, fc.last_params().b)
    fc.refit(_resid(["A", "B"], seed=2))  # 第 2 次：沿用
    ab2 = (fc.last_params().a, fc.last_params().b)
    assert ab2 == ab1  # (a,b) 未重估
    fc.refit(_resid(["A", "B"], seed=3))  # 第 3 次：沿用
    fc.refit(_resid(["A", "B"], seed=4))  # 第 4 次：重估（可能不同）
    # 第 4 次為新估計點（不強制數值不同，但 Q̄ 已隨資料更新）
    assert fc.last_params().q_bar.shape == (2, 2)


def test_filter_reuses_cached_params():
    fc = CorrelationForecaster("dcc", 0.94, refit_interval=63, fixed_ab=(0.01, 0.96), selection_interval=21)
    fc.refit(_resid(["A", "B"], seed=1))
    ab = (fc.last_params().a, fc.last_params().b)
    R = fc.filter(_resid(["A", "B"], seed=9))
    assert (fc.last_params().a, fc.last_params().b) == ab  # filter 不重估
    assert np.allclose(np.diag(R.to_numpy()), 1.0)


def test_selection_rebuilds_qbar_for_rotated_universe():
    fc = CorrelationForecaster("dcc", 0.94, refit_interval=63, fixed_ab=(0.01, 0.96), selection_interval=21)
    fc.refit(_resid(["A", "B"], seed=1))
    assert fc.last_params().q_bar.shape == (2, 2)
    fc.refit(_resid(["A", "B", "C"], seed=2))  # 換入新資產
    assert fc.last_params().q_bar.shape == (3, 3)  # Q̄ 隨新集合重建
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_models/test_correlation_forecaster.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 實作**

```python
# quantcore/models/correlation/forecaster.py
"""相關預報器 refit/filter（規格 §5.3，鏡射 VolForecaster）。

貴的 (a,b) QMLE 週期重估（每 refit_interval 交易日 = 每 estimate_every 次選擇）、
便宜的 Q_t 遞迴每次決策。ewma 模式無待估參數。有狀態，策略每 run 新建（不破 INV-6）。
"""

from __future__ import annotations

import pandas as pd

from quantcore.models.correlation.dcc import DccParams, dcc_recursion, estimate_dcc, q_bar
from quantcore.models.correlation.ewma_corr import ewma_correlation


class CorrelationForecaster:
    def __init__(
        self,
        corr_model: str,
        ewma_lambda: float,
        refit_interval: int,
        fixed_ab: tuple[float, float],
        selection_interval: int,
    ) -> None:
        if corr_model not in ("dcc", "ewma"):
            raise ValueError(f"CorrelationForecaster 不支援 corr_model={corr_model!r}")
        self._model = corr_model
        self._lam = ewma_lambda
        self._refit_interval = refit_interval
        self._fixed_ab = fixed_ab
        # 63÷21=3：每 3 次選擇重估 (a,b)。fixed 模式（refit_interval==0）不重估。
        self._estimate_every = max(1, round(refit_interval / selection_interval))
        self._n_sel = 0
        self._params: DccParams | None = None

    def refit(self, std_resid: pd.DataFrame) -> pd.DataFrame:
        """選擇日：ewma 直接算 R；dcc 依節奏重估或沿用 (a,b)，Q̄ 每次重算，回 R_t。"""
        if self._model == "ewma":
            return ewma_correlation(std_resid, self._lam)
        self._n_sel += 1
        reestimate = self._refit_interval > 0 and ((self._n_sel - 1) % self._estimate_every == 0)
        if reestimate or self._params is None:
            if self._refit_interval == 0:  # fixed 模式：(a,b) 固定、僅 Q̄
                self._params = DccParams(*self._fixed_ab, q_bar(std_resid))
            else:
                self._params = estimate_dcc(std_resid, self._fixed_ab)
        else:  # 沿用 (a,b)，Q̄ 隨（可能輪動的）資產集重算
            self._params = DccParams(self._params.a, self._params.b, q_bar(std_resid))
        return dcc_recursion(std_resid, self._params)

    def filter(self, std_resid: pd.DataFrame) -> pd.DataFrame:
        """曝險檢查日：ewma 直接算；dcc 沿用快取 (a,b,Q̄) 只推進遞迴，回 R_t（不重估）。"""
        if self._model == "ewma":
            return ewma_correlation(std_resid, self._lam)
        assert self._params is not None  # 選擇日必先 refit
        return dcc_recursion(std_resid, self._params)

    def last_params(self) -> DccParams | None:
        """供測試/診斷：dcc 回當前 DccParams；ewma 回 None。"""
        return self._params
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_models/test_correlation_forecaster.py -v`
Expected: PASS

- [ ] **Step 5: commit**

```bash
git add quantcore/models/correlation/forecaster.py tests/test_models/test_correlation_forecaster.py
git commit -m "feat(phase5a): CorrelationForecaster refit/filter（節奏 + fixed/reestimate，鏡射 VolForecaster）"
```

---

## Task 8: config — `dcc_refit_interval` / `dcc_fixed_ab` + 預設翻 ewma

**Files:**
- Modify: `quantcore/config/schema.py:53-67`（`RiskConfig`）
- Modify: `quantcore/config/default.yaml:19-29`（`risk`）
- Test: `tests/test_config.py`（續加）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_config.py（append）
import pytest
from pydantic import ValidationError

from quantcore.config import load_config


def test_default_corr_model_is_ewma(tmp_path):
    cfg = load_config("quantcore/config/default.yaml")
    assert cfg.risk.corr_model == "ewma"  # DCC 未證明前用基線（§5.3 紀律）
    assert cfg.risk.dcc_refit_interval == 63
    assert tuple(cfg.risk.dcc_fixed_ab) == (0.01, 0.96)


def test_dcc_fixed_ab_rejects_nonstationary(tmp_path, monkeypatch):
    from quantcore.config.schema import RiskConfig

    base = dict(
        vol_model="garch_arch", corr_model="dcc", vol_target_annual=0.1,
        exposure_band=0.1, exposure_min=0.1, vol_window=63, ewma_lambda=0.94,
        forecast_horizon=21, garch_window=1000, corr_window=252,
        dcc_refit_interval=63, dcc_fixed_ab=[0.5, 0.6],  # a+b=1.1 ≥ 1
    )
    with pytest.raises(ValidationError):
        RiskConfig(**base)


def test_dcc_refit_interval_zero_is_fixed_mode(tmp_path):
    from quantcore.config.schema import RiskConfig

    cfg = RiskConfig(
        vol_model="garch_arch", corr_model="dcc", vol_target_annual=0.1,
        exposure_band=0.1, exposure_min=0.1, vol_window=63, ewma_lambda=0.94,
        forecast_horizon=21, garch_window=1000, corr_window=252,
        dcc_refit_interval=0, dcc_fixed_ab=[0.01, 0.96],
    )
    assert cfg.dcc_refit_interval == 0  # 合法：固定模式
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_config.py -k "corr_model or dcc" -v`
Expected: FAIL（預設仍 dcc / 無 dcc_refit_interval 欄位）

- [ ] **Step 3: 改 schema.py（`RiskConfig` 末尾加欄位 + validator）**

```python
# quantcore/config/schema.py，RiskConfig 內 corr_window 之後加：
    dcc_refit_interval: int = Field(ge=0)  # >0=每 N 交易日重估 (a,b)；0=固定模式
    dcc_fixed_ab: tuple[float, float]  # 固定模式 (a,b)；亦為重估 fallback

    @model_validator(mode="after")
    def _dcc_fixed_ab_stationary(self) -> RiskConfig:
        a, b = self.dcc_fixed_ab
        if a < 0 or b < 0 or a + b >= 1.0:
            raise ValueError(f"risk.dcc_fixed_ab {(a, b)} 須 a≥0,b≥0,a+b<1（DCC 平穩）")
        return self
```

- [ ] **Step 4: 改 default.yaml（`risk` 區塊）**

```yaml
# quantcore/config/default.yaml，risk 區塊：
  corr_model: ewma                  # 【5a】DCC 未經消融證明前預設用已證基線（§5.3）。dcc | ewma
  # ... 其餘不動 ...
  dcc_refit_interval: 63            # §5.3 每 63 交易日重估 DCC (a,b)；設 0 = 固定模式（不估）
  dcc_fixed_ab: [0.01, 0.96]        # 固定模式 (a,b)（舊系統值）；亦為重估不收斂時 fallback
```

- [ ] **Step 5: 跑測試確認通過**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS（含既有 config 測試不回歸——注意既有測試若硬編 corr_model=="dcc" 需同步更新為 ewma）

- [ ] **Step 6: commit**

```bash
git add quantcore/config/schema.py quantcore/config/default.yaml tests/test_config.py
git commit -m "feat(phase5a): config dcc_refit_interval/dcc_fixed_ab + 預設 corr_model 翻 ewma"
```

---

## Task 9: covariance.py 收斂 + vol_target_base 接線

**Files:**
- Modify: `quantcore/models/covariance.py:24-34`（`_project_to_psd_correlation` 改引用 base）、`:14-21`（`rolling_correlation` 退役）
- Modify: `quantcore/backtest/strategies/vol_target_base.py`
- Test: `tests/test_backtest/test_vol_target_base.py`（或既有對應）、`tests/test_models/test_covariance.py`

- [ ] **Step 1: 寫失敗測試（接線後 full/voltarget 兩 corr_model 都跑得動）**

```python
# tests/test_backtest/test_vol_target_base.py（append；沿用既有合成 fixture 慣例）
import pandas as pd

from quantcore.backtest.strategies.full import Full
from quantcore.backtest.strategy import DecisionEvent


def test_full_decides_with_ewma_corr(mini_view_and_cfg):
    view, cfg = mini_view_and_cfg  # 既有合成 fixture（見 tests/fixtures/synthetic.py）
    cfg = cfg.model_copy(update={"risk": cfg.risk.model_copy(update={"corr_model": "ewma"})})
    strat = Full(cfg)
    dec = strat.decide(view, DecisionEvent.SELECTION)
    assert dec is not None
    assert abs(sum(dec.target_weights.values()) - 1.0) < 1e-9  # 權重恆和 1（INV-5）


def test_full_decides_with_dcc_corr(mini_view_and_cfg):
    view, cfg = mini_view_and_cfg
    cfg = cfg.model_copy(update={"risk": cfg.risk.model_copy(update={"corr_model": "dcc"})})
    strat = Full(cfg)
    dec = strat.decide(view, DecisionEvent.SELECTION)
    assert dec is not None
    assert dec.diagnostics.sigma_p is not None and dec.diagnostics.sigma_p > 0
```

> 若既有 fixture 名稱/形狀不同，執行時對齊既有 `tests/test_backtest/test_full.py` 的建構方式
> （用同一組合成 view + cfg），不要新造 fixture。

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_vol_target_base.py -k corr -v`
Expected: FAIL（`vol_target_base` 尚未用 CorrelationForecaster / 建構參數不符）

- [ ] **Step 3: covariance.py 收斂**

```python
# quantcore/models/covariance.py
# 3-1. docstring 去「過渡/placeholder」字樣，改述「Σ 唯一出口；R 由相關模型層提供」。
# 3-2. 刪除 _project_to_psd_correlation 函數本體，改從 base 引入：
from quantcore.models.correlation.base import normalize_to_correlation
# 3-3. build_covariance 內 `R_psd = _project_to_psd_correlation(Rv)` 改為：
    R_psd = normalize_to_correlation(Rv)
# 3-4. rolling_correlation：加 deprecation docstring「Phase 4 過渡，5a 起生產路徑改用
#      CorrelationForecaster；保留僅供既有測試/研究對照」。不刪除（避免動既有測試），但不再被策略引用。
```

- [ ] **Step 4: vol_target_base 接線**

```python
# quantcore/backtest/strategies/vol_target_base.py
# 4-1. import 區：
from quantcore.models.correlation.forecaster import CorrelationForecaster
# （移除對 rolling_correlation 的 import；build_covariance/portfolio_vol 保留）

# 4-2. __init__ 內（forecaster 之後）加相關預報器：
        self._corr = CorrelationForecaster(
            cfg.risk.corr_model,
            cfg.risk.ewma_lambda,
            cfg.risk.dcc_refit_interval,
            tuple(cfg.risk.dcc_fixed_ab),
            cfg.schedule.selection_interval,
        )

# 4-3. 新增殘差蒐集（selected 各檔的標準化殘差，按日交集對齊）：
    def _collect_std_residuals(self, selected: list[str]) -> pd.DataFrame:
        series = {t: self._forecaster.last_standardized_residuals(t) for t in selected}
        mat = pd.concat(series, axis=1)
        mat.columns = list(series.keys())
        return mat.dropna()

# 4-4. decide() 內把
#        window = _selected_returns_window(view, state.selected, cfg.risk.corr_window)
#        R = rolling_correlation(window)
#      改為：
        std_resid = self._collect_std_residuals(state.selected)
        R = (
            self._corr.refit(std_resid)
            if event is DecisionEvent.SELECTION
            else self._corr.filter(std_resid)
        )
# 4-5. 刪除 _selected_returns_window（不再使用）。
```

> **順序保證**：σ̂ 的 refit/filter 在 `_select_and_weight`（refit）與 `_refilter`（filter）
> 已先於 decide 尾段執行 → 殘差此時已快取。`_collect_std_residuals` 讀快取安全。

- [ ] **Step 5: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/ tests/test_models/test_covariance.py -v`
Expected: PASS（含既有 full/voltarget 測試不回歸）

- [ ] **Step 6: commit**

```bash
git add quantcore/models/covariance.py quantcore/backtest/strategies/vol_target_base.py tests/test_backtest/test_vol_target_base.py tests/test_models/test_covariance.py
git commit -m "feat(phase5a): covariance 唯一出口收斂 + vol_target_base 接 CorrelationForecaster（rolling 退役）"
```

---

## Task 10: 擴充 INV-3 守護（DCC/EWMA R 來源）

**Files:**
- Modify: `tests/test_invariants/test_covariance_valid.py`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_invariants/test_covariance_valid.py（append）
import numpy as np
import pandas as pd

from quantcore.models.correlation.dcc import DccParams, dcc_recursion, q_bar
from quantcore.models.correlation.ewma_corr import ewma_correlation
from quantcore.models.covariance import build_covariance


def _resid(n=200, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame(rng.standard_normal((n, 3)), index=idx, columns=["A", "B", "C"])


def test_inv3_holds_with_dcc_R():
    E = _resid()
    R = dcc_recursion(E, DccParams(0.05, 0.9, q_bar(E)))
    sigma = {"A": 0.15, "B": 0.20, "C": 0.10}
    Sigma = build_covariance(sigma, R).to_numpy()
    assert np.allclose(Sigma, Sigma.T)  # 對稱
    assert np.min(np.linalg.eigvalsh(Sigma)) >= -1e-10  # PSD
    assert np.allclose(np.diag(Sigma), [0.15**2, 0.20**2, 0.10**2])  # 對角線=σ_i²


def test_inv3_holds_with_ewma_R():
    E = _resid()
    R = ewma_correlation(E, lam=0.94)
    sigma = {"A": 0.15, "B": 0.20, "C": 0.10}
    Sigma = build_covariance(sigma, R).to_numpy()
    assert np.min(np.linalg.eigvalsh(Sigma)) >= -1e-10
    assert np.allclose(np.diag(Sigma), [0.15**2, 0.20**2, 0.10**2])
```

- [ ] **Step 2: 跑測試**

Run: `uv run pytest tests/test_invariants/test_covariance_valid.py -v`
Expected: PASS（DCC/EWMA 的 R 經 build_covariance 後 INV-3 三性質成立）

- [ ] **Step 3: commit**

```bash
git add tests/test_invariants/test_covariance_valid.py
git commit -m "test(phase5a): INV-3 守護擴充至 DCC/EWMA R 來源"
```

---

## Task 11: 消融 + AC 量測（本機閘門）

**Files:**
- Modify: `quantcore/experiments/ablation.py`（掃 `corr_model`/`dcc_refit_interval`）
- Create: `tests/test_experiments/test_phase5a_ac.py`（`requires_snapshot`）
- Modify: `PROGRESS.md`（結論寫入）

- [ ] **Step 1: 確認消融引擎已能掃 risk 子參數**

Run: `uv run pytest tests/test_experiments/test_ablation.py -v`
檢視 `experiments/ablation.py` 的參數格介面（Phase 3 建的通用引擎，「一次動一參數」）。
若已支援 `risk.corr_model` / `risk.dcc_refit_interval` 掃格則不需改；否則加對應派發（沿用既有格點寫法，不新造框架）。

- [ ] **Step 2: 寫 AC 量測測試（`requires_snapshot` 本機閘門）**

```python
# tests/test_experiments/test_phase5a_ac.py
"""Phase 5a AC 本機閘門（CI 無快照乾淨 skip，比照 Phase 4）。"""

import pytest

pytestmark = pytest.mark.requires_snapshot


def test_full_runs_under_both_corr_models(snapshot_cfg):
    """full 在 corr_model ∈ {ewma, dcc} 下皆跑完整回測、σ̂_p 有限、已實現波動落合理域。"""
    from quantcore.experiments.runner import run_single

    for corr in ("ewma", "dcc"):
        cfg = snapshot_cfg.model_copy(
            update={"risk": snapshot_cfg.risk.model_copy(update={"corr_model": corr})}
        )
        result = run_single(cfg, strategy_id="full")
        realized_vol = result.metrics["annualized_vol"]
        assert 0.05 < realized_vol < 0.20  # 波動目標 σ*=10% 附近的寬合理域
```

> `snapshot_cfg` / `run_single` 對齊既有 `tests/test_experiments/test_phase4_ac.py` 的 fixture 與
> 呼叫方式；若名稱不同照既有檔調整（不新造）。

- [ ] **Step 3: 跑 AC 閘門（本機有快照）**

Run: `uv run pytest tests/test_experiments/test_phase5a_ac.py -v`
Expected: PASS（本機）；CI 無 parquet → skip。

- [ ] **Step 4: 跑消融、記錄 DCC vs EWMA 結論**

Run（本機）：以既有消融 CLI/驅動跑 `corr_model ∈ {ewma, dcc}` × `dcc_refit_interval ∈ {0, 63}`（對 `full`、`voltarget_only`），
量兩軸：(a) 已實現年化波動 vs σ*=10% 追蹤誤差 RMSE、(b) full-dcc vs full-ewma 的 Sharpe/Calmar 配對 bootstrap CI（複用 Phase 4c）。

在 `PROGRESS.md` 的 Phase 5 段寫入**明確結論**（無論顯著與否）：
- 若 DCC 顯著改善（追蹤誤差更小且/或績效 CI 排除 0）→ 記為「DCC 值得，預設可翻 dcc」。
- 若無顯著貢獻 → 記「DCC 無顯著貢獻，v1 出貨用 EWMA」（§5.3 明言的合格結論）。

- [ ] **Step 5: commit**

```bash
git add quantcore/experiments/ablation.py tests/test_experiments/test_phase5a_ac.py PROGRESS.md
git commit -m "test(phase5a): DCC vs EWMA 消融 + AC 本機閘門 + 結論寫入（§5.3）"
```

---

## Task 12: 全套件驗證 + Phase 5a 收尾

- [ ] **Step 1: 全套件（非快照）綠**

Run: `uv run pytest -q -m "not requires_snapshot"`
Expected: 全 PASS（既有 + 5a 新測試，無回歸）

- [ ] **Step 2: 快照閘門（本機）綠**

Run: `uv run pytest -q -m "requires_snapshot"`
Expected: 全 PASS（本機有 parquet）

- [ ] **Step 3: lint/format 乾淨**

Run: `uv run ruff check quantcore tests && uv run ruff format --check quantcore tests`
Expected: 無錯（僅檢查本階段改動檔；若既有檔有既存告警不擴大處理）

- [ ] **Step 4: 更新 PROGRESS.md Phase 5 狀態**

把 Phase 5a 標為進行中/完成、記規格偏離（設計文件 §4 六點）、消融結論、AC 達成情形。

- [ ] **Step 5: commit**

```bash
git add PROGRESS.md
git commit -m "docs(phase5a): PROGRESS 更新——相關模型層完成、DCC vs EWMA 結論、規格偏離備忘"
```

---

## 自審記錄（spec 覆蓋對照）

- 設計 §1.1 `normalize_to_correlation` → Task 1 ✅
- §1.2 DCC(Q̄/遞迴/QMLE/fallback) → Task 3、4 ✅；§5a AC-2 合成回收 → Task 5 ✅
- §1.3 `ewma_correlation` → Task 2 ✅
- §1.4 標準化殘差複用 VolForecaster → Task 6 ✅
- §1.5 `CorrelationForecaster` refit/filter + 節奏 + fixed/reestimate → Task 7 ✅
- §1.6 covariance 收斂（`_project` 移 base、rolling 退役） → Task 9 ✅
- §1.7 vol_target_base 接線 → Task 9 ✅
- §2 config（`dcc_refit_interval`/`dcc_fixed_ab`/預設翻 ewma、D1/D2/D3） → Task 8 ✅
- §3 消融 + AC 兩軸（追蹤誤差 + bootstrap CI） → Task 11 ✅
- §5 測試（合成 + 不變量 + forecaster + config + 端到端） → Task 1-11 分佈 ✅
- INV-3 擴充 → Task 10 ✅；INV-6 決定性（QMLE 固定起點、無亂數）→ Task 4 設計內建 ✅

**與 spec 的介面精修（實作優於字面，記入 PROGRESS）：**
- spec §1.5 的 refit/filter 帶 `when: date`；plan 改用 `CorrelationForecaster` **內部 selection 計數器**
  （63÷selection_interval=每 3 次選擇重估 (a,b)）——免日曆、決定性更乾淨，語意等價。
