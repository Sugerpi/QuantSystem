# Phase 3 — 訊號與組合層 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 實作動量選標的、絕對動量過濾、inverse-vol 相對權重與 `sixty_forty`/`mom_only`/`mom_ivol` 三策略，並提供通用消融引擎產出比較表。

**Architecture:** 純函數上游（`signals/`、`models/volatility/`）收 DataFrame/Series，不 import backtest；`portfolio/` 做選擇與權重；策略層（`backtest/strategies/`）為組合根，串起 `elig → momentum → topK → σ̂ → weighting → absmom → cash`。波動率暫用 63 日滾動標準差 placeholder，Phase 4 由 GARCH 取代。

**Tech Stack:** Python 3.12、pandas、numpy、pydantic v2、pytest、uv、ruff。

**Spec:** `docs/superpowers/specs/2026-07-19-phase3-signals-portfolio-design.md`

**執行守則：**
- 每個測試指令用 `uv run pytest ...`。
- lint/format：`uv run ruff check .` 與 `uv run ruff format .`。
- 提交訊息末行加：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`（本 plan 的 commit 範例省略該行，實作時補上）。
- 分支已在 `feature/phase3-signals-portfolio`。

---

## 檔案結構

| 檔案 | 責任 |
|------|------|
| `quantcore/config/schema.py`（改） | `VolModel` 加 `rolling_std`；`RiskConfig` 加 `vol_window` |
| `quantcore/config/default.yaml`（改） | `risk.vol_model: rolling_std`、`risk.vol_window: 63` |
| `quantcore/signals/momentum.py`（新） | `cross_sectional_momentum`、`absolute_momentum`（純函數） |
| `quantcore/portfolio/selection.py`（改） | 新增 `select_top_k` |
| `quantcore/portfolio/weighting.py`（新） | `inverse_vol`、`equal_weight`、`route_absmom_to_cash` |
| `quantcore/models/volatility/__init__.py`（新） | `estimate_annualized_vol` 派發（未實作模型丟 NotImplementedError） |
| `quantcore/models/volatility/rolling_std.py`（新） | `annualized_vol` |
| `quantcore/backtest/strategies/momentum_base.py`（新） | `MomentumStrategy` 抽象基底（DRY 兩支動量策略） |
| `quantcore/backtest/strategies/mom_only.py`（新） | `MomentumOnly` |
| `quantcore/backtest/strategies/mom_ivol.py`（新） | `MomentumInverseVol` |
| `quantcore/backtest/strategies/sixty_forty.py`（新） | `SixtyForty` |
| `quantcore/backtest/strategies/__init__.py`（改） | 註冊三策略 |
| `quantcore/experiments/ablation.py`（新） | 通用消融引擎 + CLI |
| `tests/fixtures/synthetic.py`（改） | 新增 `make_cfg` 測試 config 工廠 |
| `tests/test_signals/…`、`tests/test_portfolio/…`、`tests/test_backtest/…`、`tests/test_experiments/…`（新測試） | 各層測試 |

---

## Task 1: Config — 加入 rolling_std 波動模型與 vol_window

**Files:**
- Modify: `quantcore/config/schema.py:16` (`VolModel`)、`RiskConfig`（約 53-60）
- Modify: `quantcore/config/default.yaml:19-24`（risk 區塊）
- Test: `tests/test_config.py`（既有檔，追加測試）

- [ ] **Step 1: 追加失敗測試**

在 `tests/test_config.py` 末端加入：

```python
def test_rolling_std_vol_model_and_window_load():
    from quantcore.config import load_config

    cfg = load_config("quantcore/config/default.yaml")
    assert cfg.risk.vol_model == "rolling_std"
    assert cfg.risk.vol_window == 63


def test_vol_window_must_be_positive():
    import pytest
    from pydantic import ValidationError

    from quantcore.config import QuantConfig, load_config

    raw = load_config("quantcore/config/default.yaml").model_dump(mode="json")
    raw["risk"]["vol_window"] = 0
    with pytest.raises(ValidationError):
        QuantConfig.model_validate(raw)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_config.py::test_rolling_std_vol_model_and_window_load -v`
Expected: FAIL（`vol_model` 為 `garch_arch`，且 `vol_window` 欄位不存在 → ValidationError 或 AttributeError）

- [ ] **Step 3: 改 schema**

`quantcore/config/schema.py` 第 16 行：

```python
VolModel = Literal["garch_arch", "garch_own", "ewma", "rolling_std"]
```

`RiskConfig`（在 `exposure_min` 後加一欄）：

```python
class RiskConfig(_Strict):
    """波動率/相關模型與曝險控制（規格 §1.6、§5）。"""

    vol_model: VolModel
    corr_model: CorrModel
    vol_target_annual: float = Field(gt=0)
    exposure_band: float = Field(ge=0, le=1)
    exposure_min: float = Field(ge=0, le=1)
    vol_window: int = Field(gt=0)  # rolling_std 的滾動窗（交易日）；Phase 4 GARCH 取代後仍保留供 EWMA/基線
```

- [ ] **Step 4: 改 default.yaml**

`quantcore/config/default.yaml` 的 risk 區塊改為：

```yaml
risk:                               # §1.6 / §5
  vol_model: rolling_std            # Phase 3 暫定（唯一實作）；Phase 4 → garch_arch。garch_arch | garch_own | ewma | rolling_std
  corr_model: dcc                   # dcc | ewma
  vol_target_annual: 0.10           # σ* 年化波動目標
  exposure_band: 0.10               # 曝險更新帶
  exposure_min: 0.10                # E_min
  vol_window: 63                    # rolling_std 滾動窗（交易日），Phase 3 placeholder
```

- [ ] **Step 5: 跑測試確認通過**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS（全部）

- [ ] **Step 6: Commit**

```bash
git add quantcore/config/schema.py quantcore/config/default.yaml tests/test_config.py
git commit -m "feat(config): 加入 rolling_std 波動模型與 vol_window（Phase 3 placeholder）"
```

---

## Task 2: signals — 橫斷面 12-1 動量

**Files:**
- Create: `quantcore/signals/momentum.py`
- Test: `tests/test_signals/__init__.py`（空）、`tests/test_signals/test_momentum.py`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_signals/__init__.py`（空檔）與 `tests/test_signals/test_momentum.py`：

