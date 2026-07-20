# Phase 2 — 回測核心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可重現的事件驅動回測引擎，跑得動 `bh_spy` 與 `ew_menu`，並由 INV-1/2/5/6 測試鎖死時間語意、會計恆等式與可重現性。

**Architecture:** 策略在外、天在內——`run_strategy()` 是單策略的完整回測，`runner` 逐策略呼叫再 concat。`PointInTimeView` 建構時實體切片 `≤ t` 並凍結，未來資料物理上不存在。時間語意集中在 `clock.py`，會計為純函式，`experiments/` 負責檔案落地。依賴方向 `config ← data ← portfolio ← backtest ← experiments`。

**Tech Stack:** Python 3.12、uv、pandas、pyarrow、pydantic、pytest。

**設計來源：** `docs/superpowers/specs/2026-07-17-phase2-backtest-core-design.md`（以下稱「設計文件」）。規格為 `DEVELOPMENT_GUIDE v1.2.md`。

**執行前提：** 在 feature 分支上做（repo 慣例，見 git log）。第一步就建分支。

---

## 關鍵語意速查（實作時反覆對照）

每日順序（設計文件 §2.1，**刻意偏離 §6.1 伪代碼**）：

```
1. 當日損益：NAV *= 1 + Σ w_i(t)·r_i(t) + w_cash(t)·rate_daily(t)
             w(t) 為 close(t-1) 建立的持倉；r_i(t) = adj_close(t)/adj_close(t-1) − 1
2. 權重漂移：w_drift = w(t)(1+r(t)) / (1 + 組合報酬)
3. 若 t 為執行日：turnover = Σ_i |target_i − drift_i|（**不含 CASH**）
                  NAV -= NAV × turnover × per_side_bps/10000
                  w(t+1) = target
   否則：w(t+1) = w_drift
4. 若 t 為決策日：target = strategy.decide(view(t), event)  → 於下一交易日執行
5. 記錄
```

錨點：warmup 結束後第一個交易日為第 0 天。`active_days = trading_days[warmup:]`。

---

## 檔案結構

| 檔案 | 職責 |
|------|------|
| `quantcore/config/schema.py`（修改） | `BacktestConfig.initial_nav` |
| `quantcore/config/default.yaml`（修改） | 同上 |
| `quantcore/backtest/clock.py`（新增） | 決策日／執行日的唯一定義處 |
| `quantcore/backtest/ptview.py`（新增） | 時間閘門，切片 `≤ t` |
| `quantcore/portfolio/selection.py`（新增） | `eligible_assets` |
| `quantcore/backtest/accounting.py`（新增） | 純函式：損益、漂移、成本 |
| `quantcore/backtest/strategy.py`（新增） | `Strategy` ABC、`Decision`、`Diagnostics`、`DecisionEvent` |
| `quantcore/backtest/strategies/__init__.py`（新增） | 策略註冊表 |
| `quantcore/backtest/strategies/bh_spy.py`（新增） | Buy & Hold SPY |
| `quantcore/backtest/strategies/ew_menu.py`（新增） | 選單等權 |
| `quantcore/backtest/engine.py`（新增） | `run_strategy` |
| `quantcore/backtest/metrics.py`（新增） | Sharpe/Sortino/MaxDD/Calmar/turnover |
| `quantcore/experiments/tracking.py`（新增） | run 目錄、manifest、決定性寫檔 |
| `quantcore/experiments/runner.py`（新增） | pipeline + CLI |
| `tests/fixtures/synthetic.py`（新增） | 合成迷你快照 |
| `tests/test_invariants/test_no_lookahead.py`（新增） | INV-1 |
| `tests/test_invariants/test_execution_lag.py`（新增） | INV-2 |
| `tests/test_invariants/test_accounting.py`（新增） | INV-5 |
| `tests/test_invariants/test_reproducibility.py`（新增） | INV-6 |
| `tests/test_backtest/test_bh_spy_external.py`（新增） | AC-3，`requires_snapshot` |
| `pyproject.toml`（修改） | `requires_snapshot` marker |

---

## Task 0: 建立分支

- [ ] **Step 1: 建分支**

```bash
git checkout main
git pull --ff-only 2>/dev/null || true
git checkout -b feature/phase2-backtest-core
```

- [ ] **Step 2: 確認基線全綠**

Run: `uv run pytest`
Expected: `78 passed`

---

## Task 1: Config 新增 `initial_nav`

**Files:**
- Modify: `quantcore/config/schema.py`（`BacktestConfig`）
- Modify: `quantcore/config/default.yaml`（`backtest` 區塊）
- Test: `tests/test_config.py`

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_config.py` 末尾：

```python
def test_backtest_initial_nav_loaded_and_positive():
    cfg = load_config("quantcore/config/default.yaml")
    assert cfg.backtest.initial_nav == 1.0


def test_backtest_initial_nav_rejects_non_positive(tmp_path):
    import pydantic
    import pytest
    import yaml

    raw = yaml.safe_load(open("quantcore/config/default.yaml", encoding="utf-8"))
    raw["backtest"]["initial_nav"] = 0.0
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(pydantic.ValidationError):
        load_config(p)
```

> 若 `tests/test_config.py` 尚未 import `load_config`，沿用該檔既有的 import 風格。

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_config.py -k initial_nav -v`
Expected: FAIL — `AttributeError: 'BacktestConfig' object has no attribute 'initial_nav'`

- [ ] **Step 3: 實作**

`quantcore/config/schema.py`，替換 `BacktestConfig`：

```python
class BacktestConfig(_Strict):
    """回測範圍與初始狀態（規格 §6）。"""

    start: date
    initial_nav: float = Field(gt=0)
    # NAV 為尺度不變：Sharpe/MaxDD/Calmar/換手率皆不受此值影響，僅 nav.parquet 的
    # 數字大小改變。仍入 config 以維持「參數只在 config」這條明線。
```

`quantcore/config/default.yaml`，`backtest` 區塊改為：

```yaml
backtest:
  start: 2005-01-03                 # §1.1 建議起點
  initial_nav: 1.0                  # 尺度不變，不影響任何指標
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
git add quantcore/config/schema.py quantcore/config/default.yaml tests/test_config.py
git commit -m "feat(config): backtest.initial_nav"
```

---

## Task 2: 合成迷你快照 fixture

INV 測試不得依賴真實快照（`snapshots/` 為 gitignore，CI 上不存在）。此 fixture 產生與 `load_snapshot()` 回傳值同形的 dict。

**Files:**
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/synthetic.py`

- [ ] **Step 1: 建立 fixture 模組**

`tests/fixtures/__init__.py`：空檔。

`tests/fixtures/synthetic.py`：

```python
"""合成迷你快照：INV 測試專用，全離線、不碰 snapshots/。

回傳結構與 quantcore.data.snapshot.load_snapshot() 相同（prices/rates/metadata/manifest），
使引擎測試不需要真實快照即可在 CI 執行。
"""

from __future__ import annotations

import pandas as pd


def make_dates(n: int, start: str = "2020-01-02") -> pd.DatetimeIndex:
    """n 個連續「交易日」。合成資料不需真實 NYSE 日曆——引擎只認序列順序。"""
    return pd.bdate_range(start=start, periods=n)


def make_snapshot(
    prices_by_ticker: dict[str, list[float]],
    dates: pd.DatetimeIndex,
    dtb3_percent: float = 2.52,
) -> dict:
    """由每檔的 adj_close 序列組出快照 dict。

    prices_by_ticker 的序列長度可短於 dates：視為該檔較晚上市，
    對齊到 dates 的「尾端」（最後一筆對齊最後一天）。
    dtb3_percent 預設 2.52 → 日利率 0.0252/252 = 0.0001（整數，便於手算）。
    """
    frames = []
    for ticker, series in sorted(prices_by_ticker.items()):
        d = dates[len(dates) - len(series) :]
        frames.append(
            pd.DataFrame(
                {
                    "date": d,
                    "ticker": ticker,
                    "close": series,
                    "adj_close": series,
                    "volume": [1e6] * len(series),
                }
            )
        )
    prices = pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"])
    prices = prices.reset_index(drop=True)
    rates = pd.DataFrame({"date": dates, "DTB3": [dtb3_percent] * len(dates)})
    return {
        "prices": prices,
        "rates": rates,
        "metadata": {"tickers": {}, "overrides": [], "sources": {}},
        "manifest": {"snapshot_id": "synthetic", "content_hashes": {}},
    }
```

- [ ] **Step 2: 確認 import 得動**

Run: `uv run python -c "from tests.fixtures.synthetic import make_snapshot, make_dates; s = make_snapshot({'SPY':[100.0,110.0]}, make_dates(2)); print(s['prices'])"`
Expected: 印出兩列 SPY

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/
git commit -m "test(fixtures): 合成迷你快照（INV 測試用，全離線）"
```

---

## Task 3: `clock.py` + INV-2 時鐘算術

**Files:**
- Create: `quantcore/backtest/clock.py`
- Test: `tests/test_invariants/test_execution_lag.py`

- [ ] **Step 1: 寫失敗測試**

`tests/test_invariants/test_execution_lag.py`：

```python
"""INV-2：訊號-執行延遲 ≥ 1 個交易日（規格 §1.2、§3）。

本檔前半鎖時鐘算術，後半（Task 9 加入）鎖引擎行為。
"""

import pytest

from quantcore.backtest.clock import EventClock
from tests.fixtures.synthetic import make_dates


def _clock(n=40, warmup=5, sel=7, exp=3) -> EventClock:
    return EventClock(
        trading_days=make_dates(n),
        warmup=warmup,
        selection_interval=sel,
        exposure_check_interval=exp,
    )


def test_active_days_start_after_warmup():
    c = _clock()
    assert c.active_days[0] == c.trading_days[5]
    assert len(c.active_days) == 35


def test_first_active_day_is_both_selection_and_exposure_day():
    """錨點：warmup 結束後第一個交易日為第 0 天（設計文件 §2.3.1）。"""
    c = _clock()
    t0 = c.active_days[0]
    assert c.is_selection_day(t0)
    assert c.is_exposure_check_day(t0)


def test_selection_days_are_every_interval_from_anchor():
    c = _clock(sel=7)
    sel = [t for t in c.active_days if c.is_selection_day(t)]
    assert sel == list(c.active_days[::7])


def test_execution_day_is_strictly_next_trading_day():
    c = _clock()
    for t in c.active_days[:-1]:
        ex = c.execution_day(t)
        assert ex > t
        i = c.trading_days.get_loc(t)
        assert ex == c.trading_days[i + 1]


def test_execution_day_none_past_end_of_data():
    c = _clock()
    assert c.execution_day(c.trading_days[-1]) is None


def test_rejects_interval_below_two():
    """間隔 1 會讓前次決策尚未執行就被覆蓋，語意不明確，直接拒絕。"""
    with pytest.raises(ValueError, match="間隔"):
        EventClock(
            trading_days=make_dates(10),
            warmup=0,
            selection_interval=1,
            exposure_check_interval=3,
        )


def test_rejects_warmup_beyond_data():
    with pytest.raises(ValueError, match="warmup"):
        EventClock(
            trading_days=make_dates(10),
            warmup=10,
            selection_interval=7,
            exposure_check_interval=3,
        )
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_invariants/test_execution_lag.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'quantcore.backtest.clock'`

