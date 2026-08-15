# full_gjr 策略（GJR-GARCH 波動引擎）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `full_gjr` 策略，波動引擎改用 GJR-GARCH(1,1)-t（非對稱項 γ），Step 2（σ̂_i→inverse-vol）與 Step 3（σ̂_p→曝險）同時改用新變異數。

**Architecture:** GJR = arch 套件 `o=1`。以 `GjrGarchArch(GarchArch)` 子類最小化擴充，`o` 參數穿過共用的 `_build_arch_model` 與濾波函式；平穩條件納入 0.5γ（INV-4）；forecaster 快取記錄 `o` 以正確濾波與取 γ；`full_gjr` 繼承 `Full` 只換 forecaster spec；前端 GARCH 頁顯示 γ。單一 forecaster 抽換點覆蓋 Step 2/3。

**Tech Stack:** Python、arch 套件、pandas/numpy、pytest、FastAPI（presentation）、uv。

**Spec:** `docs/superpowers/specs/2026-08-15-full-gjr-strategy-design.md`

---

## 檔案結構

- Modify: `quantcore/models/volatility/garch_arch.py` — `_build_arch_model` 加 `o`；`GarchArch` 加 `_o=0`、`_estimate` 依名稱取參；新增 `GjrGarchArch`；`garch_filter_forecast/residuals` 加 `o`。
- Modify: `quantcore/models/volatility/base.py` — `_check_stationarity` 納入 0.5γ。
- Modify: `quantcore/models/volatility/__init__.py` — `fit_volatility` 認 `"gjr_garch"`。
- Modify: `quantcore/models/volatility/forecaster.py` — spec 集合加 `"gjr_garch"`；`_CacheEntry` 記 `arch_o`；`filter` 傳 `o`；`last_params` γ 分支。
- Create: `quantcore/backtest/strategies/full_gjr.py` — `FullGjr(Full)`。
- Modify: `quantcore/backtest/strategies/__init__.py` — 註冊 `FullGjr`。
- Modify: `quantcore/presentation/web/routes/garch.py` — persistence 納入 0.5γ、參數軌跡加 γ 系列。
- Create: `scratchpad`（研究輕流程）消融腳本；Modify: `PROGRESS.md`。
- Test: `tests/test_models/test_gjr_garch.py`、`tests/test_models/test_forecaster.py`、`tests/test_backtest/test_full_gjr.py`、`tests/test_presentation/test_garch_page.py`（或既有前端測試檔）。

---

## Task 1: garch_arch.py 加入 GJR 能力

**Files:**
- Modify: `quantcore/models/volatility/garch_arch.py`
- Test: `tests/test_models/test_gjr_garch.py`

- [ ] **Step 1: 寫失敗測試（fit 產出 gamma、平穩、length-6 向量）**

建立 `tests/test_models/test_gjr_garch.py`：

