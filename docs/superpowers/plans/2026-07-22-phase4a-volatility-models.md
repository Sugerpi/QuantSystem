# Phase 4a — 波動率模型層 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `models/volatility` 波動率模型層——GARCH(1,1)-t 與 EWMA(λ=0.94) 兩個 `VolatilityModel`、多步預測、GARCH 失敗退回 EWMA、QLIKE/MZ-R² 評估與 GARCH vs EWMA 比較表——不碰回測引擎與策略。

**Architecture:** `VolatilityModel` ABC 在 `base.py`，×100 估計 / ÷100² 還原的縮放與 α+β<1 慣例檢查（INV-4）全關在 base，子類只實作 ×100 尺度的估計與預測。GARCH 用 `arch` 套件，失敗（不收斂 / 非平穩）拋 `GarchDegenerateError`，由 `fit_volatility` 封裝捕捉並退回 EWMA。評估為純函數 + walk-forward 驅動，輸出比較表。

**Tech Stack:** Python 3.11、`arch`（GARCH）、numpy、pandas、pydantic（config）、pytest。

**規格來源：** `DEVELOPMENT_GUIDE v1.2.md` §5.1/§5.2/§5.4/§1.6、INV-4。設計文件：`docs/superpowers/specs/2026-07-22-phase4a-volatility-models-design.md`。

**重要背景（給零脈絡的實作者）：**
- 依賴方向（CLAUDE.md）：`config ← data ← models ← signals/portfolio ← backtest ← experiments`。`models/volatility` 是上游純模型層，**不得 import `backtest`**。
- INV-4 慣例：報酬 ×100 後估計、預測 ÷100²（變異數是二次量）還原；Student-t；GARCH persistence α+β<1。
- **EWMA 是 IGARCH**：其 α+β=1 為定義特性、**非** INV-4 違反。α+β<1 檢查只對 GARCH 家族啟用（見 Task 3）。
- 硬性規則：任何參數只能在 `config/`。λ 與 H 本計畫入 config（Task 2）。
- 既有 `models/volatility/rolling_std.py::annualized_vol` 與 `estimate_annualized_vol` 派發**保留不動**（Phase 3 placeholder，4b 才遷移 `mom_ivol`）。
- 每個 task 結束都跑 `uv run pytest -q` 應全綠後才 commit。

---

## 檔案結構

| 檔案 | 責任 | 動作 |
|------|------|------|
| `pyproject.toml` | 加 `arch` 依賴 | 修改 |
| `quantcore/config/schema.py` | `RiskConfig` 加 `ewma_lambda`/`forecast_horizon` | 修改 |
| `quantcore/config/default.yaml` | 同上兩參數的預設值 | 修改 |
| `quantcore/models/volatility/base.py` | `VolatilityModel` ABC + 縮放模板 + `GarchDegenerateError` | 新增 |
| `quantcore/models/volatility/ewma.py` | `Ewma`（RiskMetrics λ=0.94，基線+fallback） | 新增 |
| `quantcore/models/volatility/garch_arch.py` | `GarchArch`（GARCH(1,1)-t via arch） | 新增 |
| `quantcore/models/volatility/eval.py` | `qlike`/`mincer_zarnowitz_r2` 純函數 | 新增 |
| `quantcore/models/volatility/__init__.py` | `fit_volatility` 封裝 + `annualized_forecast_vol` + 匯出 | 修改 |
| `quantcore/experiments/vol_eval.py` | walk-forward 評估驅動 + CLI（AC 交付） | 新增 |
| `tests/fixtures/synthetic.py` | 已知參數 GARCH-t 序列生成器 | 修改 |
| `tests/test_models/test_base.py` | base 縮放/慣例檢查 | 新增 |
| `tests/test_models/test_ewma.py` | EWMA 遞迴/多步/std resid | 新增 |
| `tests/test_models/test_garch_arch.py` | GARCH 回收/多步/失敗 | 新增 |
| `tests/test_models/test_vol_eval.py` | eval 純函數 + walk-forward 驅動 | 新增 |
| `tests/test_invariants/test_garch_conventions.py` | INV-4 守護（目前缺席） | 新增 |
| `tests/test_config.py` | 新 config 欄位驗證 | 修改 |

---

## Task 1: 加入 `arch` 依賴

**Files:**
- Modify: `pyproject.toml:10-21`

- [ ] **Step 1: 加入依賴宣告**

在 `pyproject.toml` 的 `dependencies` list 末尾（`python-dotenv` 之後）加一行：

```toml
    "arch>=7.0",
```

- [ ] **Step 2: 同步環境**

Run: `uv sync --extra dev`
Expected: 解析並安裝 `arch`（連帶 `scipy`）。無錯誤。

- [ ] **Step 3: 驗證可匯入且版本 ≥7**

Run: `uv run python -c "import arch; print(arch.__version__)"`
Expected: 印出 `7.x` 版本字串。

- [ ] **Step 4: 確認既有測試未被破壞**

Run: `uv run pytest -q`
Expected: 176 passed。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build(phase4a): 加入 arch 依賴（GARCH(1,1)-t）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Config 新增 `ewma_lambda` 與 `forecast_horizon`

**Files:**
- Modify: `quantcore/config/schema.py:53-63`（`RiskConfig`）
- Modify: `quantcore/config/default.yaml:19-25`（`risk` 區塊）
- Test: `tests/test_config.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_config.py` 末尾加入：

```python
def test_risk_ewma_lambda_and_horizon_loaded():
    cfg = load_config("quantcore/config/default.yaml")
    assert cfg.risk.ewma_lambda == 0.94
    assert cfg.risk.forecast_horizon == 21


def test_risk_ewma_lambda_must_be_open_unit_interval():
    import pytest
    from tests.fixtures.synthetic import make_cfg

    with pytest.raises(Exception):
        make_cfg(["SPY", "TLT"], risk={"ewma_lambda": 1.0})
    with pytest.raises(Exception):
        make_cfg(["SPY", "TLT"], risk={"ewma_lambda": 0.0})


def test_risk_forecast_horizon_must_be_positive():
    import pytest
    from tests.fixtures.synthetic import make_cfg

    with pytest.raises(Exception):
        make_cfg(["SPY", "TLT"], risk={"forecast_horizon": 0})
```