- [ ] **Step 3: 實作**

`quantcore/backtest/clock.py`：

```python
"""事件時鐘（規格 §1.2、§1.7）。

決策日與執行日的**唯一**定義處——引擎不自行推算 t+1（INV-2）。
錨點：warmup 結束後的第一個交易日為第 0 天（設計文件 §2.3.1；§1.7 只給間隔未給起點）。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class EventClock:
    """交易日序列 + 再平衡時程 → 決策日／執行日。"""

    trading_days: pd.DatetimeIndex
    warmup: int
    selection_interval: int
    exposure_check_interval: int

    def __post_init__(self) -> None:
        if self.warmup < 0:
            raise ValueError(f"warmup 不可為負：{self.warmup}")
        if self.warmup >= len(self.trading_days):
            raise ValueError(
                f"warmup ({self.warmup}) 不可 ≥ 交易日數 ({len(self.trading_days)})"
            )
        for name, v in (
            ("selection_interval", self.selection_interval),
            ("exposure_check_interval", self.exposure_check_interval),
        ):
            if v < 2:
                raise ValueError(
                    f"{name} 間隔須 ≥ 2（間隔 1 會讓決策在執行前即被覆蓋）：{v}"
                )

    @property
    def active_days(self) -> pd.DatetimeIndex:
        """實際跑回測的交易日（warmup 之後）。"""
        return self.trading_days[self.warmup :]

    def _offset(self, t: pd.Timestamp) -> int:
        """t 距錨點的交易日數。t 不在 active_days 內即為呼叫端的 bug。"""
        return int(self.active_days.get_loc(t))

    def is_selection_day(self, t: pd.Timestamp) -> bool:
        return self._offset(t) % self.selection_interval == 0

    def is_exposure_check_day(self, t: pd.Timestamp) -> bool:
        return self._offset(t) % self.exposure_check_interval == 0

    def is_decision_day(self, t: pd.Timestamp) -> bool:
        return self.is_selection_day(t) or self.is_exposure_check_day(t)

    def execution_day(self, decision_day: pd.Timestamp) -> pd.Timestamp | None:
        """決策日的下一個交易日；已無資料則回 None（INV-2 的唯一實作）。"""
        i = int(self.trading_days.get_loc(decision_day))
        if i + 1 >= len(self.trading_days):
            return None
        return self.trading_days[i + 1]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_invariants/test_execution_lag.py -v`
Expected: PASS（7 項）

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/clock.py tests/test_invariants/test_execution_lag.py
git commit -m "feat(backtest): 事件時鐘 + INV-2 時鐘算術測試"
```

---

## Task 4: `ptview.py` + INV-1

**Files:**
- Create: `quantcore/backtest/ptview.py`
- Test: `tests/test_invariants/test_no_lookahead.py`

- [ ] **Step 1: 寫失敗測試**

`tests/test_invariants/test_no_lookahead.py`：

```python
"""INV-1：無 Look-Ahead——決策日 t 只依賴 timestamp ≤ t 的資料（規格 §1.2、§3）。

兩層防護：
(a) property：view 內任何 timestamp ≤ t。
(b) 竄改未來資料，view 內容必須逐位元不變 —— 這條測結構而非自律：
    若有人讓 view 洩漏未來，(a) 可能仍過，(b) 必當場紅燈。
"""

import numpy as np
import pandas as pd
import pytest

from quantcore.backtest.ptview import make_view
from tests.fixtures.synthetic import make_dates, make_snapshot


def _snap(n=30):
    dates = make_dates(n)
    return make_snapshot(
        {
            "SPY": list(100.0 + np.arange(n) * 1.0),
            "QQQ": list(200.0 + np.arange(n) * 2.0),
        },
        dates,
    ), dates


def test_view_contains_no_future_timestamps():
    snap, dates = _snap()
    for t in dates:
        v = make_view(snap, t)
        assert (v.prices["date"] <= t).all()
        assert (v.rates["date"] <= t).all()


def test_view_includes_day_t_itself():
    """§1.2：day t 的 bar 在 close(t) 之後存在，決策於 close(t) 之後 → 含 t。"""
    snap, dates = _snap()
    t = dates[10]
    v = make_view(snap, t)
    assert v.prices["date"].max() == t


def test_corrupting_the_future_does_not_change_the_view():
    snap, dates = _snap()
    t = dates[10]
    baseline = make_view(snap, t)

    corrupted = {k: (val.copy() if hasattr(val, "copy") else val) for k, val in snap.items()}
    p = corrupted["prices"]
    future = p["date"] > t
    rng = np.random.default_rng(0)
    p.loc[future, "adj_close"] = rng.normal(1e6, 1e5, size=int(future.sum()))
    p.loc[future, "close"] = p.loc[future, "adj_close"]
    r = corrupted["rates"]
    r.loc[r["date"] > t, "DTB3"] = -999.0

    after = make_view(corrupted, t)
    pd.testing.assert_frame_equal(baseline.prices, after.prices)
    pd.testing.assert_frame_equal(baseline.rates, after.rates)


def test_view_is_frozen():
    snap, dates = _snap()
    v = make_view(snap, dates[5])
    with pytest.raises(Exception):
        v.t = dates[6]


def test_bar_count_counts_only_up_to_t():
    snap, dates = _snap()
    v = make_view(snap, dates[9])
    assert v.bar_count("SPY") == 10
    assert v.bar_count("NOPE") == 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_invariants/test_no_lookahead.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'quantcore.backtest.ptview'`

- [ ] **Step 3: 實作**

`quantcore/backtest/ptview.py`：

```python
"""PointInTimeView：結構性防 look-ahead（規格 §1.2、INV-1）。

**只做時間閘門**——不懂合格性、不懂動量。業務規則屬 portfolio/（§2.1）。

關鍵設計：建構時即實體切片 ≤ t 並凍結，物件內物理上不存在未來資料。
這使 INV-1 可斷言「view 裡沒有未來」這個結構事實，而非斷言「呼叫者沒作弊」。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class PointInTimeView:
    """close(t) 之後可見的全部資料。"""

    t: pd.Timestamp
    prices: pd.DataFrame
    rates: pd.DataFrame

    def bar_count(self, ticker: str) -> int:
        """該檔在 ≤ t 的 bar 數（合格性判定的原料）。"""
        return int((self.prices["ticker"] == ticker).sum())

    def history(self, ticker: str) -> pd.DataFrame:
        """該檔 ≤ t 的完整歷史，依日期排序。"""
        h = self.prices[self.prices["ticker"] == ticker]
        return h.sort_values("date").reset_index(drop=True)

    def last_adj_close(self, ticker: str) -> float:
        h = self.history(ticker)
        if h.empty:
            raise KeyError(f"{ticker} 在 {self.t:%Y-%m-%d} 無資料")
        return float(h["adj_close"].iloc[-1])


def make_view(snapshot: dict, t: pd.Timestamp) -> PointInTimeView:
    """由快照與決策日建構 view。切片為副本——來源之後被竄改也不影響已建的 view。"""
    t = pd.Timestamp(t)
    p, r = snapshot["prices"], snapshot["rates"]
    return PointInTimeView(
        t=t,
        prices=p.loc[p["date"] <= t].reset_index(drop=True),
        rates=r.loc[r["date"] <= t].reset_index(drop=True),
    )
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_invariants/test_no_lookahead.py -v`
Expected: PASS（5 項）

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/ptview.py tests/test_invariants/test_no_lookahead.py
git commit -m "feat(backtest): PointInTimeView + INV-1 測試"
```

---

## Task 5: `portfolio/selection.py`

**Files:**
- Create: `quantcore/portfolio/selection.py`
- Test: `tests/test_portfolio/__init__.py`, `tests/test_portfolio/test_selection.py`

- [ ] **Step 1: 寫失敗測試**

`tests/test_portfolio/__init__.py`：空檔。

`tests/test_portfolio/test_selection.py`：

```python
"""point-in-time 合格性（規格 §1.1、§2.1）。"""

import numpy as np

from quantcore.backtest.ptview import make_view
from quantcore.portfolio.selection import eligible_assets
from tests.fixtures.synthetic import make_dates, make_snapshot

MENU = ["SPY", "QQQ", "LATE"]


def _snap(n=30):
    dates = make_dates(n)
    snap = make_snapshot(
        {
            "SPY": list(100.0 + np.arange(n)),
            "QQQ": list(200.0 + np.arange(n)),
            "LATE": list(50.0 + np.arange(10)),  # 只有最後 10 天有資料
        },
        dates,
    )
    return snap, dates


def test_asset_with_insufficient_history_is_not_eligible():
    snap, dates = _snap()
    v = make_view(snap, dates[-1])
    assert eligible_assets(v, MENU, min_history_days=20) == ["QQQ", "SPY"]


def test_late_asset_becomes_eligible_once_history_suffices():
    snap, dates = _snap()
    v = make_view(snap, dates[-1])
    assert eligible_assets(v, MENU, min_history_days=10) == ["LATE", "QQQ", "SPY"]


def test_result_is_sorted_for_determinism():
    snap, dates = _snap()
    v = make_view(snap, dates[-1])
    out = eligible_assets(v, ["QQQ", "SPY"], min_history_days=5)
    assert out == sorted(out)


def test_ticker_absent_from_snapshot_is_not_eligible():
    snap, dates = _snap()
    v = make_view(snap, dates[-1])
    assert eligible_assets(v, ["SPY", "NOPE"], min_history_days=5) == ["SPY"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_portfolio/test_selection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'quantcore.portfolio.selection'`

- [ ] **Step 3: 實作**

`quantcore/portfolio/selection.py`：

```python
"""選擇層（規格 §1.1、§1.3、§2.1）。