```python
"""GJR-GARCH(1,1)-t：非對稱項 γ 估計、濾波 parity、向量長度。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantcore.models.volatility.garch_arch import (
    GarchArch,
    GjrGarchArch,
    garch_filter_forecast,
    garch_filter_residuals,
)
from tests.fixtures.synthetic import make_garch_t_returns


def test_gjr_fit_produces_gamma_and_is_stationary():
    r = make_garch_t_returns(4000, omega=1e-6, alpha=0.06, beta=0.88, nu=7, seed=7)
    m = GjrGarchArch().fit(r)
    p = m.params
    assert "gamma" in p  # GJR 多出非對稱項
    assert all(np.isfinite(v) for v in p.values())
    # GJR 平穩條件：α + β + 0.5γ < 1
    assert p["alpha"] + p["beta"] + 0.5 * p["gamma"] < 1.0
    assert p["nu"] > 3.0  # Student-t


def test_gjr_arch_params_full_vector_length_six():
    r = make_garch_t_returns(1000, omega=1e-6, alpha=0.06, beta=0.88, nu=8, seed=1)
    m = GjrGarchArch().fit(r)
    # 完整 arch 向量 [mu, omega, alpha[1], gamma[1], beta[1], nu]
    assert m.arch_params.shape == (6,)


def test_gjr_filter_forecast_matches_fit_forecast():
    r = make_garch_t_returns(1500, omega=1e-6, alpha=0.06, beta=0.88, nu=8, seed=13)
    m = GjrGarchArch().fit(r)
    filtered = garch_filter_forecast(m.arch_params, r, 21, o=1)
    assert filtered.shape == (21,)
    assert np.allclose(filtered, m.forecast(21))


def test_gjr_filter_residuals_matches_fit_scale():
    rng = np.random.default_rng(3)
    idx = pd.date_range("2018-01-01", periods=400, freq="B")
    r = pd.Series(rng.standard_normal(400) * 0.01, index=idx)
    m = GjrGarchArch().fit(r)
    resid = garch_filter_residuals(m.arch_params, r, o=1)
    assert np.allclose(resid.to_numpy(), m.standardized_residuals.to_numpy(), atol=1e-8)


def test_standard_garch_unchanged_length_five():
    # 回歸保護：標準 GARCH 路徑（o=0）向量仍 5、無 gamma。
    r = make_garch_t_returns(1000, omega=1e-6, alpha=0.08, beta=0.90, nu=8, seed=1)
    m = GarchArch().fit(r)
    assert m.arch_params.shape == (5,)
    assert "gamma" not in m.params
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_models/test_gjr_garch.py -v`
Expected: FAIL（`ImportError: cannot import name 'GjrGarchArch'`）

- [ ] **Step 3: 實作 GJR 能力**

改 `quantcore/models/volatility/garch_arch.py`：

`_build_arch_model` 加 `o` 參數：

```python
def _build_arch_model(scaled_array: np.ndarray, o: int = 0):
    """建 GARCH(1,1)-t（×100 尺度）。o>0 啟用 GJR 非對稱項。_estimate 與濾波
    共用，使模型規格單一來源——規格若變（dist/p/o/q）兩條路徑不會靜默分歧。"""
    from arch import arch_model

    return arch_model(scaled_array, mean="Constant", vol="GARCH", p=1, o=o, q=1, dist="t")
```

`GarchArch` 加類別屬性與依名稱取參（讓子類重用同一 `_estimate`）：

```python
class GarchArch(VolatilityModel):
    enforce_stationarity = True
    _min_obs = 100  # GARCH-t MLE 需足夠樣本
    _o = 0  # arch 非對稱階數；GjrGarchArch 覆寫為 1

    def _estimate(self, scaled_returns: pd.Series) -> None:
        am = _build_arch_model(scaled_returns.to_numpy(), o=self._o)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = am.fit(disp="off", show_warning=False)
        if int(getattr(res, "convergence_flag", 1)) != 0:
            raise GarchDegenerateError(f"GARCH 優化未收斂（flag={res.convergence_flag}）")
        pr = res.params
        self._params = {
            "omega": float(pr["omega"]),
            "alpha": float(pr["alpha[1]"]),
            "beta": float(pr["beta[1]"]),
            "nu": float(pr["nu"]),
        }
        if self._o >= 1:
            self._params["gamma"] = float(pr["gamma[1]"])
        if not all(np.isfinite(v) for v in self._params.values()):
            raise GarchDegenerateError("GARCH 參數含非有限值")
        self._res = res
        self._index = scaled_returns.index
        self._scaled = scaled_returns
        self._arch_params = np.asarray(res.params.to_numpy(), dtype="float64")
```

`_forecast_scaled` 沿用（arch analytic forecast 對 GJR 亦適用，無需改）。

在檔尾新增子類（放在 `GarchArch` class 之後、模組函式之前）：

```python
class GjrGarchArch(GarchArch):
    """GJR-GARCH(1,1)-t：加非對稱槓桿項 γ（arch o=1）。其餘估計/預測/殘差
    慣例全繼承 GarchArch（×100 尺度、Student-t、analytic 多步）。"""

    _o = 1
```

`garch_filter_forecast` / `garch_filter_residuals` 加 `o` 參數：