```python
"""橫斷面與絕對動量（規格 §1.3、§1.4）。"""

import numpy as np

from quantcore.signals.momentum import cross_sectional_momentum
from tests.fixtures.synthetic import make_dates, make_snapshot


def test_momentum_uses_skip_and_lookback_offsets():
    # lookback=4, skip=1：M = s[t-1]/s[t-4] - 1
    dates = make_dates(6)
    snap = make_snapshot({"A": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]}, dates)
    out = cross_sectional_momentum(snap["prices"], lookback=4, skip=1)
    # s[-2]=14, s[-5]=11 → 14/11 - 1
    assert out["A"] == np.float64(14.0 / 11.0 - 1.0)


def test_asset_with_too_few_bars_is_omitted():
    dates = make_dates(6)
    snap = make_snapshot(
        {"A": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0], "SHORT": [1.0, 2.0, 3.0]}, dates
    )
    out = cross_sectional_momentum(snap["prices"], lookback=4, skip=1)
    assert "A" in out
    assert "SHORT" not in out  # 只有 3 根 bar < lookback+1=5


def test_multiple_tickers_scored_independently():
    dates = make_dates(6)
    snap = make_snapshot(
        {"UP": [10, 10, 10, 10, 10, 20], "DOWN": [20, 20, 20, 20, 20, 10]}, dates
    )
    out = cross_sectional_momentum(snap["prices"], lookback=4, skip=1)
    # skip=1 → 用 s[-2]（尚未反映最後一天跳動），兩檔 s[-2]/s[-5] 皆為 1.0 → 0.0
    assert out["UP"] == 0.0
    assert out["DOWN"] == 0.0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_signals/test_momentum.py -v`
Expected: FAIL（`ModuleNotFoundError: quantcore.signals.momentum`）

- [ ] **Step 3: 實作**

建立 `quantcore/signals/momentum.py`：

```python
"""動量訊號（規格 §1.3、§1.4）。純函數，收 DataFrame，不 import backtest。

依賴方向（CLAUDE.md）：signals 為上游，只認 pandas。呼叫端（策略）持有 view，
把 view.prices / view.rates 傳入——比照 portfolio/selection.py 的設計。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_DAYS_PER_YEAR = 252


def cross_sectional_momentum(
    prices: pd.DataFrame, lookback: int, skip: int
) -> dict[str, float]:
    """12-1 橫斷面動量：M_i = adj_close[t-skip] / adj_close[t-lookback] - 1。

    prices 為 point-in-time 切片（≤ t），須含 'ticker'/'date'/'adj_close'。
    bar 數 < lookback+1 者不產生分數（算不出 t-lookback）。
    """
    out: dict[str, float] = {}
    for ticker, g in prices.groupby("ticker", sort=True):
        s = g.sort_values("date")["adj_close"].to_numpy()
        if len(s) < lookback + 1:
            continue
        out[ticker] = float(s[-1 - skip] / s[-1 - lookback] - 1.0)
    return out
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_signals/test_momentum.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/signals/momentum.py tests/test_signals/
git commit -m "feat(signals): 橫斷面 12-1 動量（純函數，§1.3）"
```

---

## Task 3: signals — 絕對動量過濾

**Files:**
- Modify: `quantcore/signals/momentum.py`
- Test: `tests/test_signals/test_momentum.py`（追加）

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_signals/test_momentum.py` 追加：

```python
from quantcore.signals.momentum import absolute_momentum


def test_absmom_pass_when_return_beats_tbill():
    # dtb3=2.52% → 日利率 0.0001；lookback=4 → tbill_cum≈(1.0001)^4-1≈0.0004
    dates = make_dates(5)
    snap = make_snapshot(
        {"UP": [10.0, 10.0, 10.0, 10.0, 11.0], "DOWN": [10.0, 10.0, 10.0, 10.0, 9.0]},
        dates,
        dtb3_percent=2.52,
    )
    out = absolute_momentum(snap["prices"], snap["rates"], lookback=4)
    assert out["UP"] is True  # TR=+0.10 > tbill
    assert out["DOWN"] is False  # TR=-0.10 < tbill


def test_absmom_omits_short_history():
    dates = make_dates(5)
    snap = make_snapshot({"SHORT": [1.0, 2.0, 3.0]}, dates)
    out = absolute_momentum(snap["prices"], snap["rates"], lookback=4)
    assert "SHORT" not in out
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_signals/test_momentum.py::test_absmom_pass_when_return_beats_tbill -v`
Expected: FAIL（`absolute_momentum` 未定義 → ImportError）

- [ ] **Step 3: 實作**

在 `quantcore/signals/momentum.py` 追加：

```python
def absolute_momentum(
    prices: pd.DataFrame, rates: pd.DataFrame, lookback: int
) -> dict[str, bool]:
    """時間序列動量（§1.4）：過去 lookback 日總報酬是否勝過同期 T-bill 累積。

    tbill 累積：DTB3（年化 %）→ 日利率（÷100 ÷252），取 ≤ t 的末 lookback 日複利。
    所有資產共用同一 t，故 tbill 窗只算一次。bar 不足者略過（與動量一致）。
    """
    r = rates.sort_values("date")["DTB3"].to_numpy() / 100.0 / _DAYS_PER_YEAR
    daily = r[-lookback:]
    tbill_cum = float(np.prod(1.0 + daily) - 1.0)

    out: dict[str, bool] = {}
    for ticker, g in prices.groupby("ticker", sort=True):
        s = g.sort_values("date")["adj_close"].to_numpy()
        if len(s) < lookback + 1:
            continue
        tr = float(s[-1] / s[-1 - lookback] - 1.0)
        out[ticker] = bool(tr - tbill_cum > 0.0)
    return out
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_signals/test_momentum.py -v`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
git add quantcore/signals/momentum.py tests/test_signals/test_momentum.py
git commit -m "feat(signals): 絕對動量過濾（時間序列動量 vs T-bill，§1.4）"
```

---

## Task 4: portfolio — 排序取 K（含平手規則）

**Files:**
- Modify: `quantcore/portfolio/selection.py`
- Test: `tests/test_portfolio/test_selection.py`（追加）

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_portfolio/test_selection.py` 末端追加：

```python
from quantcore.portfolio.selection import select_top_k