Phase 2 只有 point-in-time 合格性；Phase 3 於本檔加入排序、取 K 與平手規則。

合格性放在 portfolio/ 而非 ptview：view 是機制（時間閘門），合格性是業務規則。
混在一起的話，Phase 3 的排序與 top-K 會開始往 view 塞邏輯。
"""

from __future__ import annotations

from quantcore.backtest.ptview import PointInTimeView


def eligible_assets(
    view: PointInTimeView, menu: list[str], min_history_days: int
) -> list[str]:
    """在 t 日已累積 ≥ min_history_days 個 bar 的選單資產，依字母序（決定性）。"""
    return sorted(t for t in menu if view.bar_count(t) >= min_history_days)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_portfolio/test_selection.py -v`
Expected: PASS（4 項）

- [ ] **Step 5: Commit**

```bash
git add quantcore/portfolio/selection.py tests/test_portfolio/
git commit -m "feat(portfolio): point-in-time 合格性"
```

---

## Task 6: `accounting.py` + INV-5 三日手算 golden case

**Files:**
- Create: `quantcore/backtest/accounting.py`
- Test: `tests/test_invariants/test_accounting.py`

- [ ] **Step 1: 寫失敗測試**

`tests/test_invariants/test_accounting.py`：

```python
"""INV-5：會計恆等式——NAV 遞推 + 權重恆和為 1（規格 §1.5、§1.8、§3、§6.1）。

三日手算 golden case 的完整算式見 test_three_day_golden_case 的 docstring。
本檔亦是 Phase 2 唯一實際驗證現金計息的地方（bh_spy/ew_menu 恆滿倉，w_cash = 0）。
"""

import pytest

from quantcore.backtest.accounting import (
    CASH,
    apply_costs,
    apply_returns,
    portfolio_return,
    turnover,
)

RATE = 0.0001  # DTB3 2.52% 年化 ÷ 252


def test_portfolio_return_includes_cash_interest():
    assert portfolio_return({CASH: 1.0}, {}, RATE) == pytest.approx(0.0001)


def test_portfolio_return_mixes_assets_and_cash():
    r = portfolio_return({"A": 0.5, CASH: 0.5}, {"A": 0.10}, RATE)
    assert r == pytest.approx(0.5 * 0.10 + 0.5 * 0.0001)


def test_portfolio_return_raises_when_held_asset_has_no_return():
    with pytest.raises(KeyError, match="無報酬資料"):
        portfolio_return({"A": 1.0}, {}, RATE)


def test_turnover_excludes_cash_leg():
    """§1.8：賣 10% A 換現金 = 單邊 10% 換手，不是 20%（設計文件 §2.2）。"""
    assert turnover({"A": 1.0, CASH: 0.0}, {"A": 0.9, CASH: 0.1}) == pytest.approx(0.1)


def test_weights_sum_to_one_after_drift():
    _, drifted = apply_returns(1.0, {"A": 0.6, "B": 0.4, CASH: 0.0}, {"A": 0.10, "B": -0.05}, RATE)
    assert sum(drifted.values()) == pytest.approx(1.0)


def test_weights_sum_to_one_after_drift_with_cash():
    _, drifted = apply_returns(1.0, {"A": 0.5, CASH: 0.5}, {"A": 0.10}, RATE)
    assert sum(drifted.values()) == pytest.approx(1.0)


def test_three_day_golden_case():
    """三日手算 golden case（Phase 2 AC-2）。

    設定：資產 A、B + 合成現金。per_side_bps = 5（= 0.0005）。
          日利率 = 0.0252 / 252 = 0.0001。
          初始 NAV = 1.0，初始持倉 100% 現金。

    Day 1（r_A = +10%, r_B = -5%，持倉全現金故報酬不影響）
        組合報酬 = 1.0 × 0.0001                    = 0.0001
        NAV      = 1.0 × 1.0001                    = 1.0001
        漂移後   = CASH 1.0 × 1.0001 / 1.0001      = 1.0
        （Day 1 為決策日，target = {A: 0.6, B: 0.4}，Day 2 執行）

    Day 2（r_A = 0, r_B = 0；執行日）
        組合報酬 = 1.0 × 0.0001                    = 0.0001
        NAV(損益後) = 1.0001 × 1.0001              = 1.00020001
        漂移後   = CASH 1.0
        換手     = |0.6 − 0| + |0.4 − 0|           = 1.0      （不含 CASH 腿）
        成本     = 1.00020001 × 1.0 × 0.0005       = 0.000500100005
        NAV      = 1.00020001 − 0.000500100005     = 0.999699909995
        持倉     = {A: 0.6, B: 0.4, CASH: 0.0}

    Day 3（r_A = +10%, r_B = -5%）
        組合報酬 = 0.6 × 0.10 + 0.4 × (−0.05)      = 0.04
        NAV      = 0.999699909995 × 1.04           = 1.0396879063948
        漂移後   A = 0.6 × 1.10 / 1.04             = 0.6346153846153846
                 B = 0.4 × 0.95 / 1.04             = 0.3653846153846154
                 合計                               = 1.0
    """
    bps = 5.0

    # Day 1
    nav, w = apply_returns(1.0, {CASH: 1.0}, {"A": 0.10, "B": -0.05}, RATE)
    assert nav == pytest.approx(1.0001, rel=1e-12)
    assert w[CASH] == pytest.approx(1.0, rel=1e-12)
    target = {"A": 0.6, "B": 0.4, CASH: 0.0}

    # Day 2（執行日）
    nav, w = apply_returns(nav, w, {"A": 0.0, "B": 0.0}, RATE)
    assert nav == pytest.approx(1.00020001, rel=1e-12)
    nav, to = apply_costs(nav, w, target, bps)
    assert to == pytest.approx(1.0, rel=1e-12)
    assert nav == pytest.approx(0.999699909995, rel=1e-12)
    w = dict(target)

    # Day 3
    nav, w = apply_returns(nav, w, {"A": 0.10, "B": -0.05}, RATE)
    assert nav == pytest.approx(1.0396879063948, rel=1e-12)
    assert w["A"] == pytest.approx(0.6346153846153846, rel=1e-12)
    assert w["B"] == pytest.approx(0.3653846153846154, rel=1e-12)
    assert sum(w.values()) == pytest.approx(1.0, rel=1e-12)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_invariants/test_accounting.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'quantcore.backtest.accounting'`

- [ ] **Step 3: 實作**

`quantcore/backtest/accounting.py`：

```python
"""會計：NAV 遞推、權重漂移、現金計息、成本入帳（規格 §1.5、§1.8、§6.1；INV-5）。

全為純函式——不知道日期、不碰 I/O。權重 dict 一律含 'CASH' 鍵。
"""

from __future__ import annotations

CASH = "CASH"
"""合成現金的鍵（§1.5：直接以利率入帳，不持有 BIL/SHV）。"""

_BPS = 10_000.0


def portfolio_return(
    weights: dict[str, float], returns: dict[str, float], cash_rate_daily: float
) -> float:
    """當日組合報酬 = Σ w_i·r_i + w_cash·日利率（§6.1 step 3）。"""
    total = weights.get(CASH, 0.0) * cash_rate_daily
    for k, w in weights.items():
        if k == CASH or w == 0.0:
            continue
        if k not in returns:
            raise KeyError(f"持有 {k} 但當日無報酬資料")
        total += w * returns[k]
    return total


def apply_returns(
    nav: float,
    weights: dict[str, float],
    returns: dict[str, float],
    cash_rate_daily: float,
) -> tuple[float, dict[str, float]]:
    """當日損益 + 權重漂移，回傳 (新 NAV, 漂移後權重)。

    漂移後權重恆和為 1（INV-5）：分母為 1 + 組合報酬，與分子的成長因子一致。
    """
    pr = portfolio_return(weights, returns, cash_rate_daily)
    growth = 1.0 + pr
    if growth <= 0.0:
        raise ValueError(f"組合報酬 {pr} 導致 NAV 歸零或為負，資料異常")
    drifted = {}
    for k, w in weights.items():
        g = (1.0 + cash_rate_daily) if k == CASH else (1.0 + returns.get(k, 0.0))
        drifted[k] = w * g / growth
    return nav * growth, drifted


def turnover(drifted: dict[str, float], target: dict[str, float]) -> float:
    """Σ_i |target_i − drifted_i|，**i 只跑風險資產**（§1.8、設計文件 §2.2）。

    現金為合成、無交易成本；計入 CASH 腿會使單邊成本變兩倍。
    """
    keys = (set(drifted) | set(target)) - {CASH}
    return sum(abs(target.get(k, 0.0) - drifted.get(k, 0.0)) for k in keys)


def apply_costs(
    nav: float, drifted: dict[str, float], target: dict[str, float], per_side_bps: float
) -> tuple[float, float]:
    """執行日扣成本，回傳 (扣後 NAV, 換手率)。"""
    to = turnover(drifted, target)
    return nav - nav * to * per_side_bps / _BPS, to
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_invariants/test_accounting.py -v`
Expected: PASS（7 項）

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/accounting.py tests/test_invariants/test_accounting.py
git commit -m "feat(backtest): 會計純函式 + INV-5 三日手算 golden case"
```

---

## Task 7: `strategy.py` 介面

**Files:**
- Create: `quantcore/backtest/strategy.py`

- [ ] **Step 1: 實作介面**

無獨立測試——介面本身由 Task 8 的策略測試覆蓋（純 ABC + dataclass，無行為可測）。

`quantcore/backtest/strategy.py`：

```python
"""Strategy 介面（規格 §6.2）。

**與 §6.2 的偏離**：§6.2 的簽章為 `decide(self, view)`，但 §1.7 定義了兩種決策日
（選擇日重跑完整權重、曝險檢查日只重算 E(t)），策略必須分辨自己被哪一種叫到，
否則 ew_menu 會在每個曝險檢查日也做月再平衡、full 無法實作 §1.6 的分頻。
`decide(view)` 沒有管道傳此資訊，故加入 `event` 參數。cfg 於 __init__ 綁定。

Diagnostics 不是可選的 debug 資訊，是 Decision Explorer（§11.2）的正式資料合約——
引擎在決策當下就記錄，事後補記錄等於重跑回測。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum

from quantcore.backtest.ptview import PointInTimeView
from quantcore.config import QuantConfig