（`load_config` 已於 `tests/test_config.py` 匯入；若無，於檔頭加 `from quantcore.config import load_config`。）

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_config.py::test_risk_ewma_lambda_and_horizon_loaded -v`
Expected: FAIL —— `AttributeError`（`ewma_lambda` 尚未存在）或 `ValidationError`（default.yaml 未含鍵）。

- [ ] **Step 3: 加入 schema 欄位**

在 `quantcore/config/schema.py` 的 `RiskConfig`（第 53-63 行）加入兩欄位，置於 `vol_window` 之後：

```python
    ewma_lambda: float = Field(gt=0, lt=1)  # §5.3 RiskMetrics EWMA 衰減；也是 GARCH fallback
    forecast_horizon: int = Field(gt=0)  # §1.6 Step 1 的 H，對齊 selection_interval
```

- [ ] **Step 4: 加入 default.yaml 預設值**

在 `quantcore/config/default.yaml` 的 `risk:` 區塊（`vol_window` 之後）加入：

```yaml
  ewma_lambda: 0.94                 # §5.3 RiskMetrics EWMA 衰減（也是 GARCH fallback）
  forecast_horizon: 21              # §1.6 Step 1 的 H，對齊 selection_interval
```

- [ ] **Step 5: 執行確認通過**

Run: `uv run pytest tests/test_config.py -v`
Expected: 全部 PASS（含新三項）。

- [ ] **Step 6: 全測試綠**

Run: `uv run pytest -q`
Expected: 179 passed。

- [ ] **Step 7: Commit**

```bash
git add quantcore/config/schema.py quantcore/config/default.yaml tests/test_config.py
git commit -m "feat(config): risk 加 ewma_lambda / forecast_horizon（§5.3/§1.6）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `base.py` —— VolatilityModel ABC + 縮放模板

**Files:**
- Create: `quantcore/models/volatility/base.py`
- Test: `tests/test_models/test_base.py`

**設計要點：** 縮放（×100 估計 / ÷100² 還原）與 α+β<1 檢查全在 base。α+β<1 檢查以類別旗標 `enforce_stationarity` 控制是否啟用——GARCH 設 True，EWMA（IGARCH，α+β=1）設 False。子類只實作 `_estimate`（收 ×100 尺度報酬）與 `_forecast_scaled`（回 ×100 尺度每步變異數）。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_models/test_base.py`：

```python
"""base.VolatilityModel 的縮放模板與慣例檢查（INV-4 的單一實作點）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantcore.models.volatility.base import GarchDegenerateError, VolatilityModel


class _DummyModel(VolatilityModel):
    """最小具體子類：在 ×100 尺度把條件變異數固定為輸入報酬變異數，供測 base。"""

    enforce_stationarity = False
    _min_obs = 2

    def __init__(self, fake_alpha_beta: tuple[float, float] | None = None):
        self._fake_ab = fake_alpha_beta

    def _estimate(self, scaled_returns: pd.Series) -> None:
        self._scaled_var = float(scaled_returns.var(ddof=1))
        self._scaled = scaled_returns

    def _forecast_scaled(self, horizon: int) -> np.ndarray:
        return np.full(horizon, self._scaled_var, dtype="float64")

    @property
    def params(self) -> dict[str, float]:
        if self._fake_ab is None:
            return {}
        return {"alpha": self._fake_ab[0], "beta": self._fake_ab[1]}

    @property
    def standardized_residuals(self) -> pd.Series:
        return self._scaled / np.sqrt(self._scaled_var)


def _returns(n: int = 300) -> pd.Series:
    rng = np.random.default_rng(0)
    return pd.Series(rng.normal(0, 0.01, n))


def test_forecast_is_backscaled_to_return_variance():
    r = _returns()
    m = _DummyModel().fit(r)
    # base 在 ×100 尺度估計 var，forecast 應除以 100**2 還原回報酬變異數尺度
    expected = (r * 100).var(ddof=1) / (100**2)
    out = m.forecast(5)
    assert out.shape == (5,)
    assert np.allclose(out, expected)
    # 還原後應與原始報酬變異數同數量級
    assert np.isclose(out[0], r.var(ddof=1), rtol=0.05)


def test_forecast_before_fit_raises():
    with pytest.raises(RuntimeError):
        _DummyModel().forecast(1)


def test_horizon_must_be_positive():
    m = _DummyModel().fit(_returns())
    with pytest.raises(ValueError):
        m.forecast(0)


def test_stationarity_enforced_only_when_flag_set():
    r = _returns()
    # 旗標關閉（EWMA 情境）：α+β=1 不該擋
    _DummyModel(fake_alpha_beta=(0.2, 0.8)).fit(r)

    class _Enforced(_DummyModel):
        enforce_stationarity = True

    with pytest.raises(GarchDegenerateError):
        _Enforced(fake_alpha_beta=(0.2, 0.85)).fit(r)  # α+β=1.05 ≥ 1
    # α+β<1 正常
    _Enforced(fake_alpha_beta=(0.1, 0.85)).fit(r)
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_models/test_base.py -v`
Expected: FAIL —— `ModuleNotFoundError: quantcore.models.volatility.base`。

- [ ] **Step 3: 實作 base.py**

Create `quantcore/models/volatility/base.py`：

```python
"""波動率模型基底（規格 §5.1、INV-4）。

縮放（×100 估計 / ÷100² 還原）與 GARCH 平穩性檢查（α+β<1）全在此完成——
INV-4 只有這一個地方能被違反。子類只實作 ×100 尺度的估計與預測。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

_SCALE = 100.0
DAYS_PER_YEAR = 252


class GarchDegenerateError(RuntimeError):
    """GARCH 估計退化：不收斂、非平穩（α+β≥1）或參數落邊界致預測非有限。

    由 fit_volatility 捕捉並退回 EWMA（設計文件 §1.4）。
    """