```python
def garch_filter_forecast(
    fixed_params: np.ndarray, returns: pd.Series, horizon: int, o: int = 0
) -> np.ndarray:
    if horizon < 1:
        raise ValueError(f"horizon 必須 ≥ 1，收到 {horizon}")
    r = returns.astype("float64").dropna()
    am = _build_arch_model(r.to_numpy() * _SCALE, o=o)
    res = am.fix(np.asarray(fixed_params, dtype="float64"))
    fc = res.forecast(horizon=horizon, method="analytic", reindex=False)
    out = np.asarray(fc.variance.to_numpy()[-1], dtype="float64") / (_SCALE**2)
    if not np.all(np.isfinite(out)):
        raise GarchDegenerateError("濾波多步預測含非有限值（固定參數退化）")
    return out


def garch_filter_residuals(
    fixed_params: np.ndarray, returns: pd.Series, o: int = 0
) -> pd.Series:
    r = returns.astype("float64").dropna()
    am = _build_arch_model(r.to_numpy() * _SCALE, o=o)
    res = am.fix(np.asarray(fixed_params, dtype="float64"))
    cond_vol = np.asarray(res.conditional_volatility, dtype="float64")
    return pd.Series(r.to_numpy() * _SCALE / cond_vol, index=r.index)
```

（保留兩函式原有 docstring 內容，僅加 `o` 參數與 `o=o` 傳遞。）

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_models/test_gjr_garch.py tests/test_models/test_garch_arch.py -v`
Expected: PASS（新 GJR 測試綠、既有 GARCH 測試不回歸）

- [ ] **Step 5: 提交**

```bash
git add quantcore/models/volatility/garch_arch.py tests/test_models/test_gjr_garch.py
git commit -m "feat(vol): GjrGarchArch 子類 + 濾波 o 參數(GJR-GARCH)"
```

---

## Task 2: 平穩性條件納入 γ（INV-4）

**Files:**
- Modify: `quantcore/models/volatility/base.py:61-65`
- Test: `tests/test_models/test_gjr_garch.py`（加一則）

- [ ] **Step 1: 寫失敗測試（γ 使 persistence 逼近 1 時被擋）**

在 `tests/test_models/test_gjr_garch.py` 末尾加：

```python
def test_stationarity_check_counts_half_gamma():
    # 直接驗 base 平穩檢查：α+β=0.95 但 α+β+0.5γ≥1 應被擋為 GarchDegenerateError。
    from quantcore.models.volatility.base import GarchDegenerateError, VolatilityModel

    class _Fake(VolatilityModel):
        enforce_stationarity = True

        def __init__(self, params):
            self._p = params

        @property
        def params(self):
            return self._p

        @property
        def standardized_residuals(self):  # pragma: no cover - 未用
            raise NotImplementedError

        def _estimate(self, scaled_returns):  # pragma: no cover - 未用
            raise NotImplementedError

        def _forecast_scaled(self, horizon):  # pragma: no cover - 未用
            raise NotImplementedError

    # α+β=0.95 < 1（舊條件會放行），但 +0.5*0.2=1.05 ≥ 1 → 應擋
    m = _Fake({"alpha": 0.10, "beta": 0.85, "gamma": 0.20})
    with pytest.raises(GarchDegenerateError):
        m._check_stationarity()
    # 純 GARCH（無 gamma）行為不變：α+β=0.95 放行
    _Fake({"alpha": 0.10, "beta": 0.85})._check_stationarity()  # 不拋
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_models/test_gjr_garch.py::test_stationarity_check_counts_half_gamma -v`
Expected: FAIL（舊條件 α+β=0.95<1 未擋，無例外拋出）

- [ ] **Step 3: 修改 `_check_stationarity`**

`quantcore/models/volatility/base.py`：

```python
    def _check_stationarity(self) -> None:
        p = self.params
        # GJR 平穩條件 α+β+0.5γ<1（對稱分布下負向指標期望=0.5）；
        # 純 GARCH gamma 預設 0，退化為 α+β<1。
        persistence = p.get("alpha", 0.0) + p.get("beta", 0.0) + 0.5 * p.get("gamma", 0.0)
        if persistence >= 1.0:
            raise GarchDegenerateError(f"非平穩：α+β+0.5γ={persistence:.4f} ≥ 1（多步預測會發散）")
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_models/test_gjr_garch.py tests/test_invariants/test_garch_conventions.py -v`
Expected: PASS（新平穩測試綠、INV-4 全綠）

- [ ] **Step 5: 提交**

```bash
git add quantcore/models/volatility/base.py tests/test_models/test_gjr_garch.py
git commit -m "feat(vol): 平穩條件納入 0.5γ(GJR, INV-4)"
```

---

## Task 3: fit_volatility 支援 "gjr_garch" spec

**Files:**
- Modify: `quantcore/models/volatility/__init__.py:44-58`
- Test: `tests/test_models/test_fit_volatility.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_models/test_fit_volatility.py` 末尾加：

```python
def test_gjr_garch_spec_fits_gjr_model():
    from quantcore.models.volatility import fit_volatility
    from quantcore.models.volatility.garch_arch import GjrGarchArch

    out = fit_volatility("gjr_garch", _good_returns(), ewma_lambda=0.94)
    assert isinstance(out.model, GjrGarchArch)
    assert out.fell_back is False
    assert "gamma" in out.model.params