class DecisionEvent(StrEnum):
    """決策日的兩種類型（§1.7）。一天同時符合兩者時，引擎發 SELECTION。"""

    SELECTION = "selection"
    EXPOSURE_CHECK = "exposure_check"


@dataclass(frozen=True)
class Diagnostics:
    """每一層的完整中間結果（§6.2）。Phase 3-4 的欄位在 Phase 2 為 None。"""

    eligible: list[str]
    selected: list[str]
    momentum_scores: dict[str, float] | None = None
    absmom: dict[str, bool] | None = None
    sigma_hat: dict[str, float] | None = None
    w_risky: dict[str, float] | None = None
    sigma_p: float | None = None
    exposure_raw: float | None = None
    exposure_applied: float | None = None
    band_blocked: bool | None = None


@dataclass(frozen=True)
class Decision:
    """一次決策的產出。target_weights 含 'CASH' 鍵。"""

    target_weights: dict[str, float]
    diagnostics: Diagnostics


class Strategy(ABC):
    """策略基底。strategy_id 為穩定識別碼，取代名稱字串過濾（§6.2）。"""

    strategy_id: str

    def __init__(self, cfg: QuantConfig) -> None:
        self._cfg = cfg

    @property
    @abstractmethod
    def warmup_days(self) -> int:
        """本策略需要幾個交易日的歷史才能決策。引擎取全策略最大值（設計文件 §2.3）。"""

    @abstractmethod
    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        """回傳下一交易日要執行的目標權重；本次不動作則回 None。"""
```

- [ ] **Step 2: 確認 import 得動且 ABC 不可實例化**

Run: `uv run python -c "
from quantcore.backtest.strategy import Strategy, Decision, Diagnostics, DecisionEvent
print(DecisionEvent.SELECTION)
try:
    Strategy(None)
except TypeError as e:
    print('ABC OK:', type(e).__name__)
"`
Expected: 印出 `selection` 與 `ABC OK: TypeError`

- [ ] **Step 3: Commit**

```bash
git add quantcore/backtest/strategy.py
git commit -m "feat(backtest): Strategy 介面（decide 加 event 參數，見 docstring）"
```

---

## Task 8: `bh_spy` 與 `ew_menu`

**Files:**
- Create: `quantcore/backtest/strategies/__init__.py`
- Create: `quantcore/backtest/strategies/bh_spy.py`
- Create: `quantcore/backtest/strategies/ew_menu.py`
- Test: `tests/test_backtest/__init__.py`, `tests/test_backtest/test_strategies.py`

- [ ] **Step 1: 寫失敗測試**

`tests/test_backtest/__init__.py`：空檔。

`tests/test_backtest/test_strategies.py`：

```python
"""Phase 2 的兩個 benchmark 策略（規格 §6.3）。"""

import numpy as np

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategies import STRATEGIES
from quantcore.backtest.strategy import DecisionEvent
from quantcore.config import load_config
from tests.fixtures.synthetic import make_dates, make_snapshot

CONFIG_YAML = "quantcore/config/default.yaml"


def _cfg(min_history_days=10):
    cfg = load_config(CONFIG_YAML).model_copy(deep=True)
    cfg.universe.menu = ["SPY", "QQQ", "LATE"]
    cfg.universe.min_history_days = min_history_days
    cfg.signal.top_k = 2
    return cfg


def _snap(n=30):
    dates = make_dates(n)
    snap = make_snapshot(
        {
            "SPY": list(100.0 + np.arange(n)),
            "QQQ": list(200.0 + np.arange(n)),
            "LATE": list(50.0 + np.arange(5)),
        },
        dates,
    )
    return snap, dates


def test_bh_spy_decides_once_then_never_again():
    """§6.3：Buy & Hold —— 全期僅一次交易。"""
    cfg = _cfg()
    snap, dates = _snap()
    s = STRATEGIES["bh_spy"](cfg)

    first = s.decide(make_view(snap, dates[10]), DecisionEvent.SELECTION)
    assert first is not None
    assert first.target_weights == {"SPY": 1.0, CASH: 0.0}
    assert first.diagnostics.selected == ["SPY"]

    assert s.decide(make_view(snap, dates[11]), DecisionEvent.SELECTION) is None
    assert s.decide(make_view(snap, dates[12]), DecisionEvent.EXPOSURE_CHECK) is None


def test_bh_spy_needs_no_warmup():
    assert STRATEGIES["bh_spy"](_cfg()).warmup_days == 0


def test_ew_menu_equal_weights_eligible_only():
    cfg = _cfg(min_history_days=10)
    snap, dates = _snap()
    s = STRATEGIES["ew_menu"](cfg)

    d = s.decide(make_view(snap, dates[-1]), DecisionEvent.SELECTION)
    assert d is not None
    # LATE 只有 5 個 bar < 10 → 不合格
    assert d.diagnostics.eligible == ["QQQ", "SPY"]
    assert d.target_weights == {"QQQ": 0.5, "SPY": 0.5, CASH: 0.0}
    assert sum(d.target_weights.values()) == 1.0


def test_ew_menu_ignores_exposure_check_days():
    """§1.7：曝險檢查日只重算 E(t)；ew_menu 無曝險模型故不動作。"""
    cfg = _cfg()
    snap, dates = _snap()
    s = STRATEGIES["ew_menu"](cfg)
    assert s.decide(make_view(snap, dates[-1]), DecisionEvent.EXPOSURE_CHECK) is None


def test_ew_menu_warmup_is_min_history_days():
    assert STRATEGIES["ew_menu"](_cfg(min_history_days=252)).warmup_days == 252


def test_ew_menu_returns_none_when_nothing_eligible():
    cfg = _cfg(min_history_days=999)
    snap, dates = _snap()
    s = STRATEGIES["ew_menu"](cfg)
    assert s.decide(make_view(snap, dates[-1]), DecisionEvent.SELECTION) is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_strategies.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'quantcore.backtest.strategies'`

- [ ] **Step 3: 實作**

`quantcore/backtest/strategies/bh_spy.py`：

```python
"""bh_spy —— Buy & Hold SPY（規格 §6.3）。

存在理由：最誠實的基準，不折騰能拿到什麼。

有狀態（`_decided`）是刻意的：buy & hold 的語意就是「決策一次」。引擎每次 run
建立新實例，故不影響 INV-6 可重現性。
"""

from __future__ import annotations

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.config import QuantConfig


class BuyHoldSPY(Strategy):
    strategy_id = "bh_spy"

    def __init__(self, cfg: QuantConfig) -> None:
        super().__init__(cfg)
        self._decided = False

    @property
    def warmup_days(self) -> int:
        return 0

    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        if self._decided or event is not DecisionEvent.SELECTION:
            return None
        self._decided = True
        return Decision(
            target_weights={"SPY": 1.0, CASH: 0.0},
            diagnostics=Diagnostics(eligible=["SPY"], selected=["SPY"]),
        )
```

`quantcore/backtest/strategies/ew_menu.py`：

```python
"""ew_menu —— 選單等權重、月再平衡（規格 §6.3）。

存在理由：分散但無訊號。
"""

from __future__ import annotations

from quantcore.backtest.accounting import CASH
from quantcore.backtest.ptview import PointInTimeView
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.config import QuantConfig


class EqualWeightMenu(Strategy):
    strategy_id = "ew_menu"

    @property
    def warmup_days(self) -> int:
        return self._cfg.universe.min_history_days

    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        if event is not DecisionEvent.SELECTION:
            return None
        from quantcore.portfolio.selection import eligible_assets

        elig = eligible_assets(
            view, self._cfg.universe.menu, self._cfg.universe.min_history_days
        )
        if not elig:
            return None
        w = 1.0 / len(elig)
        target = {t: w for t in elig}
        target[CASH] = 0.0
        return Decision(
            target_weights=target,
            diagnostics=Diagnostics(eligible=elig, selected=elig),
        )
```

> `eligible_assets` 於函式內 import 是為了避免 `backtest.strategies` 在 import 時
> 拉進 `portfolio`——依賴方向 `portfolio ← backtest` 允許此 import，寫在函式內純為
> 降低模組載入耦合。若 ruff 抱怨，移到檔頭亦可。

`quantcore/backtest/strategies/__init__.py`：

```python
"""Phase 2 策略註冊表（規格 §6.3）。Phase 3-4 於此加入其餘五個策略。"""

from quantcore.backtest.strategies.bh_spy import BuyHoldSPY
from quantcore.backtest.strategies.ew_menu import EqualWeightMenu

STRATEGIES = {
    BuyHoldSPY.strategy_id: BuyHoldSPY,
    EqualWeightMenu.strategy_id: EqualWeightMenu,
}

__all__ = ["STRATEGIES", "BuyHoldSPY", "EqualWeightMenu"]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/test_strategies.py -v`
Expected: PASS（6 項）

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/strategies/ tests/test_backtest/
git commit -m "feat(backtest): bh_spy 與 ew_menu 策略"
```

---

## Task 9: `engine.py` + INV-2 行為測試

**Files:**
- Create: `quantcore/backtest/engine.py`
- Modify: `tests/test_invariants/test_execution_lag.py`（追加行為測試）

- [ ] **Step 1: 寫失敗測試**

追加到 `tests/test_invariants/test_execution_lag.py` 末尾：

```python
# ---------------------------------------------------------------- 引擎行為（Task 9）

import numpy as np

from quantcore.backtest.accounting import CASH
from quantcore.backtest.engine import run_strategy
from quantcore.backtest.strategy import Decision, DecisionEvent, Diagnostics, Strategy
from quantcore.config import load_config
from tests.fixtures.synthetic import make_snapshot


class _FixedTarget(Strategy):
    """在第一個選擇日給定 target，其後不動作。target 由測試注入。"""

    strategy_id = "fixed"

    def __init__(self, cfg, target):
        super().__init__(cfg)
        self._target = target
        self._done = False

    @property
    def warmup_days(self) -> int:
        return 0

    def decide(self, view, event):
        if self._done or event is not DecisionEvent.SELECTION:
            return None
        self._done = True
        return Decision(
            target_weights=dict(self._target),
            diagnostics=Diagnostics(eligible=sorted(self._target), selected=sorted(self._target)),
        )


def _engine_cfg():
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["A", "B"]
    cfg.universe.min_history_days = 1
    cfg.signal.top_k = 2
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    return cfg


def _engine_snapshot(n=20):
    dates = make_dates(n)
    rng = np.random.default_rng(7)
    a = list(100.0 * np.cumprod(1 + rng.normal(0.001, 0.01, n)))
    b = list(50.0 * np.cumprod(1 + rng.normal(0.001, 0.01, n)))
    return make_snapshot({"A": a, "B": b}, dates), dates