class VolatilityModel(ABC):
    """波動率模型 ABC。

    fit 收「報酬」序列（非價格）；forecast 回「每步變異數」，已還原縮放。
    """

    #: GARCH 家族設 True 以啟用 α+β<1 檢查；EWMA（IGARCH，α+β=1）設 False。
    enforce_stationarity: bool = False
    #: fit 所需最小觀測數（子類覆寫）。
    _min_obs: int = 2

    _fitted: bool = False

    def fit(self, returns: pd.Series) -> "VolatilityModel":
        r = returns.astype("float64").dropna()
        if len(r) < self._min_obs:
            raise ValueError(
                f"{type(self).__name__}.fit 需至少 {self._min_obs} 筆觀測，收到 {len(r)}"
            )
        self._estimate(r * _SCALE)
        if self.enforce_stationarity:
            self._check_stationarity()
        self._fitted = True
        return self

    def forecast(self, horizon: int) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("forecast 前須先 fit")
        if horizon < 1:
            raise ValueError(f"horizon 必須 ≥ 1，收到 {horizon}")
        scaled_var = np.asarray(self._forecast_scaled(horizon), dtype="float64")
        out = scaled_var / (_SCALE**2)
        if not np.all(np.isfinite(out)):
            raise GarchDegenerateError("多步預測含非有限值（參數退化）")
        return out

    def _check_stationarity(self) -> None:
        p = self.params
        persistence = p.get("alpha", 0.0) + p.get("beta", 0.0)
        if persistence >= 1.0:
            raise GarchDegenerateError(
                f"非平穩：α+β={persistence:.4f} ≥ 1（多步預測會發散）"
            )

    @property
    @abstractmethod
    def params(self) -> dict[str, float]:
        """{'omega','alpha','beta','nu',...}（×100 尺度）；供落盤與慣例檢查。"""

    @property
    @abstractmethod
    def standardized_residuals(self) -> pd.Series:
        """標準化殘差 r_t/σ_t（尺度不變），供 Phase 5 DCC。"""

    @abstractmethod
    def _estimate(self, scaled_returns: pd.Series) -> None:
        """在 ×100 尺度估計並儲存內部狀態。失敗拋 GarchDegenerateError。"""

    @abstractmethod
    def _forecast_scaled(self, horizon: int) -> np.ndarray:
        """×100 尺度的每步變異數（長度 horizon）。"""
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_models/test_base.py -v`
Expected: 全部 PASS（4 項）。

- [ ] **Step 5: Commit**

```bash
git add quantcore/models/volatility/base.py tests/test_models/test_base.py
git commit -m "feat(models): VolatilityModel ABC + 縮放模板（INV-4 單一出口）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `ewma.py` —— RiskMetrics EWMA（λ=0.94）

**Files:**
- Create: `quantcore/models/volatility/ewma.py`
- Test: `tests/test_models/test_ewma.py`

**設計要點：** `h_1 = 樣本變異數（seed）`；`h_t = λ·h_{t-1} + (1-λ)·r²_{t-1}`（t≥2，×100 尺度）。多步預測為 flat：所有 h 步 = 最後條件變異數。`enforce_stationarity=False`（IGARCH）。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_models/test_ewma.py`：

```python
"""EWMA(λ=0.94) 遞迴、flat 多步、標準化殘差、平穩性豁免。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantcore.models.volatility.ewma import Ewma


def _returns(n: int = 300) -> pd.Series:
    rng = np.random.default_rng(1)
    return pd.Series(rng.normal(0, 0.01, n))


def _reference_last_var(scaled: np.ndarray, lam: float) -> float:
    """獨立參考遞迴：回傳用於預測 r_{T+1} 的條件變異數（×100 尺度）。"""
    h = float(np.var(scaled, ddof=1))  # seed = 樣本變異數
    for t in range(1, len(scaled)):
        h = lam * h + (1 - lam) * scaled[t - 1] ** 2
    # 再納入最後一筆觀測，得預測 r_{T+1} 的條件變異數
    h = lam * h + (1 - lam) * scaled[-1] ** 2
    return h


def test_forecast_matches_reference_recursion():
    r = _returns()
    m = Ewma(0.94).fit(r)
    ref_scaled = _reference_last_var(r.to_numpy() * 100, 0.94)
    expected = ref_scaled / (100**2)  # 還原尺度
    out = m.forecast(1)
    assert np.isclose(out[0], expected, rtol=1e-9)


def test_multistep_is_flat():
    m = Ewma(0.94).fit(_returns())
    out = m.forecast(21)
    assert out.shape == (21,)
    assert np.allclose(out, out[0])  # EWMA 無均值回歸 → 常數多步


def test_lambda_exposed_in_params_no_alpha_beta():
    m = Ewma(0.94).fit(_returns())
    assert m.params["lambda"] == 0.94
    # 無 alpha/beta → base 的平穩性檢查不觸發（IGARCH 豁免）
    assert "alpha" not in m.params


def test_standardized_residuals_unit_scale():
    m = Ewma(0.94).fit(_returns(500))
    z = m.standardized_residuals
    # 標準化殘差樣本標準差應接近 1
    assert 0.7 < float(z.std()) < 1.4
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_models/test_ewma.py -v`
Expected: FAIL —— `ModuleNotFoundError`。

- [ ] **Step 3: 實作 ewma.py**

Create `quantcore/models/volatility/ewma.py`：

```python
"""RiskMetrics EWMA（λ=0.94，規格 §5.3）。

消融基線 + GARCH fallback（設計文件 §1.4），兩者共用此實作。
EWMA 是 IGARCH（α+β=1），enforce_stationarity=False 豁免 base 的平穩性檢查。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantcore.models.volatility.base import VolatilityModel


class Ewma(VolatilityModel):
    enforce_stationarity = False
    _min_obs = 2

    def __init__(self, lam: float):
        if not 0 < lam < 1:
            raise ValueError(f"EWMA λ 必須落在 (0,1)，收到 {lam}")
        self._lam = float(lam)

    def _estimate(self, scaled_returns: pd.Series) -> None:
        lam = self._lam
        r = scaled_returns.to_numpy()
        h = float(np.var(r, ddof=1))  # seed = 樣本變異數
        cond_var = np.empty(len(r), dtype="float64")
        for t in range(len(r)):
            cond_var[t] = h  # 預測 r_t 的條件變異數
            h = lam * h + (1 - lam) * r[t] ** 2
        self._cond_var = cond_var  # ×100 尺度，長度 = len(r)
        self._last_var = h  # 預測 r_{T+1} 的條件變異數
        self._scaled = scaled_returns

    def _forecast_scaled(self, horizon: int) -> np.ndarray:
        return np.full(horizon, self._last_var, dtype="float64")

    @property
    def params(self) -> dict[str, float]:
        return {"lambda": self._lam}

    @property
    def standardized_residuals(self) -> pd.Series:
        return self._scaled / np.sqrt(self._cond_var)
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_models/test_ewma.py -v`
Expected: 全部 PASS（4 項）。

- [ ] **Step 5: Commit**

```bash
git add quantcore/models/volatility/ewma.py tests/test_models/test_ewma.py
git commit -m "feat(models): EWMA(λ=0.94)（消融基線 + GARCH fallback）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 合成 GARCH-t 序列生成器（fixture）