def test_select_top_k_by_score_desc():
    scores = {"A": 0.1, "B": 0.5, "C": 0.3}
    assert select_top_k(scores, k=2) == ["B", "C"]


def test_select_top_k_tie_broken_by_ticker_alpha():
    scores = {"A": 0.3, "C": 0.3, "D": 0.2, "B": 0.1}
    # A 與 C 同分 0.3 → 字母序 A 先；取 2 → ["A", "C"]
    assert select_top_k(scores, k=2) == ["A", "C"]


def test_select_top_k_caps_at_available():
    scores = {"A": 0.3, "B": 0.1}
    assert select_top_k(scores, k=5) == ["A", "B"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_portfolio/test_selection.py::test_select_top_k_by_score_desc -v`
Expected: FAIL（`select_top_k` 未定義 → ImportError）

- [ ] **Step 3: 實作**

在 `quantcore/portfolio/selection.py` 末端追加：

```python
def select_top_k(momentum_scores: dict[str, float], k: int) -> list[str]:
    """依分數降序取前 K；平手以 ticker 字母序（決定性，§1.3）。"""
    ranked = sorted(momentum_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [ticker for ticker, _ in ranked[:k]]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_portfolio/test_selection.py -v`
Expected: PASS（含既有 eligible 測試）

- [ ] **Step 5: Commit**

```bash
git add quantcore/portfolio/selection.py tests/test_portfolio/test_selection.py
git commit -m "feat(portfolio): select_top_k 排序取 K + 字母序平手（§1.3）"
```

---

## Task 5: models/volatility — 滾動標準差 placeholder + 派發

**Files:**
- Create: `quantcore/models/volatility/__init__.py`、`quantcore/models/volatility/rolling_std.py`
- Test: `tests/test_models/__init__.py`（空）、`tests/test_models/test_rolling_std.py`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_models/__init__.py`（空）與 `tests/test_models/test_rolling_std.py`：

```python
"""滾動標準差波動 placeholder（Phase 3；Phase 4 由 GARCH 取代）。"""

import numpy as np
import pandas as pd
import pytest

from quantcore.models.volatility import estimate_annualized_vol
from quantcore.models.volatility.rolling_std import annualized_vol


def test_annualized_vol_matches_formula():
    s = pd.Series([100.0, 101.0, 103.0, 102.0, 105.0, 104.0])
    expected = s.pct_change().dropna().iloc[-3:].std(ddof=1) * np.sqrt(252)
    assert annualized_vol(s, window=3) == pytest.approx(expected)


def test_higher_dispersion_gives_higher_vol():
    calm = pd.Series([100.0, 100.5, 101.0, 101.5, 102.0, 102.5])
    wild = pd.Series([100.0, 110.0, 95.0, 115.0, 90.0, 120.0])
    assert annualized_vol(wild, 4) > annualized_vol(calm, 4)


def test_dispatch_rolling_std():
    s = pd.Series([100.0, 101.0, 103.0, 102.0, 105.0])
    assert estimate_annualized_vol("rolling_std", s, 3) == annualized_vol(s, 3)


def test_dispatch_unimplemented_raises():
    s = pd.Series([100.0, 101.0, 103.0])
    with pytest.raises(NotImplementedError):
        estimate_annualized_vol("garch_arch", s, 3)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_models/test_rolling_std.py -v`
Expected: FAIL（`ModuleNotFoundError: quantcore.models.volatility`）

- [ ] **Step 3: 實作**

建立 `quantcore/models/volatility/rolling_std.py`：

```python
"""滾動標準差波動估計（Phase 3 placeholder）。

規格 §1.6 Step 1 的 σ̂ 在 v1 應由 GARCH 產生；Phase 3 尚無 GARCH，暫以末 window 日
報酬的樣本標準差年化代替。Phase 4 的 models/volatility/base.py 模板會收編此估計，
並以 QLIKE/MZ-R²（§5.4）評估後由 GARCH 取代預設。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_DAYS_PER_YEAR = 252


def annualized_vol(adj_close: pd.Series, window: int) -> float:
    """末 window 日報酬的樣本標準差 × sqrt(252)。"""
    rets = adj_close.astype("float64").pct_change().dropna()
    tail = rets.iloc[-window:]
    return float(tail.std(ddof=1) * np.sqrt(_DAYS_PER_YEAR))
```

建立 `quantcore/models/volatility/__init__.py`：

```python
"""波動率模型層（規格 §5）。Phase 3 只有 rolling_std placeholder。"""

from __future__ import annotations

import pandas as pd

from quantcore.models.volatility.rolling_std import annualized_vol


def estimate_annualized_vol(vol_model: str, adj_close: pd.Series, window: int) -> float:
    """依 config 的 vol_model 派發 σ̂ 估計。未實作模型明確拋錯，不靜默。"""
    if vol_model == "rolling_std":
        return annualized_vol(adj_close, window)
    raise NotImplementedError(f"vol_model={vol_model!r} 尚未實作（Phase 4）")


__all__ = ["annualized_vol", "estimate_annualized_vol"]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_models/test_rolling_std.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/models/volatility/ tests/test_models/
git commit -m "feat(models): 滾動標準差波動 placeholder + vol_model 派發（§1.6/§5）"
```

---

## Task 6: portfolio — inverse-vol、等權、絕對動量轉現金

**Files:**
- Create: `quantcore/portfolio/weighting.py`
- Test: `tests/test_portfolio/test_weighting.py`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_portfolio/test_weighting.py`：

```python
"""相對權重與絕對動量轉現金（規格 §1.6 Step 2、§1.4）。"""

import pytest

from quantcore.portfolio.weighting import equal_weight, inverse_vol, route_absmom_to_cash


def test_inverse_vol_lower_weight_for_higher_vol():
    w = inverse_vol({"A": 0.1, "B": 0.2})
    # 1/0.1=10, 1/0.2=5, sum=15
    assert w["A"] == pytest.approx(10 / 15)
    assert w["B"] == pytest.approx(5 / 15)
    assert sum(w.values()) == pytest.approx(1.0)


def test_equal_weight_sums_to_one():
    w = equal_weight(["A", "B", "C"])
    assert w == {"A": pytest.approx(1 / 3), "B": pytest.approx(1 / 3), "C": pytest.approx(1 / 3)}


def test_route_absmom_moves_failed_weight_to_cash():
    weights, cash = route_absmom_to_cash({"A": 0.6, "B": 0.4}, {"A": True, "B": False})
    assert weights == {"A": 0.6}
    assert cash == pytest.approx(0.4)
    assert sum(weights.values()) + cash == pytest.approx(1.0)


def test_route_absmom_all_fail_all_cash():
    weights, cash = route_absmom_to_cash({"A": 0.5, "B": 0.5}, {"A": False, "B": False})
    assert weights == {}
    assert cash == pytest.approx(1.0)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_portfolio/test_weighting.py -v`
Expected: FAIL（`ModuleNotFoundError: quantcore.portfolio.weighting`）

- [ ] **Step 3: 實作**

建立 `quantcore/portfolio/weighting.py`：

```python
"""相對權重與絕對動量轉現金（規格 §1.6 Step 2、§1.4）。純函數。

依賴方向：portfolio 上游於 backtest，只認基本型別，不 import view/策略。
"""

from __future__ import annotations


def inverse_vol(sigma_hat: dict[str, float]) -> dict[str, float]:
    """w_i = (1/σ̂_i) / Σ_j(1/σ̂_j)，Σ w = 1（§1.6 Step 2）。σ̂ 須為正。"""
    inv = {t: 1.0 / s for t, s in sigma_hat.items()}
    total = sum(inv.values())
    return {t: v / total for t, v in inv.items()}


def equal_weight(assets: list[str]) -> dict[str, float]:
    """入選資產等權，Σ w = 1。"""
    w = 1.0 / len(assets)
    return {t: w for t in assets}


def route_absmom_to_cash(
    w_risky: dict[str, float], absmom_pass: dict[str, bool]
) -> tuple[dict[str, float], float]:
    """絕對動量 fail 的資產配額整份轉入現金（§1.4）。不在 pass 檔上重新歸一。

    回傳 (通過檔的權重, 現金權重)。兩者總和守恆 = Σ w_risky。
    """
    weights = {t: w for t, w in w_risky.items() if absmom_pass.get(t, False)}
    cash = sum(w for t, w in w_risky.items() if not absmom_pass.get(t, False))
    return weights, cash
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_portfolio/test_weighting.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/portfolio/weighting.py tests/test_portfolio/test_weighting.py
git commit -m "feat(portfolio): inverse-vol/等權/絕對動量轉現金（§1.6 Step 2、§1.4）"
```

---

## Task 7: 測試 config 工廠 + sixty_forty 策略

**Files:**
- Modify: `tests/fixtures/synthetic.py`（加 `make_cfg`）
- Create: `quantcore/backtest/strategies/sixty_forty.py`
- Modify: `quantcore/backtest/strategies/__init__.py`
- Test: `tests/test_backtest/test_strategies.py`（追加）

- [ ] **Step 1: 加 make_cfg 工廠**

在 `tests/fixtures/synthetic.py` 末端追加：

```python
def make_cfg(menu: list[str], **overrides: dict):
    """由 default.yaml 生一份測試 config，套用巢狀覆寫後重新驗證。

    overrides 以巢狀 dict 給，如 make_cfg(["SPY"], signal={"top_k": 2}).
    """
    from quantcore.config import QuantConfig, load_config

    raw = load_config("quantcore/config/default.yaml").model_dump(mode="json")
    raw["universe"]["menu"] = list(menu)
    for section, values in overrides.items():
        raw[section].update(values)
    return QuantConfig.model_validate(raw)
```

- [ ] **Step 2: 寫失敗測試**

在 `tests/test_backtest/test_strategies.py` 末端追加：

```python
from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategy import DecisionEvent
from quantcore.backtest.strategies import STRATEGIES
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def test_sixty_forty_targets_60_40():
    dates = make_dates(10)
    snap = make_snapshot(
        {"SPY": list(100.0 + range(10)), "IEF": list(50.0 + range(10))}, dates
    )
    cfg = make_cfg(["SPY", "IEF"])
    strat = STRATEGIES["sixty_forty"](cfg)
    d = strat.decide(make_view(snap, dates[-1]), DecisionEvent.SELECTION)
    assert d.target_weights == {"SPY": 0.6, "IEF": 0.4, "CASH": 0.0}


def test_sixty_forty_no_action_on_exposure_check():
    dates = make_dates(10)
    snap = make_snapshot({"SPY": list(100.0 + range(10))}, dates)
    cfg = make_cfg(["SPY", "IEF"])
    strat = STRATEGIES["sixty_forty"](cfg)
    assert strat.decide(make_view(snap, dates[-1]), DecisionEvent.EXPOSURE_CHECK) is None
```

> 註：`list(100.0 + range(10))` 在 Python 無效；測試請用 `[100.0 + i for i in range(10)]`。實作測試時直接用 list comprehension。

- [ ] **Step 3: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_strategies.py::test_sixty_forty_targets_60_40 -v`
Expected: FAIL（`KeyError: 'sixty_forty'`）

- [ ] **Step 4: 實作 sixty_forty**

建立 `quantcore/backtest/strategies/sixty_forty.py`：

```python
"""sixty_forty —— 60% SPY / 40% IEF（規格 §6.3）。

存在理由：傳統配置基準。每個選擇日重平衡回 60/40。
"""

from __future__ import annotations

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy


class SixtyForty(Strategy):
    strategy_id = "sixty_forty"

    @property
    def warmup_days(self) -> int:
        return 0

    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        if event is not DecisionEvent.SELECTION:
            return None
        return Decision(
            target_weights={"SPY": 0.6, "IEF": 0.4, CASH: 0.0},
            diagnostics=Diagnostics(eligible=["IEF", "SPY"], selected=["IEF", "SPY"]),
        )
```

在 `quantcore/backtest/strategies/__init__.py` 加入 import 與註冊：

```python
"""策略註冊表（規格 §6.3）。"""

from quantcore.backtest.strategies.bh_spy import BuyHoldSPY
from quantcore.backtest.strategies.ew_menu import EqualWeightMenu
from quantcore.backtest.strategies.sixty_forty import SixtyForty

STRATEGIES = {
    BuyHoldSPY.strategy_id: BuyHoldSPY,
    EqualWeightMenu.strategy_id: EqualWeightMenu,
    SixtyForty.strategy_id: SixtyForty,
}

__all__ = ["STRATEGIES", "BuyHoldSPY", "EqualWeightMenu", "SixtyForty"]
```

- [ ] **Step 5: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/test_strategies.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add quantcore/backtest/strategies/sixty_forty.py quantcore/backtest/strategies/__init__.py tests/fixtures/synthetic.py tests/test_backtest/test_strategies.py
git commit -m "feat(strategies): sixty_forty 60/40 基準 + make_cfg 測試工廠（§6.3）"
```

---

## Task 8: 動量策略基底 + mom_only

**Files:**
- Create: `quantcore/backtest/strategies/momentum_base.py`、`quantcore/backtest/strategies/mom_only.py`
- Modify: `quantcore/backtest/strategies/__init__.py`
- Test: `tests/test_backtest/test_mom_strategies.py`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_backtest/test_mom_strategies.py`：

```python
"""動量策略（規格 §1.3/§1.4/§6.3）。以 decide() 直接驗證，避開 clock 設置。"""

from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategy import DecisionEvent
from quantcore.backtest.strategies import STRATEGIES
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot

# lookback=4, skip=1, top_k=2, min_history=5, vol_window=3
_CFG_KW = dict(
    signal={"momentum_lookback": 4, "momentum_skip": 1, "top_k": 2},
    universe={"min_history_days": 5},
    risk={"vol_model": "rolling_std", "vol_window": 3},
)


def _snap(dates):
    # WIN/MID 動量為正且通過絕對動量；LOSE 動量最低、被排除
    return make_snapshot(
        {
            "WIN": [10.0, 11.0, 12.0, 13.0, 15.0, 18.0],
            "MID": [10.0, 10.5, 11.0, 11.5, 12.5, 13.0],
            "LOSE": [20.0, 19.0, 18.0, 17.0, 16.0, 15.0],
        },
        dates,
    )


def test_mom_only_selects_top_k_equal_weight():
    dates = make_dates(6)
    cfg = make_cfg(["WIN", "MID", "LOSE"], **_CFG_KW)
    strat = STRATEGIES["mom_only"](cfg)
    d = strat.decide(make_view(_snap(dates), dates[-1]), DecisionEvent.SELECTION)
    # 前 2 高動量 = WIN, MID；等權 0.5/0.5，皆通過絕對動量
    assert d.diagnostics.selected == ["WIN", "MID"] or d.diagnostics.selected == ["MID", "WIN"]
    assert set(d.diagnostics.selected) == {"WIN", "MID"}
    assert d.target_weights["WIN"] == 0.5
    assert d.target_weights["MID"] == 0.5
    assert d.target_weights["CASH"] == 0.0


def test_mom_only_diagnostics_populated_but_no_sigma():
    dates = make_dates(6)
    cfg = make_cfg(["WIN", "MID", "LOSE"], **_CFG_KW)
    strat = STRATEGIES["mom_only"](cfg)
    d = strat.decide(make_view(_snap(dates), dates[-1]), DecisionEvent.SELECTION)
    assert set(d.diagnostics.momentum_scores) == {"WIN", "MID", "LOSE"}  # 全合格
    assert set(d.diagnostics.absmom) == {"WIN", "MID"}  # 只入選檔
    assert d.diagnostics.sigma_hat is None  # mom_only 無波動
    assert d.diagnostics.w_risky == {"WIN": 0.5, "MID": 0.5}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_mom_strategies.py::test_mom_only_selects_top_k_equal_weight -v`
Expected: FAIL（`KeyError: 'mom_only'`）

- [ ] **Step 3: 實作基底**

建立 `quantcore/backtest/strategies/momentum_base.py`：

```python
"""動量策略共用基底（DRY：mom_only 與 mom_ivol 只差相對權重演算法）。

組合根：策略層在依賴鏈下游，串起 signals → portfolio → models。
"""

from __future__ import annotations

from abc import abstractmethod

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.portfolio.selection import eligible_assets, select_top_k
from quantcore.portfolio.weighting import route_absmom_to_cash
from quantcore.signals.momentum import absolute_momentum, cross_sectional_momentum


class MomentumStrategy(Strategy):
    """選標的 + 絕對動量 + 相對權重。子類實作 _risky_weights。"""

    @property
    def warmup_days(self) -> int:
        # momentum 需 lookback+1 根 bar 才算得出 t-lookback
        return self._cfg.signal.momentum_lookback + 1

    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        if event is not DecisionEvent.SELECTION:
            return None
        cfg = self._cfg
        elig = eligible_assets(
            view.prices, cfg.universe.menu, cfg.universe.min_history_days
        )
        scores = cross_sectional_momentum(
            view.prices, cfg.signal.momentum_lookback, cfg.signal.momentum_skip
        )
        scores = {t: v for t, v in scores.items() if t in elig}
        if not scores:
            return None
        selected = select_top_k(scores, cfg.signal.top_k)
        w_risky, sigma_hat = self._risky_weights(selected, view)
        absmom_all = absolute_momentum(view.prices, view.rates, cfg.signal.momentum_lookback)
        absmom = {t: bool(absmom_all.get(t, False)) for t in selected}
        weights, cash = route_absmom_to_cash(w_risky, absmom)
        target = {**weights, CASH: cash}
        return Decision(
            target_weights=target,
            diagnostics=Diagnostics(
                eligible=elig,
                selected=selected,
                momentum_scores=scores,
                absmom=absmom,
                sigma_hat=sigma_hat,
                w_risky=w_risky,
            ),
        )

    @abstractmethod
    def _risky_weights(
        self, selected: list[str], view: PointInTimeView
    ) -> tuple[dict[str, float], dict[str, float] | None]:
        """回傳 (相對權重 Σ=1, σ̂ 或 None)。"""
```

建立 `quantcore/backtest/strategies/mom_only.py`：

```python
"""mom_only —— 動量選 K + 等權 + 絕對動量（規格 §6.3）。

存在理由：消融——只有選擇層，無 inverse-vol、無波動目標。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategies.momentum_base import MomentumStrategy
from quantcore.portfolio.weighting import equal_weight


class MomentumOnly(MomentumStrategy):
    strategy_id = "mom_only"

    def _risky_weights(
        self, selected: list[str], view: PointInTimeView
    ) -> tuple[dict[str, float], None]:
        return equal_weight(selected), None
```

在 `quantcore/backtest/strategies/__init__.py` 註冊（加 import、加入 dict 與 `__all__`）：

```python
from quantcore.backtest.strategies.mom_only import MomentumOnly
# ... STRATEGIES 加：MomentumOnly.strategy_id: MomentumOnly
# ... __all__ 加 "MomentumOnly"
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/test_mom_strategies.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/strategies/momentum_base.py quantcore/backtest/strategies/mom_only.py quantcore/backtest/strategies/__init__.py tests/test_backtest/test_mom_strategies.py
git commit -m "feat(strategies): mom_only + 動量策略共用基底（§6.3）"
```

---

## Task 9: mom_ivol 策略

**Files:**
- Create: `quantcore/backtest/strategies/mom_ivol.py`
- Modify: `quantcore/backtest/strategies/__init__.py`
- Test: `tests/test_backtest/test_mom_strategies.py`（追加）

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_backtest/test_mom_strategies.py` 追加：

```python
def test_mom_ivol_weights_are_inverse_vol():
    dates = make_dates(6)
    cfg = make_cfg(["WIN", "MID", "LOSE"], **_CFG_KW)
    strat = STRATEGIES["mom_ivol"](cfg)
    d = strat.decide(make_view(_snap(dates), dates[-1]), DecisionEvent.SELECTION)
    assert set(d.diagnostics.selected) == {"WIN", "MID"}
    assert d.diagnostics.sigma_hat is not None
    assert set(d.diagnostics.sigma_hat) == {"WIN", "MID"}
    # inverse-vol：波動較低者權重較高，且兩檔權重和（未被 absmom 擋下時）=1
    assert sum(d.target_weights[t] for t in d.diagnostics.selected) == \
        __import__("pytest").approx(1.0)
    win_vol = d.diagnostics.sigma_hat["WIN"]
    mid_vol = d.diagnostics.sigma_hat["MID"]
    if win_vol > mid_vol:
        assert d.target_weights["WIN"] < d.target_weights["MID"]
    else:
        assert d.target_weights["WIN"] > d.target_weights["MID"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_mom_strategies.py::test_mom_ivol_weights_are_inverse_vol -v`
Expected: FAIL（`KeyError: 'mom_ivol'`）

- [ ] **Step 3: 實作**

建立 `quantcore/backtest/strategies/mom_ivol.py`：

```python
"""mom_ivol —— 動量 + inverse-vol（無波動目標）（規格 §6.3）。

存在理由：消融——有相對權重層但無總曝險控制（E=1）。
σ̂ 由 config 的 vol_model 決定，Phase 3 為 rolling_std。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategies.momentum_base import MomentumStrategy
from quantcore.models.volatility import estimate_annualized_vol
from quantcore.portfolio.weighting import inverse_vol


class MomentumInverseVol(MomentumStrategy):
    strategy_id = "mom_ivol"

    def _risky_weights(
        self, selected: list[str], view: PointInTimeView
    ) -> tuple[dict[str, float], dict[str, float]]:
        model = self._cfg.risk.vol_model
        window = self._cfg.risk.vol_window
        sigma_hat = {
            t: estimate_annualized_vol(model, view.history(t)["adj_close"], window)
            for t in selected
        }
        return inverse_vol(sigma_hat), sigma_hat
```

在 `quantcore/backtest/strategies/__init__.py` 註冊 `MomentumInverseVol`（import、dict、`__all__`）。

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/test_mom_strategies.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/strategies/mom_ivol.py quantcore/backtest/strategies/__init__.py tests/test_backtest/test_mom_strategies.py
git commit -m "feat(strategies): mom_ivol 動量 + inverse-vol（§6.3）"
```

---

## Task 10: decisions.parquet 完整落盤（AC-2 端到端）

**Files:**
- Test: `tests/test_experiments/test_decisions_diagnostics.py`

驗證 mom_ivol 經 `run_experiment` 落地後，`decisions.parquet` 的 diagnostics 欄位完整（AC-2）。

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_experiments/test_decisions_diagnostics.py`：

```python
"""AC-2：決策 diagnostics 完整落盤（規格 §6.2）。"""

import json

import pandas as pd

from quantcore.experiments.runner import run_experiment
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def test_mom_ivol_decisions_have_full_diagnostics(tmp_path):
    dates = make_dates(30)
    prices = {
        "WIN": [10.0 + i * 0.6 for i in range(30)],
        "MID": [10.0 + i * 0.3 for i in range(30)],
        "LOSE": [40.0 - i * 0.3 for i in range(30)],
        "SPY": [100.0 + i * 0.2 for i in range(30)],
        "IEF": [50.0 + i * 0.05 for i in range(30)],
    }
    snap = make_snapshot(prices, dates)
    cfg = make_cfg(
        ["WIN", "MID", "LOSE", "SPY", "IEF"],
        signal={"momentum_lookback": 4, "momentum_skip": 1, "top_k": 2},
        universe={"min_history_days": 5},
        risk={"vol_model": "rolling_std", "vol_window": 3},
        schedule={"selection_interval": 3, "exposure_check_interval": 2},
        backtest={"start": dates[0].date().isoformat(), "initial_nav": 1.0},
    )
    run_dir = run_experiment(
        cfg=cfg, snapshot=snap, out_root=tmp_path, label="t", strategy_ids=["mom_ivol"]
    )
    dec = pd.read_parquet(run_dir / "decisions.parquet")
    assert len(dec) > 0
    row = dec.iloc[0]
    assert json.loads(row["momentum_scores"])  # 非空
    assert json.loads(row["absmom"])
    assert json.loads(row["sigma_hat"])
    assert json.loads(row["w_risky"])
    # Phase 4 才有的曝險欄維持缺值
    assert pd.isna(row["sigma_p"])
    assert pd.isna(row["exposure_applied"])
```

- [ ] **Step 2: 跑測試確認狀態**

Run: `uv run pytest tests/test_experiments/test_decisions_diagnostics.py -v`
Expected: 若前面 Task 正確，此測試應直接 PASS（落盤路徑已存在）。若 FAIL，依訊息修正（常見：`make_cfg` 的 `backtest.start` 需為 ISO 字串；clock 間隔 ≥ 2）。

- [ ] **Step 3: （若失敗才做）修正**

依 Step 2 失敗訊息調整測試或既有 `_flatten_decisions`。預期不需改產品碼。

- [ ] **Step 4: Commit**

```bash
git add tests/test_experiments/test_decisions_diagnostics.py
git commit -m "test(experiments): AC-2 mom_ivol decisions 完整落盤驗證（§6.2）"
```

---

## Task 11: experiments/ablation.py — 通用消融引擎 + CLI（AC-1）

**Files:**
- Create: `quantcore/experiments/ablation.py`
- Test: `tests/test_experiments/test_ablation.py`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_experiments/test_ablation.py`：

```python
"""AC-1：消融跑得動並產出比較表（規格 §7.3）。"""

import pandas as pd

from quantcore.experiments.ablation import run_ablation
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def _cfg_and_snap():
    dates = make_dates(30)
    prices = {
        "WIN": [10.0 + i * 0.6 for i in range(30)],
        "MID": [10.0 + i * 0.3 for i in range(30)],
        "LOSE": [40.0 - i * 0.3 for i in range(30)],
        "SPY": [100.0 + i * 0.2 for i in range(30)],
        "IEF": [50.0 + i * 0.05 for i in range(30)],
    }
    snap = make_snapshot(prices, dates)
    cfg = make_cfg(
        ["WIN", "MID", "LOSE", "SPY", "IEF"],
        signal={"momentum_lookback": 4, "momentum_skip": 1, "top_k": 2},
        universe={"min_history_days": 5},
        risk={"vol_model": "rolling_std", "vol_window": 3},
        schedule={"selection_interval": 3, "exposure_check_interval": 2},
        backtest={"start": dates[0].date().isoformat(), "initial_nav": 1.0},
    )
    return cfg, snap


def test_ablation_produces_comparison_table(tmp_path):
    cfg, snap = _cfg_and_snap()
    run_dir = run_ablation(
        base_cfg=cfg,
        snapshot=snap,
        strategy_ids=["mom_only", "mom_ivol", "ew_menu"],
        param_grid={"signal.top_k": [2, 3]},
        out_root=tmp_path,
        label="test",
    )
    table = pd.read_parquet(run_dir / "comparison.parquet")
    assert len(table) > 0
    # 三策略 × (baseline + top_k 變體)
    assert set(table["strategy_id"]) == {"mom_only", "mom_ivol", "ew_menu"}
    for col in ("cell_label", "strategy_id", "sharpe", "max_drawdown"):
        assert col in table.columns


def test_ablation_grid_varies_one_param_at_a_time(tmp_path):
    cfg, snap = _cfg_and_snap()
    run_dir = run_ablation(
        base_cfg=cfg,
        snapshot=snap,
        strategy_ids=["mom_only"],
        param_grid={"signal.top_k": [2, 3], "costs.per_side_bps": [0, 10]},
        out_root=tmp_path,
        label="test",
    )
    table = pd.read_parquet(run_dir / "comparison.parquet")
    # cells: baseline + top_k(2 值) + cost(2 值) = 5 個 cell（一次動一參數，含 baseline）
    assert set(table["cell_label"]) == {
        "baseline",
        "signal.top_k=2",
        "signal.top_k=3",
        "costs.per_side_bps=0",
        "costs.per_side_bps=10",
    }
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_experiments/test_ablation.py -v`
Expected: FAIL（`ModuleNotFoundError: quantcore.experiments.ablation`）

- [ ] **Step 3: 實作**

建立 `quantcore/experiments/ablation.py`：

```python
"""通用消融引擎（規格 §7.3）。

一次跑多策略 × 參數敏感度（一次動一參數），彙整成單一比較表。
「跟得上多少跑多少」：只跑已註冊、已實作的策略；vol_target 敏感度留 Phase 4。

紀律（§7.3）：敏感度表用途是確認結論對參數擾動穩健，不是挑最好一格回填 config。
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

import pandas as pd

from quantcore.backtest.clock import EventClock
from quantcore.backtest.engine import run_strategy
from quantcore.backtest.metrics import compute_metrics
from quantcore.backtest.strategies import STRATEGIES
from quantcore.config import QuantConfig, load_config
from quantcore.data.snapshot import load_snapshot
from quantcore.experiments.tracking import create_run_dir

_DAYS_PER_YEAR = 252


def _apply_override(raw: dict, dotted_key: str, value) -> dict:
    """回傳套用單一 'section.field' 覆寫後的 config dict 副本。"""
    out = copy.deepcopy(raw)
    section, field = dotted_key.split(".", 1)
    out[section][field] = value
    return out


def _build_cells(base_raw: dict, param_grid: dict[str, list]) -> list[tuple[str, dict]]:
    """一次動一參數：baseline + 每個參數的每個值。回傳 (cell_label, config_dict)。"""
    cells: list[tuple[str, dict]] = [("baseline", base_raw)]
    for key, values in param_grid.items():
        for v in values:
            cells.append((f"{key}={v}", _apply_override(base_raw, key, v)))
    return cells


def _evaluate(cfg: QuantConfig, snapshot: dict, strategy_ids: list[str]) -> dict[str, dict]:
    """跑指定策略，回傳 {strategy_id: metrics dict}。in-memory，不落 run 目錄。"""
    d = snapshot["prices"]["date"]
    days = pd.DatetimeIndex(sorted(d.unique()))
    days = days[days >= pd.Timestamp(cfg.backtest.start)]

    strategies = [STRATEGIES[sid](cfg) for sid in strategy_ids]
    warmup = max(s.warmup_days for s in strategies)
    clock = EventClock(
        trading_days=days,
        warmup=warmup,
        selection_interval=cfg.schedule.selection_interval,
        exposure_check_interval=cfg.schedule.exposure_check_interval,
    )

    result: dict[str, dict] = {}
    for s in strategies:
        nav_df, _w, _dec = run_strategy(snapshot, clock, s, cfg)
        rate = (
            snapshot["rates"].set_index("date")["DTB3"].reindex(nav_df["date"]).ffill().bfill()
            / 100.0
            / _DAYS_PER_YEAR
        )
        result[s.strategy_id] = compute_metrics(
            nav=nav_df["nav"].reset_index(drop=True),
            rate_daily=rate.reset_index(drop=True),
            total_turnover=float(nav_df["turnover"].sum()),
            total_cost=float(nav_df["cost"].sum()),
        )
    return result


def run_ablation(
    base_cfg: QuantConfig,
    snapshot: dict,
    strategy_ids: list[str],
    param_grid: dict[str, list],
    out_root: str | Path,
    label: str,
    now: pd.Timestamp | None = None,
) -> Path:
    """跑消融矩陣並寫出單一比較表，回傳 run 目錄。"""
    now = pd.Timestamp.now() if now is None else now
    base_raw = base_cfg.model_dump(mode="json")

    rows = []
    for cell_label, cfg_dict in _build_cells(base_raw, param_grid):
        cfg = QuantConfig.model_validate(cfg_dict)
        for sid, metrics in _evaluate(cfg, snapshot, strategy_ids).items():
            rows.append({"cell_label": cell_label, "strategy_id": sid, **metrics})

    table = pd.DataFrame(rows)
    run_dir = create_run_dir(out_root, f"{label}_ablation", now)
    table.to_parquet(run_dir / "comparison.parquet", index=False)
    _print_summary(table)
    return run_dir


def _print_summary(table: pd.DataFrame) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    base = table[table["cell_label"] == "baseline"].sort_values("sharpe", ascending=False)
    print("=== 消融比較表（baseline，依 Sharpe 排序）===")
    cols = [c for c in ("strategy_id", "sharpe", "max_drawdown", "calmar", "annualized_turnover") if c in base.columns]
    print(base[cols].to_string(index=False))


def _cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m quantcore.experiments.ablation")
    p.add_argument("--config", required=True)
    p.add_argument("--out-root", default="runs")
    p.add_argument("--label", default="default")
    p.add_argument(
        "--strategies",
        default="bh_spy,ew_menu,sixty_forty,mom_only,mom_ivol",
        help="逗號分隔；Phase 3 可跑者",
    )
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    snapshot = load_snapshot(cfg.snapshot)
    grid = {
        "signal.top_k": [3, 5, 8],
        "signal.momentum_lookback": [126, 252],
        "costs.per_side_bps": [0, 5, 10, 20],
    }
    run_dir = run_ablation(
        base_cfg=cfg,
        snapshot=snapshot,
        strategy_ids=[s.strip() for s in args.strategies.split(",") if s.strip()],
        param_grid=grid,
        out_root=args.out_root,
        label=args.label,
    )
    print(f"消融已完成：{run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_experiments/test_ablation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quantcore/experiments/ablation.py tests/test_experiments/test_ablation.py
git commit -m "feat(experiments): 通用消融引擎 + CLI（§7.3，AC-1）"
```

---

## Task 12: 全套綠 + lint + PROGRESS 更新

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: 跑全套測試**

Run: `uv run pytest -q`
Expected: 全綠（Phase 2 的 135 項 + Phase 3 新增）。0 failed。

- [ ] **Step 2: lint / format**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: All checks passed；all files already formatted。若 format 有動，跑 `uv run ruff format .` 後重新 `git add`。

- [ ] **Step 3: 更新 PROGRESS.md**

將 Phase 3 區塊的任務與 AC 勾選為完成，狀態改 ✅，並在「變更紀錄」加一行 2026-07-19 條目，記錄：
- 五策略（bh_spy/ew_menu/sixty_forty/mom_only/mom_ivol）可跑、通用消融引擎產出比較表（AC-1）、decisions.parquet 完整落盤（AC-2）。
- **規格偏離備忘**：`vol_model` 暫設 `rolling_std`（§7.2 範例為 garch_arch），Phase 4 GARCH 到位後翻回；`sixty_forty` 順手於 Phase 3 建（原不在 Phase 3 任務清單）；absmom 回看窗沿用 `momentum_lookback`（不新增參數）。

同時把總覽表 Phase 3 狀態由 ⬜ 改為 ✅。

- [ ] **Step 4: Commit**

```bash
git add PROGRESS.md
git commit -m "docs(phase3): 訊號與組合層完成，AC-1/AC-2 達成"
```

---

## Self-Review（撰寫者已核對）

**Spec 覆蓋：**
- §1.3 橫斷面動量 → Task 2；平手字母序 → Task 4。
- §1.4 絕對動量 + 轉現金 → Task 3、Task 6。
- §1.6 Step 2 inverse-vol / σ̂ placeholder → Task 5、Task 6、Task 9。
- §1.7 只在 SELECTION 動作 → Task 7/8（`event is not SELECTION` 回 None）。
- §6.2 Diagnostics 完整 → Task 8/9 填欄位 + Task 10 落盤驗證。
- §6.3 三策略 → Task 7/8/9。
- §7.3 消融矩陣 → Task 11。
- Config 硬規則（參數入 config）→ Task 1（vol_window）。

**Placeholder 掃描：** 無 TODO/TBD；每個改碼步驟均附完整程式碼。Task 7 Step 2 的 `list(100.0 + range(10))` 已加註為無效寫法、指示改用 list comprehension。

**型別一致：** `estimate_annualized_vol(vol_model, adj_close, window)`、`annualized_vol(adj_close, window)`、`select_top_k(scores, k)`、`inverse_vol(sigma_hat)`、`route_absmom_to_cash(w_risky, absmom_pass)->(weights, cash)`、`_risky_weights(selected, view)->(w_risky, sigma_hat|None)`、`run_ablation(base_cfg, snapshot, strategy_ids, param_grid, out_root, label, now)` 各處簽章一致。

**已知邊界：** momentum 需 `lookback+1` bar（Task 2 略過不足者、warmup=lookback+1）；`inverse_vol` 假設 σ̂>0（測試用非常數價格）；ablation in-memory 與 runner 的 rate/metrics 計算刻意重複一小段，未提前重構 runner 以控制 Phase 3 blast radius。