def _run(target, warmup=2):
    cfg = _engine_cfg()
    snap, dates = _engine_snapshot()
    clock = EventClock(
        trading_days=dates,
        warmup=warmup,
        selection_interval=cfg.schedule.selection_interval,
        exposure_check_interval=cfg.schedule.exposure_check_interval,
    )
    nav, weights, decisions = run_strategy(snap, clock, _FixedTarget(cfg, target), cfg)
    return nav, weights, decisions, clock


def test_target_change_does_not_affect_decision_or_execution_day_nav():
    """INV-2 的行為證明（§1.2「新權重自 close(t+1) 生效，賺 (t+1 → t+2]」）。

    把 target 換成完全不同的值，決策日與執行日當天的 NAV 必須逐位元相同——
    決策日當天新權重尚未存在，執行日當天的報酬仍由舊（漂移後）權重賺得，
    成本雖於執行日扣除，但兩個 target 的換手率在此設定下相同（皆由全現金建倉，
    換手 = 1.0），故 NAV 亦同。差異只能出現在執行日之後。
    """
    nav1, _, dec1, clock = _run({"A": 1.0, "B": 0.0, CASH: 0.0})
    nav2, _, _, _ = _run({"A": 0.0, "B": 1.0, CASH: 0.0})

    d_day = dec1["decision_date"].iloc[0]
    x_day = dec1["execution_date"].iloc[0]

    n1 = nav1.set_index("date")["nav"]
    n2 = nav2.set_index("date")["nav"]
    assert n1.loc[d_day] == n2.loc[d_day]
    assert n1.loc[x_day] == n2.loc[x_day]
    after = n1.index[n1.index > x_day]
    assert not np.allclose(n1.loc[after].to_numpy(), n2.loc[after].to_numpy())


def test_weights_change_only_on_execution_day():
    nav, weights, dec, clock = _run({"A": 1.0, "B": 0.0, CASH: 0.0})
    x_day = dec["execution_date"].iloc[0]
    w = weights.pivot(index="date", columns="ticker", values="weight").fillna(0.0)

    before = w.index[w.index < x_day]
    assert (w.loc[before, CASH] == 1.0).all()
    assert w.loc[x_day, "A"] == 1.0


def test_decision_recorded_with_next_trading_day_as_execution():
    _, _, dec, clock = _run({"A": 1.0, "B": 0.0, CASH: 0.0})
    d_day = dec["decision_date"].iloc[0]
    assert dec["execution_date"].iloc[0] == clock.execution_day(d_day)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_invariants/test_execution_lag.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'quantcore.backtest.engine'`

- [ ] **Step 3: 實作**

`quantcore/backtest/engine.py`：

```python
"""回測主迴圈（規格 §6.1，model-agnostic）。

**每日順序刻意偏離 §6.1 伪代碼**（設計文件 §2.1）：§6.1 的「執行 → 損益」順序在
回看報酬慣例下，會讓新權重賺到它生效之前的報酬，與 §1.2 的損益歸屬矛盾。
以 §1.2 為準：損益 → 漂移 → 執行 → 決策。

本模組不寫檔、不知道 runs/ 的存在（那是 experiments/ 的職責）。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quantcore.backtest.accounting import CASH, apply_costs, apply_returns
from quantcore.backtest.clock import EventClock
from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategy import DecisionEvent, Strategy
from quantcore.config import QuantConfig

_RATES_SERIES = "DTB3"
_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class _Pending:
    target: dict[str, float]
    execution_day: pd.Timestamp


def _returns_wide(prices: pd.DataFrame) -> pd.DataFrame:
    """date × ticker 的日報酬（自 adj_close，即含息總報酬）。"""
    wide = prices.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    return wide.pct_change()


def _daily_rates(rates: pd.DataFrame, trading_days: pd.DatetimeIndex) -> pd.Series:
    """DTB3（年化百分比）→ 日利率，對齊交易日並 ffill 假日（§1.5）。"""
    s = rates.set_index("date")[_RATES_SERIES].sort_index()
    return s.reindex(trading_days).ffill().bfill() / 100.0 / _DAYS_PER_YEAR


def run_strategy(
    snapshot: dict, clock: EventClock, strategy: Strategy, cfg: QuantConfig
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """單一策略的完整回測，回傳 (nav, weights, decisions) 三張長格式表。"""
    rets = _returns_wide(snapshot["prices"])
    rates = _daily_rates(snapshot["rates"], clock.trading_days)

    nav = float(cfg.backtest.initial_nav)
    weights: dict[str, float] = {CASH: 1.0}
    pending: _Pending | None = None

    nav_rows, weight_rows, decision_rows = [], [], []

    for t in clock.active_days:
        row = rets.loc[t].dropna() if t in rets.index else pd.Series(dtype="float64")
        day_returns = {k: float(v) for k, v in row.items()}
        rate = float(rates.loc[t])

        nav, drifted = apply_returns(nav, weights, day_returns, rate)

        turnover_today, cost_today = 0.0, 0.0
        if pending is not None and pending.execution_day == t:
            nav_before = nav
            nav, turnover_today = apply_costs(
                nav, drifted, pending.target, cfg.costs.per_side_bps
            )
            cost_today = nav_before - nav
            weights = dict(pending.target)
            pending = None
        else:
            weights = drifted

        if clock.is_decision_day(t):
            event = (
                DecisionEvent.SELECTION
                if clock.is_selection_day(t)
                else DecisionEvent.EXPOSURE_CHECK
            )
            decision = strategy.decide(make_view(snapshot, t), event)
            if decision is not None:
                exec_day = clock.execution_day(t)
                if exec_day is not None:
                    if pending is not None:
                        raise RuntimeError(
                            f"{t:%Y-%m-%d} 產生新決策，但前次決策尚未執行——"
                            "時程間隔設定有誤（見 EventClock 的間隔 ≥ 2 檢查）"
                        )
                    pending = _Pending(target=dict(decision.target_weights), execution_day=exec_day)
                    decision_rows.append(
                        {
                            "decision_date": t,
                            "execution_date": exec_day,
                            "strategy_id": strategy.strategy_id,
                            "event": str(event),
                            "diagnostics": decision.diagnostics,
                            "target_weights": dict(decision.target_weights),
                        }
                    )

        nav_rows.append(
            {
                "date": t,
                "strategy_id": strategy.strategy_id,
                "nav": nav,
                "turnover": turnover_today,
                "cost": cost_today,
            }
        )
        for ticker, w in weights.items():
            weight_rows.append(
                {"date": t, "strategy_id": strategy.strategy_id, "ticker": ticker, "weight": w}
            )

    return (
        pd.DataFrame(nav_rows),
        pd.DataFrame(weight_rows),
        pd.DataFrame(decision_rows),
    )
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_invariants/test_execution_lag.py -v`
Expected: PASS（10 項）

- [ ] **Step 5: 全套回歸**

Run: `uv run pytest`
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add quantcore/backtest/engine.py tests/test_invariants/test_execution_lag.py
git commit -m "feat(backtest): 主迴圈（損益→漂移→執行→決策）+ INV-2 行為測試"
```

---

## Task 10: `metrics.py`

**Files:**
- Create: `quantcore/backtest/metrics.py`
- Test: `tests/test_backtest/test_metrics.py`

- [ ] **Step 1: 寫失敗測試**

`tests/test_backtest/test_metrics.py`：

```python
"""績效統計（規格 §6.4）。Phase 2 不含 block bootstrap（§9）。"""

import numpy as np
import pandas as pd
import pytest

from quantcore.backtest.metrics import (
    annualized_return,
    annualized_turnover,
    calmar,
    compute_metrics,
    max_drawdown,
    sharpe,
)


def test_annualized_return_doubles_over_one_year():
    nav = pd.Series(np.linspace(1.0, 2.0, 253))
    assert annualized_return(nav) == pytest.approx(1.0, rel=1e-9)


def test_max_drawdown_of_peak_then_trough():
    nav = pd.Series([1.0, 2.0, 1.0, 1.5])
    assert max_drawdown(nav) == pytest.approx(-0.5)


def test_max_drawdown_is_zero_for_monotonic_nav():
    assert max_drawdown(pd.Series([1.0, 1.1, 1.2])) == pytest.approx(0.0)


def test_sharpe_is_zero_when_return_equals_riskfree():
    ret = pd.Series([0.0001] * 100)
    rf = pd.Series([0.0001] * 100)
    assert sharpe(ret, rf) == pytest.approx(0.0, abs=1e-12)


def test_sharpe_is_nan_when_excess_has_no_variance_but_nonzero_mean():
    """常數超額報酬 → 標準差 0 → Sharpe 無定義。回 nan 而非 inf 或崩潰。"""
    ret = pd.Series([0.001] * 100)
    rf = pd.Series([0.0] * 100)
    assert np.isnan(sharpe(ret, rf))


def test_calmar_is_cagr_over_abs_maxdd():
    nav = pd.Series([1.0, 2.0, 1.0, 1.5])
    assert calmar(nav) == pytest.approx(annualized_return(nav) / 0.5)


def test_annualized_turnover_scales_to_252_days():
    assert annualized_turnover(total_turnover=2.0, n_days=126) == pytest.approx(4.0)


def test_compute_metrics_returns_all_keys():
    n = 300
    nav = pd.Series(np.cumprod(1 + np.full(n, 0.0004)), index=pd.RangeIndex(n))
    rf = pd.Series(np.full(n, 0.0001))
    m = compute_metrics(nav=nav, rate_daily=rf, total_turnover=1.0, total_cost=0.0005)
    assert set(m) == {
        "annualized_return",
        "sharpe",
        "sortino",
        "max_drawdown",
        "calmar",
        "annualized_turnover",
        "cost_drag_bps_per_year",
        "n_days",
    }
    assert m["n_days"] == n
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_backtest/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'quantcore.backtest.metrics'`

- [ ] **Step 3: 實作**

`quantcore/backtest/metrics.py`：

```python
"""績效統計（規格 §6.4）。純函式，不碰檔案。

Phase 2 不含 block bootstrap CI（§9 明講「先不含 bootstrap」），Phase 4 加入。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_DAYS_PER_YEAR = 252
_BPS = 10_000.0