**Files:**
- Modify: `tests/fixtures/synthetic.py`
- Test: `tests/test_models/test_garch_arch.py`（先只放生成器的自檢）

**設計要點：** 用已知 (ω,α,β,ν) 生成 GARCH(1,1)-t 序列，供 Task 6 的估計器回收測試。Student-t 創新標準化為單位變異數（乘 √((ν-2)/ν)）。固定 seed → 決定性。

- [ ] **Step 1: 寫失敗測試（生成器自檢）**

Create `tests/test_models/test_garch_arch.py`（本 task 只放這一個測試，Task 6 續加）：

```python
"""GARCH(1,1)-t：生成器自檢（Task 5）、估計器回收與多步（Task 6）。"""

from __future__ import annotations

import numpy as np

from tests.fixtures.synthetic import make_garch_t_returns


def test_generator_is_deterministic_and_stationary():
    a = make_garch_t_returns(1000, omega=1e-6, alpha=0.1, beta=0.85, nu=7, seed=42)
    b = make_garch_t_returns(1000, omega=1e-6, alpha=0.1, beta=0.85, nu=7, seed=42)
    assert np.allclose(a.to_numpy(), b.to_numpy())  # 同 seed 決定性
    assert len(a) == 1000
    assert np.all(np.isfinite(a.to_numpy()))
    # 樣本波動叢聚：|r| 的一階自相關為正（GARCH 特徵）
    absr = np.abs(a.to_numpy())
    ac1 = np.corrcoef(absr[:-1], absr[1:])[0, 1]
    assert ac1 > 0.05
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_models/test_garch_arch.py -v`
Expected: FAIL —— `ImportError: cannot import name 'make_garch_t_returns'`。

- [ ] **Step 3: 加入生成器**

在 `tests/fixtures/synthetic.py` 末尾加入（檔頭已有 `import pandas as pd`；補 `import numpy as np`）：

```python
def make_garch_t_returns(
    n: int,
    omega: float,
    alpha: float,
    beta: float,
    nu: float,
    seed: int,
) -> pd.Series:
    """已知參數 GARCH(1,1)-t 報酬序列（§8：合成資料驗證估計器正確性）。

    Student-t(ν) 創新標準化為單位變異數。回傳原始報酬尺度的 pd.Series
    （index 為連續 bdate）。α+β<1 由呼叫端保證平穩。
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    z = rng.standard_t(nu, size=n) * np.sqrt((nu - 2) / nu)  # 單位變異數
    var = np.empty(n, dtype="float64")
    ret = np.empty(n, dtype="float64")
    var[0] = omega / (1 - alpha - beta)  # 無條件變異數起始
    ret[0] = np.sqrt(var[0]) * z[0]
    for t in range(1, n):
        var[t] = omega + alpha * ret[t - 1] ** 2 + beta * var[t - 1]
        ret[t] = np.sqrt(var[t]) * z[t]
    return pd.Series(ret, index=pd.bdate_range("2000-01-03", periods=n))
```

（若檔頭尚無 `import numpy as np`，於 `import pandas as pd` 上方補上；函式內的重複 import 可移除。）

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_models/test_garch_arch.py -v`
Expected: PASS（1 項）。

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/synthetic.py tests/test_models/test_garch_arch.py
git commit -m "test(fixtures): 已知參數 GARCH-t 序列生成器（§8）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `garch_arch.py` —— GARCH(1,1)-t via arch

**Files:**
- Create: `quantcore/models/volatility/garch_arch.py`
- Test: `tests/test_models/test_garch_arch.py`（續 Task 5）

**設計要點：** `arch_model(scaled, mean='Constant', vol='GARCH', p=1, q=1, dist='t')`。`enforce_stationarity=True`（base 檢查 α+β<1）。不收斂 → `GarchDegenerateError`。多步預測用 arch 的 analytic forecast（GARCH(1,1) 的閉式解析遞迴，非模擬），並以測試鎖住「連續步滿足 v_h = ω+(α+β)v_{h-1}」。

- [ ] **Step 1: 寫失敗測試（續加至 test_garch_arch.py）**

在 `tests/test_models/test_garch_arch.py` 加入：

```python
import pandas as pd
import pytest

from quantcore.models.volatility.base import GarchDegenerateError
from quantcore.models.volatility.garch_arch import GarchArch


def test_recovers_known_parameters():
    # 以 scale-invariant 參數（α,β,ν）為回收標的；ω 隨尺度變，不強比。
    r = make_garch_t_returns(4000, omega=1e-6, alpha=0.10, beta=0.85, nu=7, seed=7)
    m = GarchArch().fit(r)
    p = m.params
    # 估回真值附近（非落邊界）。容差對 N=4000 固定 seed 之單次抽樣校準，
    # 若略偏可微調，但須保持「近真值」而非放寬到無意義。
    assert 0.04 < p["alpha"] < 0.18
    assert 0.75 < p["beta"] < 0.93
    assert p["alpha"] + p["beta"] < 1.0
    assert p["nu"] > 3.0


def test_multistep_follows_analytic_recursion():
    r = make_garch_t_returns(2000, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=3)
    m = GarchArch().fit(r)
    # 取 ×100 尺度的每步變異數（子類原始輸出），驗證解析遞迴關係
    scaled = m._forecast_scaled(10)
    p = m.params
    persistence = p["alpha"] + p["beta"]
    for h in range(1, 10):
        assert np.isclose(scaled[h], p["omega"] + persistence * scaled[h - 1], rtol=1e-6)


def test_forecast_backscaled_reasonable_annualized_vol():
    r = make_garch_t_returns(2000, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=3)
    m = GarchArch().fit(r)
    per_step_var = m.forecast(21)  # 已還原
    ann_vol = float(np.sqrt(per_step_var.mean()) * np.sqrt(252))
    assert 0.01 < ann_vol < 2.0  # 合理年化波動區間（非退化）