def test_gjr_garch_spec_falls_back_to_ewma_on_degenerate(monkeypatch):
    from quantcore.models.volatility import fit_volatility
    from quantcore.models.volatility.base import GarchDegenerateError
    from quantcore.models.volatility.ewma import Ewma
    from quantcore.models.volatility.garch_arch import GjrGarchArch

    def _boom(self, scaled):
        raise GarchDegenerateError("forced")

    monkeypatch.setattr(GjrGarchArch, "_estimate", _boom)
    out = fit_volatility("gjr_garch", _good_returns(), ewma_lambda=0.94)
    assert isinstance(out.model, Ewma)
    assert out.fell_back is True
```

（`_good_returns` 已在該檔既有；若未 import GjrGarchArch/monkeypatch，測試內就地 import。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_models/test_fit_volatility.py -k gjr -v`
Expected: FAIL（`ValueError: 未知 vol spec：'gjr_garch'`）

- [ ] **Step 3: 加 gjr_garch 分支**

`quantcore/models/volatility/__init__.py`，在 `garch_arch` 分支後、`ewma` 分支前插入：

```python
    if spec == "gjr_garch":
        try:
            return FitOutcome(GjrGarchArch().fit(returns), False, None)
        except GarchDegenerateError as exc:
            return FitOutcome(Ewma(ewma_lambda).fit(returns), True, str(exc))
```

並在檔頭 import：

```python
from quantcore.models.volatility.garch_arch import GarchArch, GjrGarchArch
```