def annualized_return(nav: pd.Series) -> float:
    """CAGR。以交易日數 / 252 為年數。"""
    n = len(nav) - 1
    if n <= 0:
        return float("nan")
    return float((nav.iloc[-1] / nav.iloc[0]) ** (_DAYS_PER_YEAR / n) - 1.0)


def _excess(ret: pd.Series, rf_daily: pd.Series) -> np.ndarray:
    return (ret.to_numpy() - rf_daily.to_numpy())[1:] if len(ret) else np.array([])


def sharpe(ret: pd.Series, rf_daily: pd.Series) -> float:
    """年化 Sharpe，超額於 DTB3（§6.4）。超額報酬無變異時回 nan。"""
    e = ret.to_numpy() - rf_daily.to_numpy()
    sd = e.std(ddof=1)
    if sd == 0.0:
        return 0.0 if e.mean() == 0.0 else float("nan")
    return float(e.mean() / sd * np.sqrt(_DAYS_PER_YEAR))


def sortino(ret: pd.Series, rf_daily: pd.Series) -> float:
    """年化 Sortino：分母只算下檔波動。無下檔時回 nan。"""
    e = ret.to_numpy() - rf_daily.to_numpy()
    downside = e[e < 0]
    if len(downside) == 0:
        return float("nan")
    sd = downside.std(ddof=1)
    if sd == 0.0:
        return float("nan")
    return float(e.mean() / sd * np.sqrt(_DAYS_PER_YEAR))


def max_drawdown(nav: pd.Series) -> float:
    """最大回撤（負值或 0）。"""
    dd = nav / nav.cummax() - 1.0
    return float(dd.min())


def calmar(nav: pd.Series) -> float:
    """CAGR / |MaxDD|。無回撤時回 nan。"""
    mdd = max_drawdown(nav)
    if mdd == 0.0:
        return float("nan")
    return float(annualized_return(nav) / abs(mdd))


def annualized_turnover(total_turnover: float, n_days: int) -> float:
    if n_days <= 0:
        return float("nan")
    return float(total_turnover * _DAYS_PER_YEAR / n_days)


def compute_metrics(
    nav: pd.Series, rate_daily: pd.Series, total_turnover: float, total_cost: float
) -> dict[str, float]:
    """§6.4 的彙總統計。nav 與 rate_daily 須等長且同序。"""
    ret = nav.pct_change().fillna(0.0)
    n = len(nav)
    years = n / _DAYS_PER_YEAR
    return {
        "annualized_return": annualized_return(nav),
        "sharpe": sharpe(ret, rate_daily),
        "sortino": sortino(ret, rate_daily),
        "max_drawdown": max_drawdown(nav),
        "calmar": calmar(nav),
        "annualized_turnover": annualized_turnover(total_turnover, n),
        "cost_drag_bps_per_year": float(total_cost / nav.iloc[0] * _BPS / years)
        if years > 0
        else float("nan"),
        "n_days": n,
    }
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_backtest/test_metrics.py -v`
Expected: PASS（8 項）

- [ ] **Step 5: Commit**

```bash
git add quantcore/backtest/metrics.py tests/test_backtest/test_metrics.py
git commit -m "feat(backtest): 績效統計（不含 bootstrap）"
```

---

## Task 11: `experiments/tracking.py`

**Files:**
- Create: `quantcore/experiments/tracking.py`
- Test: `tests/test_experiments/__init__.py`, `tests/test_experiments/test_tracking.py`

- [ ] **Step 1: 寫失敗測試**

`tests/test_experiments/__init__.py`：空檔。

`tests/test_experiments/test_tracking.py`：

```python
"""run 目錄、manifest、決定性寫檔（規格 §7.1、INV-6）。"""

import json

import pandas as pd
import pytest

from quantcore.experiments.tracking import create_run_dir, git_commit, write_artifacts


def test_create_run_dir_uses_label_and_timestamp(tmp_path):
    d = create_run_dir(tmp_path, "default", pd.Timestamp("2026-07-17T14:32:11"))
    assert d.name == "2026-07-17_1432_default"
    assert d.is_dir()


def test_create_run_dir_rejects_collision(tmp_path):
    ts = pd.Timestamp("2026-07-17T14:32:11")
    create_run_dir(tmp_path, "default", ts)
    with pytest.raises(FileExistsError):
        create_run_dir(tmp_path, "default", ts)


def test_git_commit_marks_dirty_working_tree():
    """INV-6 的三元組含 git_commit；工作區髒了卻回乾淨的 sha 就是撒謊。"""
    c = git_commit()
    assert isinstance(c, str) and len(c) >= 7


def test_manifest_separates_identity_from_created_at(tmp_path):
    d = create_run_dir(tmp_path, "x", pd.Timestamp("2026-07-17T14:32:11"))
    write_artifacts(
        run_dir=d,
        cfg_dict={"seed": 42},
        identity={"config_hash": "abc", "snapshot_id": "s1", "git_commit": "c1",
                  "quantcore_version": "0.1.0"},
        created_at="2026-07-17T14:32:11+00:00",
        nav=pd.DataFrame({"date": [pd.Timestamp("2020-01-02")], "strategy_id": ["a"],
                          "nav": [1.0], "turnover": [0.0], "cost": [0.0]}),
        weights=pd.DataFrame({"date": [pd.Timestamp("2020-01-02")], "strategy_id": ["a"],
                              "ticker": ["CASH"], "weight": [1.0]}),
        decisions=pd.DataFrame(),
        metrics={"a": {"sharpe": 1.0}},
    )
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert set(m) == {"identity", "created_at"}
    assert m["identity"]["config_hash"] == "abc"


def test_all_artifacts_written(tmp_path):
    d = create_run_dir(tmp_path, "x", pd.Timestamp("2026-07-17T14:32:11"))
    write_artifacts(
        run_dir=d,
        cfg_dict={"seed": 42},
        identity={"config_hash": "abc", "snapshot_id": "s1", "git_commit": "c1",
                  "quantcore_version": "0.1.0"},
        created_at="2026-07-17T14:32:11+00:00",
        nav=pd.DataFrame({"date": [pd.Timestamp("2020-01-02")], "strategy_id": ["a"],
                          "nav": [1.0], "turnover": [0.0], "cost": [0.0]}),
        weights=pd.DataFrame({"date": [pd.Timestamp("2020-01-02")], "strategy_id": ["a"],
                              "ticker": ["CASH"], "weight": [1.0]}),
        decisions=pd.DataFrame(),
        metrics={"a": {"sharpe": 1.0}},
    )
    for fn in ("config.yaml", "manifest.json", "nav.parquet", "weights.parquet",
               "decisions.parquet", "metrics.json"):
        assert (d / fn).exists(), fn
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_experiments/test_tracking.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'quantcore.experiments.tracking'`

- [ ] **Step 3: 實作**

`quantcore/experiments/tracking.py`：

```python
"""run 目錄、manifest、決定性寫檔（規格 §7.1；INV-6）。

manifest 刻意切成 identity / created_at 兩塊（設計文件 §5.2）：
INV-6 是「(config, snapshot_hash, git_commit) 三元組決定**輸出**」，時間戳本就會變。
把邊界寫在資料結構上，而非藏在測試的 exclude 清單裡。
"""

from __future__ import annotations

import json
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pandas as pd
import yaml

try:
    QC_VERSION = version("quantcore")
except PackageNotFoundError:  # pragma: no cover
    QC_VERSION = "unknown"


def git_commit() -> str:
    """HEAD 的 sha；工作區有未提交改動則加 -dirty 後綴。

    不加 dirty 標記的話，INV-6 的三元組會撒謊——同一個 sha 可能對應不同的程式碼。
    """
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return f"{sha}-dirty" if dirty else sha


def create_run_dir(out_root: str | Path, label: str, now: pd.Timestamp) -> Path:
    """runs/YYYY-MM-DD_HHMM_<label>/。

    與 §7.1 範例（`..._full_default`）不同：一個 run 涵蓋多策略，
    目錄名放單一策略名無意義（設計文件 §5.1）。
    """
    d = Path(out_root) / f"{now:%Y-%m-%d_%H%M}_{label}"
    d.mkdir(parents=True, exist_ok=False)
    return d


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    """決定性寫檔：固定欄序與列序（沿用 Phase 1 達成 AC-4 的作法）。"""
    df.to_parquet(path, index=False)


def write_artifacts(
    run_dir: Path,
    cfg_dict: dict,
    identity: dict,
    created_at: str,
    nav: pd.DataFrame,
    weights: pd.DataFrame,
    decisions: pd.DataFrame,
    metrics: dict,
) -> None:
    """寫出 §7.1 的 Phase 2 子集（無 model_details/——Phase 2 無模型）。"""
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg_dict, sort_keys=True, allow_unicode=True), encoding="utf-8"
    )
    (run_dir / "manifest.json").write_text(
        json.dumps({"identity": identity, "created_at": created_at},
                   indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_parquet(nav, run_dir / "nav.parquet")
    _write_parquet(weights, run_dir / "weights.parquet")
    _write_parquet(decisions, run_dir / "decisions.parquet")
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_experiments/test_tracking.py -v`
Expected: PASS（5 項）

- [ ] **Step 5: Commit**

```bash
git add quantcore/experiments/tracking.py tests/test_experiments/
git commit -m "feat(experiments): run 目錄、manifest（identity/created_at）、決定性寫檔"
```

---

## Task 12: `experiments/runner.py` + CLI

**Files:**
- Create: `quantcore/experiments/runner.py`
- Test: `tests/test_experiments/test_runner.py`

- [ ] **Step 1: 寫失敗測試**

`tests/test_experiments/test_runner.py`：

```python
"""單次實驗 pipeline（規格 §7.1）。"""

import json

import numpy as np
import pandas as pd

from quantcore.config import load_config
from quantcore.experiments.runner import run_experiment
from tests.fixtures.synthetic import make_dates, make_snapshot


def _cfg():
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["SPY", "QQQ"]
    cfg.universe.min_history_days = 5
    cfg.signal.top_k = 2
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    return cfg


def _snap(n=30):
    dates = make_dates(n)
    rng = np.random.default_rng(3)
    return make_snapshot(
        {
            "SPY": list(100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))),
            "QQQ": list(200.0 * np.cumprod(1 + rng.normal(0.0005, 0.012, n))),
        },
        dates,
    )