def test_nonstationary_series_raises_or_falls_within_bounds():
    # 近單位根 / 極端序列易使 arch 估出 α+β≥1，應由 base 擋為 GarchDegenerateError。
    rng = np.random.default_rng(9)
    # 刻意造出強持續性波動（random walk 般的變異數），提高非平穩機率
    shocks = rng.normal(0, 1, 400).cumsum()
    series = pd.Series(np.diff(shocks, prepend=0.0) * 0.05)
    try:
        m = GarchArch().fit(series)
        assert m.params["alpha"] + m.params["beta"] < 1.0  # 若收斂，必平穩
    except GarchDegenerateError:
        pass  # 非平穩被正確擋下，即符合預期
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_models/test_garch_arch.py -v`
Expected: FAIL —— `ModuleNotFoundError: quantcore.models.volatility.garch_arch`。

- [ ] **Step 3: 實作 garch_arch.py**

Create `quantcore/models/volatility/garch_arch.py`：

```python
"""GARCH(1,1)-t via arch 套件（規格 §5.2，Phase 4 正式路徑）。

v1 固定 GARCH(1,1)-t，不做 AIC 選規格。多步用 arch 的 analytic forecast
（GARCH(1,1) 閉式解析遞迴，決定性，符合 INV-6）。失敗拋 GarchDegenerateError。
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from quantcore.models.volatility.base import GarchDegenerateError, VolatilityModel


class GarchArch(VolatilityModel):
    enforce_stationarity = True
    _min_obs = 100  # GARCH-t MLE 需足夠樣本

    def _estimate(self, scaled_returns: pd.Series) -> None:
        from arch import arch_model

        am = arch_model(
            scaled_returns.to_numpy(),
            mean="Constant",
            vol="GARCH",
            p=1,
            q=1,
            dist="t",
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = am.fit(disp="off", show_warning=False)
        if int(getattr(res, "convergence_flag", 0)) != 0:
            raise GarchDegenerateError(f"GARCH 優化未收斂（flag={res.convergence_flag}）")
        pr = res.params
        self._params = {
            "omega": float(pr["omega"]),
            "alpha": float(pr["alpha[1]"]),
            "beta": float(pr["beta[1]"]),
            "nu": float(pr["nu"]),
        }
        if not all(np.isfinite(v) for v in self._params.values()):
            raise GarchDegenerateError("GARCH 參數含非有限值")
        self._res = res

    def _forecast_scaled(self, horizon: int) -> np.ndarray:
        # analytic forecast：GARCH(1,1) 閉式遞迴，非模擬（決定性）
        fc = self._res.forecast(horizon=horizon, method="analytic", reindex=False)
        return np.asarray(fc.variance.to_numpy()[-1], dtype="float64")

    @property
    def params(self) -> dict[str, float]:
        return dict(self._params)

    @property
    def standardized_residuals(self) -> pd.Series:
        return pd.Series(np.asarray(self._res.std_resid, dtype="float64"))
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_models/test_garch_arch.py -v`
Expected: 全部 PASS（含 Task 5 的 1 項，共 5 項）。若 `test_recovers_known_parameters` 因固定 seed 抽樣略微超界，微調容差（保持「近真值、非邊界」）。

- [ ] **Step 5: 全測試綠**

Run: `uv run pytest -q`
Expected: 綠（新增測試計入）。

- [ ] **Step 6: Commit**

```bash
git add quantcore/models/volatility/garch_arch.py tests/test_models/test_garch_arch.py
git commit -m "feat(models): GARCH(1,1)-t via arch + 解析多步 + 退化拋錯（§5.2）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: 多步聚合 + fallback 封裝（`__init__.py`）

**Files:**
- Modify: `quantcore/models/volatility/__init__.py`
- Test: `tests/test_models/test_fit_volatility.py`

**設計要點：** `annualized_forecast_vol(model, H)` = `sqrt(mean(forecast(H)))·sqrt(252)`（§1.6 Step 1）。`fit_volatility(spec, returns, ewma_lambda)` 對 `garch_arch` 先試 GARCH、捕捉 `GarchDegenerateError` 退回 EWMA，回傳 `FitOutcome(model, fell_back, reason)`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_models/test_fit_volatility.py`：

```python
"""fit_volatility 的 fallback 政策與多步年化聚合。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantcore.models.volatility import (
    FitOutcome,
    annualized_forecast_vol,
    fit_volatility,
)
from quantcore.models.volatility.ewma import Ewma
from quantcore.models.volatility.garch_arch import GarchArch
from tests.fixtures.synthetic import make_garch_t_returns


def _good_returns():
    return make_garch_t_returns(1500, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=5)


def test_annualized_forecast_vol_aggregates_and_annualizes():
    m = Ewma(0.94).fit(_good_returns())
    per_step = m.forecast(21)
    expected = float(np.sqrt(per_step.mean()) * np.sqrt(252))
    assert np.isclose(annualized_forecast_vol(m, 21), expected)


def test_garch_spec_uses_garch_when_healthy():
    out = fit_volatility("garch_arch", _good_returns(), ewma_lambda=0.94)
    assert isinstance(out, FitOutcome)
    assert isinstance(out.model, GarchArch)
    assert out.fell_back is False
    assert out.reason is None


def test_garch_spec_falls_back_to_ewma_on_degenerate(monkeypatch):
    from quantcore.models.volatility import base

    def _boom(self, scaled_returns):
        raise base.GarchDegenerateError("造出的退化")

    monkeypatch.setattr(GarchArch, "_estimate", _boom)
    out = fit_volatility("garch_arch", _good_returns(), ewma_lambda=0.94)
    assert isinstance(out.model, Ewma)
    assert out.fell_back is True
    assert "退化" in out.reason


def test_ewma_spec_no_fallback():
    out = fit_volatility("ewma", _good_returns(), ewma_lambda=0.94)
    assert isinstance(out.model, Ewma)
    assert out.fell_back is False