同步更新 `fit_volatility` docstring 末句「可用：garch_arch | gjr_garch | ewma」與 raise 訊息，並把 `GjrGarchArch` 加進 `__all__`。

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_models/test_fit_volatility.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add quantcore/models/volatility/__init__.py tests/test_models/test_fit_volatility.py
git commit -m "feat(vol): fit_volatility 支援 gjr_garch spec(含 EWMA fallback)"
```

---

## Task 4: VolForecaster 支援 GJR（快取 o、last_params 取 γ）

**Files:**
- Modify: `quantcore/models/volatility/forecaster.py`
- Test: `tests/test_models/test_forecaster.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_models/test_forecaster.py` 末尾加：

```python
def test_gjr_spec_accepted_and_last_params_has_gamma():
    r = _returns()
    f = VolForecaster("gjr_garch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    s = f.refit("AAA", r)
    assert 0.01 < s < 2.0
    assert f.last_fell_back("AAA") is False
    lp = f.last_params("AAA")
    assert lp is not None and "gamma" in lp  # GJR 診斷須含 γ
    assert {"omega", "alpha", "beta", "nu", "gamma"} <= set(lp)


def test_gjr_filter_matches_gjr_filter_forecast():
    from quantcore.models.volatility.base import annualize_variance_path
    from quantcore.models.volatility.garch_arch import GjrGarchArch, garch_filter_forecast

    r = _returns()
    f = VolForecaster("gjr_garch", ewma_lambda=0.94, horizon=21, garch_window=1000)
    f.refit("AAA", r)
    got = f.filter("AAA", r)
    params = GjrGarchArch().fit(r.iloc[-1000:]).arch_params
    expected = annualize_variance_path(garch_filter_forecast(params, r.iloc[-1000:], 21, o=1))
    assert got == expected
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_models/test_forecaster.py -k gjr -v`
Expected: FAIL（`ValueError: VolForecaster 不支援 vol_model='gjr_garch'`）

- [ ] **Step 3: 修改 forecaster**

`quantcore/models/volatility/forecaster.py`：

`_CacheEntry` 加 `arch_o`：

```python
@dataclass(frozen=True)
class _CacheEntry:
    kind: str  # 'garch' | 'ewma'
    arch_params: np.ndarray | None
    fell_back: bool
    arch_o: int = 0  # GARCH 非對稱階數（GJR=1）；濾波與 last_params 取 γ 用
```

`__init__` 的 spec 檢查放寬：

```python
        if spec not in ("garch_arch", "gjr_garch", "ewma"):
            raise ValueError(
                f"VolForecaster 不支援 vol_model={spec!r}（可用：garch_arch | gjr_garch | ewma）"
            )
```

`refit` 記錄 arch_o（GjrGarchArch 是 GarchArch 子類，isinstance 仍為 True）：

```python
    def refit(self, ticker: str, returns: pd.Series) -> float:
        outcome = fit_volatility(self._spec, self._tail(returns), ewma_lambda=self._ewma_lambda)
        if isinstance(outcome.model, GarchArch):
            self._cache[ticker] = _CacheEntry(
                "garch", outcome.model.arch_params, outcome.fell_back, outcome.model._o
            )
        else:
            self._cache[ticker] = _CacheEntry("ewma", None, outcome.fell_back)
        self._resid[ticker] = outcome.model.standardized_residuals
        return annualized_forecast_vol(outcome.model, self._horizon)
```

`filter` 的 garch 分支傳 `o`：

```python
        if entry.kind == "garch":
            self._resid[ticker] = garch_filter_residuals(
                entry.arch_params, window, o=entry.arch_o
            )
            return annualize_variance_path(
                garch_filter_forecast(entry.arch_params, window, self._horizon, o=entry.arch_o)
            )
```

`last_params` 依 arch_o 分支（GJR 向量多 γ、位置右移）：

```python
    def last_params(self, ticker: str) -> dict[str, float] | None:
        """GARCH ticker 回 {omega,alpha,beta,nu}（GJR 另含 gamma）；EWMA/fallback 回 None。"""
        entry = self._cache[ticker]
        if entry.kind != "garch" or entry.arch_params is None:
            return None
        p = entry.arch_params
        if entry.arch_o >= 1:
            # [mu, omega, alpha[1], gamma[1], beta[1], nu]
            return {
                "omega": float(p[1]),
                "alpha": float(p[2]),
                "gamma": float(p[3]),
                "beta": float(p[4]),
                "nu": float(p[5]),
            }
        # [mu, omega, alpha[1], beta[1], nu]
        return {
            "omega": float(p[1]),
            "alpha": float(p[2]),
            "beta": float(p[3]),
            "nu": float(p[4]),
        }
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_models/test_forecaster.py -v`
Expected: PASS（新 GJR 測試綠、既有 garch_arch 測試不回歸）

- [ ] **Step 5: 提交**

```bash
git add quantcore/models/volatility/forecaster.py tests/test_models/test_forecaster.py
git commit -m "feat(vol): VolForecaster 支援 gjr_garch(快取 o、last_params 取 γ)"
```

---

## Task 5: full_gjr 策略 + 註冊

**Files:**
- Create: `quantcore/backtest/strategies/full_gjr.py`
- Modify: `quantcore/backtest/strategies/__init__.py`
- Test: `tests/test_backtest/test_full_gjr.py`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_backtest/test_full_gjr.py`：

```python
"""full_gjr：繼承 full，波動引擎換 GJR-GARCH（§6.3 擴充）。"""

from __future__ import annotations

import numpy as np
import pytest

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategies import STRATEGIES
from quantcore.backtest.strategies.full import Full
from quantcore.backtest.strategies.full_gjr import FullGjr
from quantcore.backtest.strategy import DecisionEvent
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def _snap(n=320):
    dates = make_dates(n)
    rng = np.random.default_rng(1)
    prices = {}
    for i, tk in enumerate(["A", "B", "C", "D"]):
        prices[tk] = list(100 * np.cumprod(1 + rng.normal(0.0003 * (i + 1), 0.01, n)))
    return make_snapshot(prices, dates), dates


def _cfg(vol_model="garch_arch"):
    return make_cfg(
        ["A", "B", "C", "D"],
        risk={"vol_model": vol_model, "garch_window": 200},
        signal={"top_k": 2, "momentum_lookback": 120, "momentum_skip": 5},
        universe={"min_history_days": 130},
    )


def test_full_gjr_registered():
    assert STRATEGIES["full_gjr"] is FullGjr


def test_full_gjr_forecaster_uses_gjr_regardless_of_config():
    # 內部強制 GJR：即使 config.vol_model=garch_arch，forecaster spec 仍為 gjr_garch。
    strat = FullGjr(_cfg(vol_model="garch_arch"))
    assert strat._forecaster._spec == "gjr_garch"


def test_full_gjr_runs_and_weights_sum_to_one():
    snap, dates = _snap()
    dec = FullGjr(_cfg()).decide(make_view(snap, dates[300]), DecisionEvent.SELECTION)
    assert dec is not None
    assert sum(dec.target_weights.values()) == pytest.approx(1.0)
    assert dec.diagnostics.sigma_p > 0
    assert len(dec.diagnostics.selected) == 2


def test_full_gjr_selection_layer_matches_full():
    # full_gjr 與 full 只差 vol 引擎——選股（selected）相同；σ̂ 因引擎不同可異。
    snap, dates = _snap()
    view = make_view(snap, dates[300])
    df = Full(_cfg()).decide(view, DecisionEvent.SELECTION)
    dg = FullGjr(_cfg()).decide(view, DecisionEvent.SELECTION)
    assert df.diagnostics.selected == dg.diagnostics.selected
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_full_gjr.py -v`
Expected: FAIL（`ModuleNotFoundError: full_gjr`）

- [ ] **Step 3: 建立策略並註冊**

建立 `quantcore/backtest/strategies/full_gjr.py`：

```python
"""full_gjr —— full 策略但波動引擎改用 GJR-GARCH（非對稱項 γ）。

除 vol 引擎外，選股/inverse-vol/absmom/波動目標曝險全繼承 Full。內部強制
gjr_garch spec（不依賴 config.vol_model），使 full vs full_gjr 可同 suite 對比。
Step 2（σ̂_i→inverse-vol）與 Step 3（σ̂_p→曝險）共用此 forecaster，同時改用新變異數。
"""

from __future__ import annotations

from quantcore.backtest.strategies.full import Full
from quantcore.config import QuantConfig
from quantcore.models.volatility.forecaster import VolForecaster


class FullGjr(Full):
    strategy_id = "full_gjr"

    def __init__(self, cfg: QuantConfig) -> None:
        super().__init__(cfg)
        self._forecaster = VolForecaster(
            "gjr_garch",
            cfg.risk.ewma_lambda,
            cfg.risk.forecast_horizon,
            cfg.risk.garch_window,
        )
```

改 `quantcore/backtest/strategies/__init__.py`：加 import、加入 `STRATEGIES` dict、加入 `__all__`：

```python
from quantcore.backtest.strategies.full_gjr import FullGjr
```

```python
    Full.strategy_id: Full,
    FullGjr.strategy_id: FullGjr,
    FullErc.strategy_id: FullErc,
```

`__all__` 加 `"FullGjr"`。

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/test_full_gjr.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add quantcore/backtest/strategies/full_gjr.py quantcore/backtest/strategies/__init__.py tests/test_backtest/test_full_gjr.py
git commit -m "feat(strategy): full_gjr(繼承 full，強制 GJR forecaster)"
```

---

## Task 6: 前端 GARCH 頁顯示 γ

**Files:**
- Modify: `quantcore/presentation/web/routes/garch.py:29-45,72`
- Test: `tests/test_presentation/test_garch_page.py`

- [ ] **Step 1: 寫失敗測試（persistence 納入 0.5γ、γ 在系列中）**

建立 `tests/test_presentation/test_garch_page.py`：

```python
"""GARCH 頁：GJR run 顯示 γ、persistence 納入 0.5γ；純 GARCH 回歸不變。"""

from __future__ import annotations

import pandas as pd

from quantcore.presentation.web.routes.garch import _param_rows


def _sub(params):
    return pd.DataFrame(
        [{"decision_date": pd.Timestamp("2020-01-02"), "garch_params": {"AAA": params}}]
    )


def test_persistence_includes_half_gamma_for_gjr():
    rows = _param_rows(_sub({"omega": 1e-6, "alpha": 0.05, "beta": 0.88, "gamma": 0.10, "nu": 7.0}))
    assert len(rows) == 1
    r = rows[0]
    assert r["gamma"] == 0.10  # γ 帶入列（供軌跡圖）
    assert r["persistence"] == 0.05 + 0.88 + 0.5 * 0.10


def test_persistence_unchanged_for_standard_garch():
    rows = _param_rows(_sub({"omega": 1e-6, "alpha": 0.08, "beta": 0.90, "nu": 8.0}))
    r = rows[0]
    assert "gamma" not in r
    assert r["persistence"] == 0.08 + 0.90
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_presentation/test_garch_page.py -v`
Expected: FAIL（`KeyError`/persistence 未含 0.5γ）

- [ ] **Step 3: 修改 garch.py**

`_param_rows` 的 persistence 改為納入 0.5γ（gamma 值本身已由 `**p` 帶入）：

```python
                        "persistence": p["alpha"] + p["beta"] + 0.5 * p.get("gamma", 0.0),
```

參數軌跡圖（`garch` 函式內，原第 72 行）：GJR run 的 `pt` 會含 `gamma` 欄，加入系列：

```python
        cols = ["omega", "alpha", "beta", "nu", "persistence"]
        if "gamma" in tp.columns:
            cols.insert(2, "gamma")  # α 之後、β 之前，呼應參數向量順序
        named = {c: (tp["date"], tp[c]) for c in cols}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_presentation/test_garch_page.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add quantcore/presentation/web/routes/garch.py tests/test_presentation/test_garch_page.py
git commit -m "feat(web): GARCH 頁顯示 γ、persistence 納入 0.5γ"
```

---

## Task 7: 全測試回歸 + 消融證據 + PROGRESS

**Files:**
- Create: `<scratchpad>/gjr_ablation.py`（研究輕流程，不進 repo）
- Modify: `PROGRESS.md`

- [ ] **Step 1: 跑全測試套件（含 INV）確認無回歸**

Run: `uv run pytest -q`
Expected: 全綠（INV-1~6、models、backtest、presentation）。若有紅先修到綠再繼續。

- [ ] **Step 2: 寫消融腳本（full vs full_gjr）**

在 scratchpad 建 `gjr_ablation.py`：以既有 snapshot 對同一 config 跑 `full` 與 `full_gjr`（透過引擎 CLI 或 runner），輸出兩者績效指標（年化報酬/波動/Sharpe/MaxDD）與曝險 E(t) 序列的差異摘要。腳本內容依既有 `quantcore/experiments/` 與 runner 介面撰寫（比照 memory 的研究快流程：scratchpad 腳本、輕配置）。

- [ ] **Step 3: 跑消融、產出對比**

Run: `uv run python <scratchpad>/gjr_ablation.py`
Expected: 印出 full vs full_gjr 指標表 + E(t) 差異；確認 GJR 帶來可辨識差異（非數值全同）。

- [ ] **Step 4: 記錄結論到 PROGRESS.md**

在 `PROGRESS.md` 新增一節，摘要：full_gjr 上線、GJR vs GARCH 消融結論（指標差異、是否採用/保留為候選）、對應 commit。

- [ ] **Step 5: 提交**

```bash
git add PROGRESS.md
git commit -m "docs(progress): full_gjr 上線 + GJR vs GARCH 消融結論"
```

---

## 完成後

依 `superpowers:finishing-a-development-branch`：全測試綠後，`feature/full-gjr-strategy` 以 `--no-ff` 併回 main（QuantSystem 慣例）。