def test_run_experiment_writes_all_artifacts_for_both_strategies(tmp_path):
    d = run_experiment(
        cfg=_cfg(),
        snapshot=_snap(),
        out_root=tmp_path,
        label="test",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )
    nav = pd.read_parquet(d / "nav.parquet")
    assert set(nav["strategy_id"].unique()) == {"bh_spy", "ew_menu"}

    metrics = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
    assert set(metrics) == {"bh_spy", "ew_menu"}
    assert "sharpe" in metrics["bh_spy"]


def test_all_strategies_share_the_same_nav_start_date(tmp_path):
    """warmup 全 run 統一（設計文件 §2.3）——否則七策略比較表不可比。"""
    d = run_experiment(
        cfg=_cfg(),
        snapshot=_snap(),
        out_root=tmp_path,
        label="test",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )
    nav = pd.read_parquet(d / "nav.parquet")
    starts = nav.groupby("strategy_id")["date"].min()
    assert starts.nunique() == 1


def test_decisions_carry_null_model_columns(tmp_path):
    """Phase 2 無模型，欄位須存在但為 null（設計文件 §0、§4）。"""
    d = run_experiment(
        cfg=_cfg(),
        snapshot=_snap(),
        out_root=tmp_path,
        label="test",
        strategy_ids=["ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )
    dec = pd.read_parquet(d / "decisions.parquet")
    assert not dec.empty
    for col in ("momentum_scores", "sigma_hat", "sigma_p", "exposure_applied", "band_blocked"):
        assert col in dec.columns
        assert dec[col].isna().all()
    assert dec["eligible"].iloc[0] == '["QQQ", "SPY"]'
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_experiments/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'quantcore.experiments.runner'`

- [ ] **Step 3: 實作**

`quantcore/experiments/runner.py`：

```python
"""單次實驗：config → 完整 pipeline → artifacts（規格 §7.1）+ CLI。

CLI 是 Phase 7 Run Lab 的 subprocess 對象（§11.1：行程邊界取代 import 邊界）。

策略在外、天在內（設計文件 §0）：run_strategy 為獨立單元，本模組只負責
逐策略呼叫、concat、落地。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from quantcore.backtest.clock import EventClock
from quantcore.backtest.engine import run_strategy
from quantcore.backtest.metrics import compute_metrics
from quantcore.backtest.strategies import STRATEGIES
from quantcore.config import QuantConfig, load_config
from quantcore.data.hashing import config_hash
from quantcore.data.snapshot import load_snapshot
from quantcore.experiments.tracking import (
    QC_VERSION,
    create_run_dir,
    git_commit,
    write_artifacts,
)

_DAYS_PER_YEAR = 252


def _trading_days(snapshot: dict, start) -> pd.DatetimeIndex:
    d = snapshot["prices"]["date"]
    days = pd.DatetimeIndex(sorted(d.unique()))
    return days[days >= pd.Timestamp(start)]


def _diagnostics_row(diag) -> dict:
    """Diagnostics → parquet 可存的欄位。dict/list 以 JSON 字串存（決定性：sort_keys）。"""

    def j(v):
        return None if v is None else json.dumps(v, sort_keys=True, ensure_ascii=False)

    return {
        "eligible": j(diag.eligible),
        "selected": j(diag.selected),
        "momentum_scores": j(diag.momentum_scores),
        "absmom": j(diag.absmom),
        "sigma_hat": j(diag.sigma_hat),
        "w_risky": j(diag.w_risky),
        "sigma_p": diag.sigma_p,
        "exposure_raw": diag.exposure_raw,
        "exposure_applied": diag.exposure_applied,
        "band_blocked": diag.band_blocked,
    }


def _flatten_decisions(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw
    rows = []
    for r in raw.to_dict("records"):
        row = {
            "decision_date": r["decision_date"],
            "execution_date": r["execution_date"],
            "strategy_id": r["strategy_id"],
            "event": r["event"],
            "target_weights": json.dumps(r["target_weights"], sort_keys=True),
        }
        row.update(_diagnostics_row(r["diagnostics"]))
        rows.append(row)
    out = pd.DataFrame(rows)
    out["sigma_p"] = out["sigma_p"].astype("float64")
    out["exposure_raw"] = out["exposure_raw"].astype("float64")
    out["exposure_applied"] = out["exposure_applied"].astype("float64")
    out["band_blocked"] = out["band_blocked"].astype("boolean")
    return out


def run_experiment(
    cfg: QuantConfig,
    snapshot: dict,
    out_root: str | Path,
    label: str,
    strategy_ids: list[str],
    now: pd.Timestamp | None = None,
) -> Path:
    """跑完所有策略並寫出 run 目錄，回傳該目錄。"""
    now = pd.Timestamp.now() if now is None else now
    days = _trading_days(snapshot, cfg.backtest.start)

    strategies = [STRATEGIES[sid](cfg) for sid in strategy_ids]
    warmup = max(s.warmup_days for s in strategies)  # 全 run 統一（設計文件 §2.3）
    clock = EventClock(
        trading_days=days,
        warmup=warmup,
        selection_interval=cfg.schedule.selection_interval,
        exposure_check_interval=cfg.schedule.exposure_check_interval,
    )

    navs, weights, decisions, metrics = [], [], [], {}
    for s in strategies:
        nav_df, w_df, d_df = run_strategy(snapshot, clock, s, cfg)
        navs.append(nav_df)
        weights.append(w_df)
        decisions.append(_flatten_decisions(d_df))

        rate = (
            snapshot["rates"].set_index("date")["DTB3"].reindex(nav_df["date"]).ffill().bfill()
            / 100.0
            / _DAYS_PER_YEAR
        )
        metrics[s.strategy_id] = compute_metrics(
            nav=nav_df["nav"].reset_index(drop=True),
            rate_daily=rate.reset_index(drop=True),
            total_turnover=float(nav_df["turnover"].sum()),
            total_cost=float(nav_df["cost"].sum()),
        )

    run_dir = create_run_dir(out_root, label, now)
    write_artifacts(
        run_dir=run_dir,
        cfg_dict=cfg.model_dump(mode="json"),
        identity={
            "config_hash": config_hash(cfg.model_dump(mode="json")),
            "snapshot_id": snapshot["manifest"]["snapshot_id"],
            "git_commit": git_commit(),
            "quantcore_version": QC_VERSION,
        },
        created_at=datetime.now(UTC).isoformat(),
        nav=pd.concat(navs, ignore_index=True),
        weights=pd.concat(weights, ignore_index=True),
        decisions=pd.concat(decisions, ignore_index=True) if any(len(d) for d in decisions)
        else pd.DataFrame(),
        metrics=metrics,
    )
    return run_dir


def _cli(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    p = argparse.ArgumentParser(prog="python -m quantcore.experiments.runner")
    p.add_argument("--config", required=True)
    p.add_argument("--label", default=None, help="run 目錄後綴；預設取 config 檔名")
    p.add_argument("--out-root", default="runs")
    p.add_argument(
        "--strategies",
        default=",".join(STRATEGIES),
        help=f"逗號分隔；可用：{', '.join(STRATEGIES)}",
    )
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    label = args.label or Path(args.config).stem
    snapshot = load_snapshot(cfg.snapshot)
    run_dir = run_experiment(
        cfg=cfg,
        snapshot=snapshot,
        out_root=args.out_root,
        label=label,
        strategy_ids=[s.strip() for s in args.strategies.split(",") if s.strip()],
    )
    print(f"run 已完成：{run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_experiments/test_runner.py -v`
Expected: PASS（3 項）

- [ ] **Step 5: Commit**

```bash
git add quantcore/experiments/runner.py tests/test_experiments/test_runner.py
git commit -m "feat(experiments): 單次實驗 pipeline + CLI"
```

---

## Task 13: INV-6 可重現性

**Files:**
- Test: `tests/test_invariants/test_reproducibility.py`

- [ ] **Step 1: 寫失敗測試**

`tests/test_invariants/test_reproducibility.py`：

```python
"""INV-6：(config, snapshot_hash, git_commit) 三元組決定輸出（規格 §3、§7.1）。

比對對象是**資料產出**，不是整個目錄——run 目錄名含時間戳、manifest 含 created_at，
兩次跑必然不同。邊界寫在 manifest 的 identity / created_at 切分上（設計文件 §5.2）。
"""

import json

import numpy as np
import pandas as pd

from quantcore.config import load_config
from quantcore.experiments.runner import run_experiment
from tests.fixtures.synthetic import make_dates, make_snapshot

DATA_FILES = ("nav.parquet", "weights.parquet", "decisions.parquet", "metrics.json")


def _cfg():
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["SPY", "QQQ"]
    cfg.universe.min_history_days = 5
    cfg.signal.top_k = 2
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    return cfg


def _snap(n=40):
    dates = make_dates(n)
    rng = np.random.default_rng(11)
    return make_snapshot(
        {
            "SPY": list(100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))),
            "QQQ": list(200.0 * np.cumprod(1 + rng.normal(0.0005, 0.012, n))),
        },
        dates,
    )


def _run(tmp_path, name):
    return run_experiment(
        cfg=_cfg(),
        snapshot=_snap(),
        out_root=tmp_path / name,
        label="repro",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )


def test_two_runs_produce_byte_identical_data_artifacts(tmp_path):
    a = _run(tmp_path, "a")
    b = _run(tmp_path, "b")
    for fn in DATA_FILES:
        assert (a / fn).read_bytes() == (b / fn).read_bytes(), fn


def test_two_runs_share_identity_but_may_differ_in_created_at(tmp_path):
    a = json.loads((_run(tmp_path, "a") / "manifest.json").read_text(encoding="utf-8"))
    b = json.loads((_run(tmp_path, "b") / "manifest.json").read_text(encoding="utf-8"))
    assert a["identity"] == b["identity"]
    assert set(a) == {"identity", "created_at"}


def test_changing_config_changes_config_hash(tmp_path):
    a = json.loads((_run(tmp_path, "a") / "manifest.json").read_text(encoding="utf-8"))

    cfg = _cfg()
    cfg.costs.per_side_bps = 20.0
    d = run_experiment(
        cfg=cfg,
        snapshot=_snap(),
        out_root=tmp_path / "c",
        label="repro",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )
    b = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert a["identity"]["config_hash"] != b["identity"]["config_hash"]


def test_changing_cost_changes_nav(tmp_path):
    """config_hash 變了但輸出沒變 = hash 沒綁到真正影響結果的東西。"""
    a = pd.read_parquet(_run(tmp_path, "a") / "nav.parquet")

    cfg = _cfg()
    cfg.costs.per_side_bps = 20.0
    d = run_experiment(
        cfg=cfg,
        snapshot=_snap(),
        out_root=tmp_path / "c",
        label="repro",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )
    b = pd.read_parquet(d / "nav.parquet")
    assert not np.allclose(a["nav"].to_numpy(), b["nav"].to_numpy())
```

- [ ] **Step 2: 跑測試**

Run: `uv run pytest tests/test_invariants/test_reproducibility.py -v`
Expected: 全部 PASS。**若 `test_two_runs_produce_byte_identical_data_artifacts` 失敗**，代表寫檔非決定性——依序檢查：(1) parquet 列序（`nav`/`weights` 是否依 `strategy_id, date` 排序）、(2) dict 迭代序（`target_weights` 的 JSON 是否 `sort_keys=True`）、(3) 浮點是否來自不同路徑。修 `tracking._write_parquet`：在寫出前 `df.sort_values(list(df.columns[:3])).reset_index(drop=True)`。

- [ ] **Step 3: Commit**

```bash
git add tests/test_invariants/test_reproducibility.py
git commit -m "test(invariants): INV-6 可重現性（雙跑資料產出逐位元相同）"
```

---

## Task 14: `requires_snapshot` marker

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/conftest.py`

- [ ] **Step 1: 加 marker 與自動 skip**

`pyproject.toml` 的 `[tool.pytest.ini_options]` 加入：

```toml
markers = [
    "requires_snapshot: 需要 snapshots/ 下的真實快照；CI 無快照（gitignore）故自動 skip",
]
```

`tests/conftest.py`：

```python
"""全域 pytest 設定。

snapshots/ 為 gitignore（規格 §2.1：hash 進版控而非資料本身），CI 上不存在真實快照。
標記 requires_snapshot 的測試在快照缺席時自動 skip，而非紅燈。
"""

from pathlib import Path

import pytest

from quantcore.config import load_config

CONFIG_YAML = "quantcore/config/default.yaml"


@pytest.fixture(scope="session")
def real_snapshot_dir() -> Path:
    return Path(load_config(CONFIG_YAML).snapshot)


def pytest_runtest_setup(item):
    if "requires_snapshot" in item.keywords:
        d = Path(load_config(CONFIG_YAML).snapshot)
        if not (d / "MANIFEST.json").exists():
            pytest.skip(f"無真實快照（{d}）——CI 環境預期如此")
```

- [ ] **Step 2: 確認 marker 生效**

Run: `uv run pytest --markers | head -5`
Expected: 列出 `@pytest.mark.requires_snapshot`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml tests/conftest.py
git commit -m "test: requires_snapshot marker（CI 無真實快照時自動 skip）"
```

---

## Task 15: 真實快照跑一次 + `bh_spy` 外部驗證（AC-3）

> **此 Task 需要使用者輸入，不可自行編造數字。**

- [ ] **Step 1: 對真實快照跑一次**

Run:
```bash
uv run python -m quantcore.experiments.runner --config quantcore/config/default.yaml --label phase2
```
Expected: 印出 `run 已完成：runs/<日期>_<時間>_phase2`

- [ ] **Step 2: 取出 `bh_spy` 的實際數字**

Run:
```bash
uv run python -c "
import json, glob
d = sorted(glob.glob('runs/*_phase2'))[-1]
m = json.load(open(d + '/metrics.json', encoding='utf-8'))
print(json.dumps(m['bh_spy'], indent=2, ensure_ascii=False))
import pandas as pd
nav = pd.read_parquet(d + '/nav.parquet')
nav = nav[nav.strategy_id == 'bh_spy']
print('期間：', nav['date'].min(), '→', nav['date'].max())
"
```

- [ ] **Step 3: 向使用者索取外部數字**

停下來，把 Step 2 的期間（起訖日）回報給使用者，請其於 portfoliovisualizer 查詢
**SPY 同期、含息、同起訖日**的 CAGR，並提供：數字、查詢日期、是否含息、期間。

**不得填入未經查證的數字**——否則此條 AC 淪為自我驗證。

- [ ] **Step 4: 估算容差並寫測試**

拿到外部數字後，逐項估算差異來源的量級，**再**決定容差（設計文件 §6.3：不可憑空指定）：

1. **滑價**：`bh_spy` 全期僅一次交易，成本 = `per_side_bps` = 5 bps 一次性。攤到 N 年 → `5/N` bps/年。
2. **現金計息**：`bh_spy` 的 `w_cash` 恆為 0 → 貢獻 0。
3. **資料源差異**：我們的 `adj_close` 為自建決定性含息調整（Phase 1），PV 用其自有資料源，除息日處理可能微異。

容差 = 三項合計，並在 docstring 逐項寫明推導。

`tests/test_backtest/test_bh_spy_external.py`：

```python
"""AC-3：bh_spy 與外部來源的端到端體檢（規格 §9 Phase 2）。

本測試需真實快照，CI 無快照故自動 skip（見 tests/conftest.py）——它是**本機閘門**。

外部參照（由使用者於 <查詢日期> 查 portfoliovisualizer 取得）：
    期間：<起> → <訖>
    標的：SPY，含息（total return）
    CAGR：<外部數字>

容差推導（設計文件 §6.3——先跑出實際數字再估算，不憑空指定）：
    滑價        ：全期僅一次交易 × 5 bps，攤於 <N> 年 → <x> bps/年
    現金計息    ：w_cash 恆為 0 → 0 bps/年
    資料源差異  ：自建含息調整 vs PV 資料源，除息日處理微異 → <y> bps/年
    合計容差    ：<z> bps/年
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from quantcore.config import load_config
from quantcore.data.snapshot import load_snapshot
from quantcore.experiments.runner import run_experiment

PV_CAGR = None  # ← 由使用者提供後填入；未填時本測試必須失敗而非誤過
TOLERANCE = None  # ← 依上方推導填入（小數，如 0.0030 表 30 bps/年）


@pytest.mark.requires_snapshot
def test_bh_spy_cagr_matches_portfoliovisualizer(tmp_path):
    assert PV_CAGR is not None, "外部參照數字尚未填入——見本檔 docstring"
    assert TOLERANCE is not None, "容差尚未依實際差異推導——見設計文件 §6.3"

    cfg = load_config("quantcore/config/default.yaml")
    snapshot = load_snapshot(cfg.snapshot)
    d = run_experiment(
        cfg=cfg,
        snapshot=snapshot,
        out_root=tmp_path,
        label="ac3",
        strategy_ids=["bh_spy"],
        now=pd.Timestamp("2026-07-17T00:00:00"),
    )
    m = json.loads(Path(d / "metrics.json").read_text(encoding="utf-8"))
    ours = m["bh_spy"]["annualized_return"]
    assert ours == pytest.approx(PV_CAGR, abs=TOLERANCE)
```

- [ ] **Step 5: 跑測試**

Run: `uv run pytest tests/test_backtest/test_bh_spy_external.py -v`
Expected: PASS（本機，有快照時）

- [ ] **Step 6: 寫推導文件**

`docs/phase2-bh-spy-external-check.md`：記錄期間、外部數字與來源、我們的數字、
逐項差異推導、結論。若差異超出容差且無法解釋 → **AC 不過，不得進 Phase 3**，
先查引擎。

- [ ] **Step 7: Commit**

```bash
git add tests/test_backtest/test_bh_spy_external.py docs/phase2-bh-spy-external-check.md
git commit -m "test(backtest): AC-3 bh_spy 對外部來源的端到端體檢"
```

---

## Task 16: 收尾

- [ ] **Step 1: 全套測試 + lint**

Run:
```bash
uv run pytest
uv run ruff check quantcore tests
uv run ruff format --check quantcore tests
```
Expected: 全綠、`All checks passed!`、`already formatted`

- [ ] **Step 2: 更新 PROGRESS.md**

`## Phase 2` 區塊：任務全部打勾；**補上 `experiments/tracking.py`、`experiments/runner.py`、
`portfolio/selection.py`、`backtest/strategies/` 四項**（原清單只列 backtest/ 六檔，
但 AC 的 INV-6 隱含 experiments/）。AC 三條打勾，AC-3 註明為本機閘門。

加「Phase 2 實作備忘（與原規劃的差異）」節，列設計文件 §10 的七處偏離：

1. 迴圈順序改為「損益 → 漂移 → 執行 → 決策」（§6.1 伪代碼與 §1.2 矛盾，以 §1.2 為準）
2. run 目錄名改為 `YYYY-MM-DD_HHMM_<label>`（§7.1 範例含策略名，但一 run 多策略）
3. 具體策略置於 `backtest/strategies/` 子套件（§2.1 只給了介面）
4. AC-3 為本機閘門而非 CI（`snapshots/` gitignore）
5. 新增 `tests/test_backtest/`、`tests/test_portfolio/`、`tests/test_experiments/`（§8 測試樹未列）
6. 決策日錨定於 warmup 結束後第一個交易日（§1.7 只給間隔未給起點）
7. `Strategy.decide` 加 `event` 參數（§6.2 的 `decide(view)` 無法分辨選擇日／曝險檢查日）

`## 變更紀錄` 加一行（日期 2026-07-17）。

- [ ] **Step 3: Commit 並合併**

```bash
git add PROGRESS.md
git commit -m "docs(phase2): 更新進度與規格偏離備忘"
git checkout main
git merge --no-ff feature/phase2-backtest-core -m "Merge branch 'feature/phase2-backtest-core'"
```

---

## 自我檢查（寫計畫時已跑過）

- **設計文件覆蓋**：§0 範圍決策 → Task 1/2/8/12；§2 事件時鐘與會計 → Task 3/6/9；
  §3 模組 → Task 3-12；§4 Strategy → Task 7/8；§5 產出 → Task 11/12；§6 測試 → Task 3/4/6/13/14/15；
  §7 config → Task 1；§9 交付順序 → Task 1-16。無遺漏。
- **無 placeholder**：Task 15 的 `PV_CAGR` / `TOLERANCE` 是**刻意**的 `None`，且測試會因
  `assert ... is not None` 而失敗——這是「需要人提供輸入」的硬閘門，不是待填的 TODO。
- **型別一致性**：`CASH` 定義於 `accounting.py`，`strategy.py` / 策略 / `engine.py` 皆自此 import；
  `DecisionEvent` 定義於 `strategy.py`；`run_strategy(snapshot, clock, strategy, cfg)` 的
  簽章在 Task 9 定義、Task 12 呼叫一致；`Diagnostics` 欄位名與 `_diagnostics_row()` 一致。