def test_unknown_spec_raises():
    with pytest.raises(ValueError):
        fit_volatility("nope", _good_returns(), ewma_lambda=0.94)
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_models/test_fit_volatility.py -v`
Expected: FAIL —— `ImportError`（`FitOutcome`/`fit_volatility`/`annualized_forecast_vol` 未匯出）。

- [ ] **Step 3: 擴充 `__init__.py`**

改寫 `quantcore/models/volatility/__init__.py`（保留既有 `estimate_annualized_vol` 與 `annualized_vol`）：

```python
"""波動率模型層（規格 §5）。

- rolling_std：Phase 3 placeholder（保留，4b 前 mom_ivol 仍用）。
- VolatilityModel/Ewma/GarchArch：Phase 4a 正式模型。
- fit_volatility：GARCH 失敗退回 EWMA 的封裝（設計文件 §1.4）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantcore.models.volatility.base import (
    DAYS_PER_YEAR,
    GarchDegenerateError,
    VolatilityModel,
)
from quantcore.models.volatility.ewma import Ewma
from quantcore.models.volatility.garch_arch import GarchArch
from quantcore.models.volatility.rolling_std import annualized_vol


def estimate_annualized_vol(vol_model: str, adj_close: pd.Series, window: int) -> float:
    """依 config 的 vol_model 派發 σ̂ 估計（Phase 3 相容路徑，4b 前 mom_ivol 用）。"""
    if vol_model == "rolling_std":
        return annualized_vol(adj_close, window)
    raise NotImplementedError(f"vol_model={vol_model!r} 於此相容路徑未實作；請用 fit_volatility")


def annualized_forecast_vol(model: VolatilityModel, horizon: int) -> float:
    """σ̂ = sqrt( (1/H)·Σ_{h=1..H} Var(t+h) )·sqrt(252)（規格 §1.6 Step 1）。"""
    per_step_var = model.forecast(horizon)
    return float(np.sqrt(per_step_var.mean()) * np.sqrt(DAYS_PER_YEAR))


@dataclass(frozen=True)
class FitOutcome:
    model: VolatilityModel
    fell_back: bool
    reason: str | None


def fit_volatility(spec: str, returns: pd.Series, *, ewma_lambda: float) -> FitOutcome:
    """依 spec 建模型並 fit。garch_arch 失敗退回 EWMA 並記標記（設計文件 §1.4）。"""
    if spec == "garch_arch":
        try:
            return FitOutcome(GarchArch().fit(returns), False, None)
        except GarchDegenerateError as exc:
            return FitOutcome(Ewma(ewma_lambda).fit(returns), True, str(exc))
    if spec == "ewma":
        return FitOutcome(Ewma(ewma_lambda).fit(returns), False, None)
    raise ValueError(f"未知 vol spec：{spec!r}（可用：garch_arch | ewma）")


__all__ = [
    "DAYS_PER_YEAR",
    "Ewma",
    "FitOutcome",
    "GarchArch",
    "GarchDegenerateError",
    "VolatilityModel",
    "annualized_forecast_vol",
    "annualized_vol",
    "estimate_annualized_vol",
    "fit_volatility",
]
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_models/test_fit_volatility.py -v`
Expected: 全部 PASS（5 項）。

- [ ] **Step 5: 確認既有相容路徑未破壞**

Run: `uv run pytest tests/test_models/test_rolling_std.py tests/test_backtest -q`
Expected: 綠（`estimate_annualized_vol`/`mom_ivol` 仍走 rolling_std）。

- [ ] **Step 6: Commit**

```bash
git add quantcore/models/volatility/__init__.py tests/test_models/test_fit_volatility.py
git commit -m "feat(models): fit_volatility fallback 封裝 + 多步年化聚合（§1.6/§1.4）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: `eval.py` —— QLIKE / MZ-R² 純函數

**Files:**
- Create: `quantcore/models/volatility/eval.py`
- Test: `tests/test_models/test_vol_eval.py`

**設計要點：** 純函數，不依賴任何模型狀態。`qlike = mean(r/f − log(r/f) − 1)`；`mincer_zarnowitz_r2` 為 `realized ~ a + b·forecast` OLS 的 R²。刻意放 models 層而非 backtest/metrics.py（依賴方向，設計文件 §3.1）。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_models/test_vol_eval.py`：

```python
"""QLIKE / MZ-R² 純損失函數。"""

from __future__ import annotations

import numpy as np

from quantcore.models.volatility.eval import mincer_zarnowitz_r2, qlike


def test_qlike_zero_for_perfect_forecast():
    v = np.array([1.0, 2.0, 3.0, 4.0])
    assert np.isclose(qlike(v, v), 0.0)


def test_qlike_positive_and_larger_for_worse_forecast():
    realized = np.array([1.0, 2.0, 3.0, 4.0])
    slightly_off = realized * 1.1
    way_off = realized * 2.0
    assert qlike(realized, slightly_off) > 0
    assert qlike(realized, way_off) > qlike(realized, slightly_off)


def test_mz_r2_is_one_when_realized_equals_forecast():
    f = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert np.isclose(mincer_zarnowitz_r2(f, f), 1.0)


def test_mz_r2_low_for_uncorrelated():
    rng = np.random.default_rng(0)
    realized = rng.uniform(1, 2, 200)
    forecast = rng.uniform(1, 2, 200)
    assert mincer_zarnowitz_r2(realized, forecast) < 0.2
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_models/test_vol_eval.py -v`
Expected: FAIL —— `ModuleNotFoundError`。

- [ ] **Step 3: 實作 eval.py**

Create `quantcore/models/volatility/eval.py`：

```python
"""波動預測品質評估（規格 §5.4）。

純函數：QLIKE（對預測偏誤穩健）與 Mincer-Zarnowitz 回歸 R²。
刻意置於 models 層而非 backtest/metrics.py，以維持依賴方向單向
（models 不得依賴 backtest；設計文件 §3.1）。
"""

from __future__ import annotations

import numpy as np


def qlike(realized_var: np.ndarray, forecast_var: np.ndarray) -> float:
    """QLIKE = mean( r/f − log(r/f) − 1 )。完美預測為 0，偏誤時為正。"""
    r = np.asarray(realized_var, dtype="float64")
    f = np.asarray(forecast_var, dtype="float64")
    if np.any(f <= 0) or np.any(r <= 0):
        raise ValueError("QLIKE 需 realized/forecast 變異數皆為正")
    ratio = r / f
    return float(np.mean(ratio - np.log(ratio) - 1.0))


def mincer_zarnowitz_r2(realized_var: np.ndarray, forecast_var: np.ndarray) -> float:
    """realized ~ a + b·forecast 的 OLS R²。"""
    r = np.asarray(realized_var, dtype="float64")
    f = np.asarray(forecast_var, dtype="float64")
    x = np.column_stack([np.ones_like(f), f])
    beta, *_ = np.linalg.lstsq(x, r, rcond=None)
    pred = x @ beta
    ss_res = float(np.sum((r - pred) ** 2))
    ss_tot = float(np.sum((r - r.mean()) ** 2))
    if ss_tot == 0:
        return 0.0
    return 1.0 - ss_res / ss_tot
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_models/test_vol_eval.py -v`
Expected: 全部 PASS（4 項）。

- [ ] **Step 5: Commit**

```bash
git add quantcore/models/volatility/eval.py tests/test_models/test_vol_eval.py
git commit -m "feat(models): QLIKE / MZ-R² 波動評估純函數（§5.4）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Walk-forward 評估驅動 + CLI（AC 交付）

**Files:**
- Create: `quantcore/experiments/vol_eval.py`
- Test: `tests/test_models/test_vol_eval.py`（續加驅動測試）

**設計要點：** 純驅動函數 `walk_forward_vol_eval(returns, spec, *, warmup, interval, horizon, ewma_lambda)` → `{'qlike':..., 'mz_r2':..., 'n_points':..., 'n_fallback':...}`；在 CI 用合成序列單元測試。CLI `compare_garch_ewma` 載真實快照、逐資產對 GARCH 與 EWMA 產比較表 + provenance（本機 AC 閘門，`requires_snapshot`）。

- [ ] **Step 1: 寫失敗測試（驅動邏輯，CI 可跑）**

在 `tests/test_models/test_vol_eval.py` 加入：

```python
import pandas as pd

from quantcore.experiments.vol_eval import walk_forward_vol_eval
from tests.fixtures.synthetic import make_garch_t_returns


def test_walk_forward_produces_finite_qlike_on_synthetic():
    r = make_garch_t_returns(700, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=11)
    out = walk_forward_vol_eval(
        r, "ewma", warmup=252, interval=21, horizon=21, ewma_lambda=0.94
    )
    assert out["n_points"] > 0
    assert np.isfinite(out["qlike"])
    assert -1.0 <= out["mz_r2"] <= 1.0
    assert out["n_fallback"] == 0  # EWMA 不 fallback


def test_walk_forward_garch_counts_fallbacks_field_present():
    r = make_garch_t_returns(700, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=12)
    out = walk_forward_vol_eval(
        r, "garch_arch", warmup=252, interval=21, horizon=21, ewma_lambda=0.94
    )
    assert "n_fallback" in out
    assert out["n_points"] > 0
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_models/test_vol_eval.py -v`
Expected: FAIL —— `ModuleNotFoundError: quantcore.experiments.vol_eval`。

- [ ] **Step 3: 實作 vol_eval.py**

Create `quantcore/experiments/vol_eval.py`：

```python
"""Walk-forward 波動預測評估 + GARCH vs EWMA 比較表（規格 §5.4，Phase 4a AC）。

每 interval 個交易日 refit，產 H 步預測，對齊未來 H 日已實現變異數 proxy，
逐資產算 QLIKE 與 MZ-R²。CLI 產出比較表（本機閘門：需真實快照）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from quantcore.config import load_config
from quantcore.data.hashing import config_hash
from quantcore.data.snapshot import load_snapshot
from quantcore.experiments.tracking import QC_VERSION, git_commit
from quantcore.models.volatility import annualized_forecast_vol, fit_volatility
from quantcore.models.volatility.eval import mincer_zarnowitz_r2, qlike


def walk_forward_vol_eval(
    returns: pd.Series,
    spec: str,
    *,
    warmup: int,
    interval: int,
    horizon: int,
    ewma_lambda: float,
) -> dict:
    """單資產 walk-forward 評估。

    在每個 refit 點 t（warmup 後，每 interval 步）以 t 前資料 fit，
    forecast 平均變異數 vs t+1..t+horizon 的已實現平均日變異數 proxy。
    """
    r = returns.astype("float64").dropna()
    vals = r.to_numpy()
    n = len(vals)
    forecasts: list[float] = []
    realized: list[float] = []
    n_fallback = 0

    t = warmup
    while t + horizon <= n:
        window = r.iloc[:t]
        outcome = fit_volatility(spec, window, ewma_lambda=ewma_lambda)
        n_fallback += int(outcome.fell_back)
        per_step = outcome.model.forecast(horizon)
        forecast_var = float(per_step.mean())  # 平均每日變異數（還原尺度）
        future = vals[t : t + horizon]
        realized_var = float(np.mean(future**2))  # 已實現平均日變異數 proxy
        forecasts.append(forecast_var)
        realized.append(realized_var)
        t += interval

    fa = np.asarray(forecasts)
    ra = np.asarray(realized)
    return {
        "spec": spec,
        "n_points": len(forecasts),
        "n_fallback": n_fallback,
        "qlike": qlike(ra, fa) if len(forecasts) else float("nan"),
        "mz_r2": mincer_zarnowitz_r2(ra, fa) if len(forecasts) else float("nan"),
    }


def _returns_by_ticker(snapshot: dict) -> dict[str, pd.Series]:
    prices = snapshot["prices"]
    out: dict[str, pd.Series] = {}
    for ticker, grp in prices.groupby("ticker"):
        s = grp.sort_values("date").set_index("date")["adj_close"].astype("float64")
        out[ticker] = s.pct_change().dropna()
    return out


def compare_garch_ewma(config_path: str, out_dir: str) -> pd.DataFrame:
    """對快照每檔資產跑 GARCH 與 EWMA walk-forward，輸出比較表 + provenance。"""
    cfg = load_config(config_path)
    snapshot = load_snapshot(cfg.snapshot)
    rets = _returns_by_ticker(snapshot)

    rows = []
    for ticker in sorted(rets):
        for spec in ("garch_arch", "ewma"):
            res = walk_forward_vol_eval(
                rets[ticker],
                spec,
                warmup=cfg.universe.min_history_days,
                interval=cfg.schedule.selection_interval,
                horizon=cfg.risk.forecast_horizon,
                ewma_lambda=cfg.risk.ewma_lambda,
            )
            rows.append({"ticker": ticker, **res})
    table = pd.DataFrame(rows).sort_values(["ticker", "spec"]).reset_index(drop=True)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out / "vol_eval_comparison.parquet", index=False)
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "snapshot_id": snapshot["manifest"].get("snapshot_id"),
                "git_commit": git_commit(),
                "config_hash": config_hash(cfg.model_dump(mode="json")),
                "quantcore_version": QC_VERSION,
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return table


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GARCH vs EWMA 波動預測比較表（§5.4）")
    ap.add_argument("--config", default="quantcore/config/default.yaml")
    ap.add_argument("--out", default="runs/vol_eval")
    args = ap.parse_args(argv)
    table = compare_garch_ewma(args.config, args.out)
    print(table.to_string(index=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
```

（`config_hash(config_dict) -> str` 已存在於 `quantcore/data/hashing.py`；`ablation.py`/`runner.py` 皆以 `config_hash(cfg.model_dump(mode="json"))` 呼叫，本檔沿用同一形式。）

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_models/test_vol_eval.py -v`
Expected: 全部 PASS（含前面 eval 純函數與此驅動測試）。

- [ ] **Step 5: 本機 AC 交付——實跑比較表（有快照時）**

Run: `uv run python -m quantcore.experiments.vol_eval --config quantcore/config/default.yaml --out runs/vol_eval`
Expected: 印出每檔 ticker × {garch_arch, ewma} 的 QLIKE/MZ-R²/fallback 表；`runs/vol_eval/vol_eval_comparison.parquet` 與 `manifest.json` 產出。**這是 Phase 4 三個 AC 中「GARCH vs EWMA QLIKE 比較表」的交付。** 目視確認多數資產 GARCH 的 QLIKE ≤ EWMA（若不然，記於 PROGRESS，屬誠實結論）。

- [ ] **Step 6: 全測試綠**

Run: `uv run pytest -q`
Expected: 綠。

- [ ] **Step 7: Commit**

```bash
git add quantcore/experiments/vol_eval.py tests/test_models/test_vol_eval.py
git commit -m "feat(experiments): walk-forward 波動評估 + GARCH vs EWMA 比較表（§5.4，AC）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: INV-4 守護測試（`test_garch_conventions.py`）

**Files:**
- Create: `tests/test_invariants/test_garch_conventions.py`

**背景：** CLAUDE.md 不變量表列此檔為 INV-4 守護，但**目前不存在**——INV-4 至今無測試守護。本 task 補上，並以變異註記確認其有牙齒。

- [ ] **Step 1: 寫測試**

Create `tests/test_invariants/test_garch_conventions.py`：

```python
"""INV-4：GARCH 數值慣例（規格 §3 INV-4）。

守護：報酬 ×100 估計 / ÷100² 還原、α+β<1（GARCH）、Student-t、EWMA 為 IGARCH 豁免。
"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.models.volatility import Ewma, GarchArch
from quantcore.models.volatility.base import GarchDegenerateError, VolatilityModel
from tests.fixtures.synthetic import make_garch_t_returns


def _series():
    return make_garch_t_returns(2000, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=21)


def test_garch_persistence_below_one():
    m = GarchArch().fit(_series())
    p = m.params
    assert p["alpha"] + p["beta"] < 1.0  # INV-4：平穩


def test_garch_uses_student_t_has_nu():
    m = GarchArch().fit(_series())
    assert "nu" in m.params
    assert m.params["nu"] > 2.0  # t 分配自由度存在且有限變異數


def test_backscaling_convention_variance_is_quadratic():
    # ×100 尺度變異數 ÷100² 還原：forecast 相對 _forecast_scaled 差 1e4 倍
    m = GarchArch().fit(_series())
    scaled = m._forecast_scaled(5)
    restored = m.forecast(5)
    assert np.allclose(restored, scaled / (100**2))


def test_ewma_is_igarch_exempt_from_stationarity():
    # EWMA α+β=1（IGARCH），不得被平穩性檢查擋下
    m = Ewma(0.94).fit(_series())
    assert m.enforce_stationarity is False
    m.forecast(21)  # 不拋 GarchDegenerateError


def test_stationarity_check_has_teeth():
    # 變異守護：若把 GARCH 的 enforce_stationarity 關掉，非平穩參數就不會被擋——
    # 這裡直接驗證 base 的檢查邏輯對 α+β≥1 會拋錯（防止 INV-4 檢查被靜默移除）。
    class _Fake(VolatilityModel):
        enforce_stationarity = True
        _min_obs = 2

        def _estimate(self, scaled_returns):
            self._s = scaled_returns

        def _forecast_scaled(self, horizon):
            return np.ones(horizon)

        @property
        def params(self):
            return {"alpha": 0.3, "beta": 0.8}  # α+β=1.1

        @property
        def standardized_residuals(self):
            return self._s

    with pytest.raises(GarchDegenerateError):
        _Fake().fit(_series())
```

- [ ] **Step 2: 執行確認通過**

Run: `uv run pytest tests/test_invariants/test_garch_conventions.py -v`
Expected: 全部 PASS（5 項）。

- [ ] **Step 3: 全測試綠**

Run: `uv run pytest -q`
Expected: 綠。

- [ ] **Step 4: Commit**

```bash
git add tests/test_invariants/test_garch_conventions.py
git commit -m "test(inv): INV-4 GARCH 數值慣例守護測試（補上缺席的守護）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: 更新 PROGRESS.md（4a 完成紀錄）

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: 記錄 4a 完成**

在 `PROGRESS.md` 的 Phase 4 區塊，把已完成的 4a 子項打勾，並在「變更紀錄」加一行（比照既有格式），記：
- 完成項：base.py（INV-4 縮放模板）、garch_arch、ewma、多步解析預測、fit_volatility fallback、eval（QLIKE/MZ-R²）、walk-forward 比較表。
- AC：Phase 4「GARCH vs EWMA QLIKE 比較表」達成（4a 段）。
- 5 處規格偏離（見設計文件 §6）。
- **補記：INV-4 守護測試 `test_garch_conventions.py` 於本階段首次建立（此前缺席）。**
- 邊界：未碰 engine/策略；`mom_ivol` 仍用 rolling_std，待 4b 遷移。

- [ ] **Step 2: 全測試綠 + 格式檢查**

Run: `uv run pytest -q && uv run ruff format --check quantcore tests && uv run ruff check quantcore tests`
Expected: 測試綠、ruff 乾淨。

- [ ] **Step 3: Commit**

```bash
git add PROGRESS.md
git commit -m "docs(phase4a): 波動率模型層完成，QLIKE 比較表 AC 達成 + 補建 INV-4 守護

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 完成後

4a 完成後，`feature/phase4-volatility` 上應有：GARCH/EWMA 模型、多步預測、fallback、QLIKE 評估與比較表、INV-4 守護。**engine 與策略未動**。

下一步為 4b（曝險模組 + `voltarget_only`/`full` 策略 + engine 接線 + refit/filter 節奏），另開 brainstorming → spec → plan。屆時再處理 `mom_ivol` 從 rolling_std 遷移到 `fit_volatility` 的接線。
```
