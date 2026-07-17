# Phase 1 — 資料層 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 QuantCore 資料層——Provider 介面、yfinance/Tiingo/Stooq/FRED adapters、NYSE 日曆、決定性快照與 hash、§4.3 驗證與 §4.5 跨源交叉驗證，並以 `snapshot create` CLI 產出不可變快照。

**Architecture:** 每個 adapter 拆為「薄網路邊界 + 純正規化函數」；純函數與所有驗證/快照邏輯以合成 fixtures 與 fake providers 離線測試（CI 全綠）。快照完整性 hash 走 canonical 資料表示（非 parquet 位元組）以守住「同日重建 hash 相同」。所有資料品質門檻進 config `data_quality` 區塊，模組不內嵌魔術數字。

**Tech Stack:** Python 3.12、uv、pandas、pyarrow、numpy、yfinance、requests、exchange_calendars、pandas-datareader、python-dotenv、pytest。

**依賴方向：** `config ← data`。`data` 只 import `config`；引擎其他層不 import yfinance。

**設計文件：** `docs/superpowers/specs/2026-07-13-phase1-data-layer-design.md`

**執行提醒：**
- 每個 adapter 的網路邊界函數（實際打 API）**不寫自動化測試**，只在 Task 12 的真實快照建立時端到端驗證；純正規化函數與所有邏輯層一律離線測試。
- 每個 Task 結尾都 commit。commit message 用 `feat(data): …` / `test(data): …` / `chore(phase1): …`。
- 執行環境為 Windows PowerShell；跑測試用 `uv run pytest`。

---

## 檔案結構

| 檔案 | 職責 |
|------|------|
| `quantcore/data/secrets.py` | 讀 `.env` / `os.environ` 取密鑰（`TIINGO_API_KEY`），缺鍵給清楚錯誤 |
| `quantcore/config/schema.py`（修改） | 新增 `DataQualityConfig`，掛到 `QuantConfig` |
| `quantcore/data/hashing.py` | `canonical_hash`、`canonicalize`、`config_hash`、`snapshot_id` |
| `quantcore/data/provider.py` | `DataProvider` Protocol + tidy schema 常數與 `empty_prices()` |
| `quantcore/data/calendar.py` | NYSE（XNYS）session 查詢封裝 |
| `quantcore/data/providers/yfinance_adapter.py` | primary：邊界 + `normalize_yfinance` + `fetch_dividends` |
| `quantcore/data/providers/tiingo_adapter.py` | validation：邊界 + `normalize_tiingo` |
| `quantcore/data/providers/stooq_adapter.py` | arbiter：邊界 + `normalize_stooq`（預留，暫不併入驗證） |
| `quantcore/data/providers/fred_adapter.py` | DTB3：keyless 邊界 + `normalize_fred` |
| `quantcore/data/validation.py` | §4.3 五項檢查（純函數）+ `ValidationResult` |
| `quantcore/data/crosssource.py` | §4.5 跨源日報酬比對 + `CrossSourceResult` |
| `quantcore/data/snapshot.py` | 組裝流程 `create_snapshot`、`load_snapshot`、CLI |
| `tests/test_data/*` | 全離線測試 |
| `.env.example`、`.gitignore`（修改）、`pyproject.toml`（修改） | 依賴與密鑰機制 |

---

## Task 1: 依賴、密鑰機制、config schema 擴充

**Files:**
- Modify: `pyproject.toml`
- Create: `.env.example`
- Modify: `.gitignore`
- Create: `quantcore/data/secrets.py`
- Test: `tests/test_data/test_secrets.py`
- Modify: `quantcore/config/schema.py`
- Modify: `quantcore/config/default.yaml`
- Modify: `tests/test_config.py`

- [ ] **Step 1: 加入依賴到 `pyproject.toml`**

把 `dependencies` 區塊改為：

```toml
dependencies = [
    "pydantic>=2.6",
    "pyyaml>=6.0",
    "pandas>=2.2",
    "pyarrow>=16.0",
    "numpy>=1.26",
    "yfinance>=0.2.40",
    "requests>=2.31",
    "exchange-calendars>=4.5",
    "pandas-datareader>=0.10",
    "python-dotenv>=1.0",
]
```

- [ ] **Step 2: 安裝依賴**

Run: `uv sync --extra dev`
Expected: 解析並安裝成功，無錯誤。

- [ ] **Step 3: 建立 `.env.example` 並把 `.env` 加入 `.gitignore`**

`.env.example`：

```
# 複製本檔為 .env（.env 已 gitignore，切勿提交）
# Tiingo 免費 API key：https://www.tiingo.com/account/api/token
TIINGO_API_KEY=your_tiingo_key_here
```

在 `.gitignore` 的「Claude Code 本地個人設定」段落上方或密鑰相關處新增：

```
# --- 密鑰（切勿進版控） ---
.env
```

- [ ] **Step 4: 寫失敗測試 `tests/test_data/test_secrets.py`**

```python
"""密鑰讀取：優先 os.environ，缺鍵給清楚錯誤。"""

import pytest

from quantcore.data.secrets import MissingSecretError, get_secret


def test_get_secret_from_environ(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "abc123")
    assert get_secret("TIINGO_API_KEY") == "abc123"


def test_missing_secret_raises_with_hint(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    with pytest.raises(MissingSecretError) as exc:
        get_secret("TIINGO_API_KEY")
    assert "TIINGO_API_KEY" in str(exc.value)
    assert ".env" in str(exc.value)
```

同時建立空的 `tests/test_data/__init__.py`。

- [ ] **Step 5: 執行測試確認失敗**

Run: `uv run pytest tests/test_data/test_secrets.py -v`
Expected: FAIL（`ModuleNotFoundError: quantcore.data.secrets`）。

- [ ] **Step 6: 實作 `quantcore/data/secrets.py`**

```python
"""密鑰讀取（設計文件 §5.2）。

優先讀 os.environ；若專案根有 .env 則先載入（python-dotenv）。
密鑰絕不寫入任何進版控檔案或 log。
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# import 時載入一次 .env（若存在）；不覆蓋既有環境變數。
load_dotenv(override=False)


class MissingSecretError(RuntimeError):
    """要求的密鑰不存在時拋出。"""


def get_secret(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingSecretError(
            f"缺少密鑰 {name}。請在專案根建立 .env（可複製 .env.example）"
            f" 並設定 {name}=…，或於 shell export {name}。"
        )
    return value
```

- [ ] **Step 7: 執行測試確認通過**

Run: `uv run pytest tests/test_data/test_secrets.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 8: 擴充 config schema — 新增 `DataQualityConfig`**

在 `quantcore/config/schema.py` 的 `CostsConfig` 之後、`BacktestConfig` 之前插入：

```python
class DataQualityConfig(_Strict):
    """資料品質門檻（設計文件 §7a、規格 §4.3/§4.5）。"""

    discrepancy_bps: float = Field(gt=0)       # §4.5 跨源日報酬差異門檻
    window_days: int = Field(gt=0)             # §4.5 滾動窗（交易日）
    window_max_hits: int = Field(gt=0)         # §4.5 窗內差異筆數上限（達到即失敗）
    extreme_return: float = Field(gt=0, lt=1)  # §4.3-2 單日 |r| 極端值門檻
    max_consecutive_nan: int = Field(gt=0)     # §4.3-3 連續缺值上限（超過即拒絕）
    total_return_tol_bps: float = Field(gt=0)  # §4.3-1 總報酬抽查容差
```

在 `QuantConfig` 加欄位（放在 `costs` 之後）：

```python
    costs: CostsConfig
    data_quality: DataQualityConfig
    backtest: BacktestConfig
```

- [ ] **Step 9: 更新 `quantcore/config/default.yaml`**

在 `costs:` 區塊之後、`backtest:` 之前插入：

```yaml
data_quality:                       # §4.3 / §4.5 資料品質門檻
  discrepancy_bps: 50               # 跨源日報酬差異門檻（bps）
  window_days: 30                   # 滾動窗（交易日）
  window_max_hits: 3                # 窗內差異達此筆數即快照失敗
  extreme_return: 0.20              # 單日 |r| 極端值門檻
  max_consecutive_nan: 5            # 連續缺值超過即拒絕
  total_return_tol_bps: 10          # 總報酬抽查容差（bps）
```

- [ ] **Step 10: 更新 `tests/test_config.py` 補 data_quality 驗證**

在檔尾新增：

```python
def test_data_quality_loaded():
    cfg = load_config(DEFAULT_YAML)
    assert cfg.data_quality.discrepancy_bps == 50
    assert cfg.data_quality.window_days == 30
    assert cfg.data_quality.window_max_hits == 3
    assert cfg.data_quality.max_consecutive_nan == 5


def test_data_quality_rejects_bad_extreme_return():
    raw = _valid_dict()
    raw["data_quality"]["extreme_return"] = 1.5  # 必須 < 1
    with pytest.raises(ValidationError):
        QuantConfig.model_validate(raw)
```

- [ ] **Step 11: 執行全部測試確認通過**

Run: `uv run pytest -q`
Expected: 既有 + 新測試全綠。

- [ ] **Step 12: ruff/black + commit**

```bash
uv run ruff check quantcore tests
uv run black quantcore tests
git add pyproject.toml uv.lock .env.example .gitignore quantcore/config/schema.py quantcore/config/default.yaml quantcore/data/secrets.py tests/test_data/ tests/test_config.py
git commit -m "chore(phase1): 依賴、.env 密鑰機制、config data_quality 區塊"
```

---

## Task 2: 決定性 canonical hash（`hashing.py`）

守住 AC-4「同日重建兩次快照 hash 相同」。

**Files:**
- Create: `quantcore/data/hashing.py`
- Test: `tests/test_data/test_hashing.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_data/test_hashing.py`**

```python
"""決定性 canonical hash（設計文件 §3.2）。"""

import numpy as np
import pandas as pd

from quantcore.data.hashing import canonical_hash, canonicalize, snapshot_id


def _frame():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-03", "2020-01-02"]),
            "ticker": ["SPY", "SPY"],
            "adj_close": [301.5, np.nan],
        }
    )


def test_hash_is_stable_across_row_order():
    a = canonicalize(_frame(), sort_cols=["ticker", "date"])
    shuffled = _frame().iloc[::-1].reset_index(drop=True)
    b = canonicalize(shuffled, sort_cols=["ticker", "date"])
    assert canonical_hash(a) == canonical_hash(b)


def test_hash_changes_on_value_change():
    a = canonicalize(_frame(), sort_cols=["ticker", "date"])
    df2 = _frame()
    df2.loc[0, "adj_close"] = 999.0
    b = canonicalize(df2, sort_cols=["ticker", "date"])
    assert canonical_hash(a) != canonical_hash(b)


def test_nan_is_deterministic():
    a = canonicalize(_frame(), sort_cols=["ticker", "date"])
    b = canonicalize(_frame(), sort_cols=["ticker", "date"])
    assert canonical_hash(a) == canonical_hash(b)


def test_snapshot_id_format():
    sid = snapshot_id(pd.Timestamp("2026-07-13"), "deadbeefcafe")
    assert sid == "2026-07-13_deadbe"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_data/test_hashing.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 實作 `quantcore/data/hashing.py`**

```python
"""決定性 canonical hash（設計文件 §3.2）。

MANIFEST 的 content SHA-256 由資料的 canonical 表示計算，而非 parquet 位元組，
因 parquet 內嵌套件版本/時間戳，位元組不決定性。canonical_hash 逐欄雜湊
dtype 標籤 + 原始值，跨 pandas/pyarrow 版本與 OS 皆決定性。
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd


def canonicalize(df: pd.DataFrame, sort_cols: list[str]) -> pd.DataFrame:
    """固定列序、欄序、重設索引。hash 前一律先過此函數。"""
    return df.sort_values(sort_cols, kind="stable").reset_index(drop=True)


def canonical_hash(df: pd.DataFrame) -> str:
    """對 canonicalize 後的 DataFrame 計算決定性 SHA-256。"""
    h = hashlib.sha256()
    for col in df.columns:
        h.update(str(col).encode("utf-8"))
        s = df[col]
        kind = s.dtype.kind
        h.update(kind.encode("ascii"))
        if kind == "f":
            h.update(np.ascontiguousarray(s.to_numpy(dtype="float64")).tobytes())
        elif kind in ("i", "u"):
            h.update(np.ascontiguousarray(s.to_numpy(dtype="int64")).tobytes())
        elif kind == "b":
            h.update(np.ascontiguousarray(s.to_numpy(dtype="int8")).tobytes())
        elif kind == "M":
            arr = s.to_numpy(dtype="datetime64[ns]").astype("int64")
            h.update(np.ascontiguousarray(arr).tobytes())
        else:  # object / string
            for v in s.tolist():
                b = (b"\x00NULL" if v is None or (isinstance(v, float) and np.isnan(v))
                     else str(v).encode("utf-8"))
                h.update(len(b).to_bytes(8, "little"))
                h.update(b)
    return h.hexdigest()


def config_hash(config_dict: dict) -> str:
    """對 config（已轉為 JSON-safe dict）計算決定性 hash。"""
    payload = json.dumps(config_dict, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def combined_hash(parts: list[str]) -> str:
    """把多個 hex hash 合併成單一 hash（順序固定）。"""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("ascii"))
    return h.hexdigest()


def snapshot_id(build_date: pd.Timestamp, combined: str) -> str:
    """快照目錄名：{YYYY-MM-DD}_{前 6 hex}。"""
    return f"{build_date:%Y-%m-%d}_{combined[:6]}"
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_data/test_hashing.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: ruff/black + commit**

```bash
uv run ruff check quantcore/data/hashing.py tests/test_data/test_hashing.py
uv run black quantcore/data/hashing.py tests/test_data/test_hashing.py
git add quantcore/data/hashing.py tests/test_data/test_hashing.py
git commit -m "feat(data): 決定性 canonical hash（守 AC-4 同日重建 hash 相同）"
```

---

## Task 3: DataProvider 介面（`provider.py`）

**Files:**
- Create: `quantcore/data/provider.py`
- Test: `tests/test_data/test_provider.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_data/test_provider.py`**

```python
"""DataProvider Protocol 與 tidy schema。"""

import pandas as pd

from quantcore.data.provider import PRICE_COLUMNS, DataProvider, empty_prices


class _FakeProvider:
    def fetch_prices(self, tickers, start, end):
        return empty_prices()

    def fetch_metadata(self, tickers):
        return {t: {"inception_date": "2000-01-01", "name": t} for t in tickers}

    def fetch_series(self, series_id, start, end):
        return pd.Series(dtype="float64", name=series_id)


def test_price_columns_order():
    assert PRICE_COLUMNS == ["date", "ticker", "close", "adj_close", "volume"]


def test_empty_prices_has_schema():
    df = empty_prices()
    assert list(df.columns) == PRICE_COLUMNS


def test_fake_satisfies_protocol():
    p: DataProvider = _FakeProvider()
    assert isinstance(p.fetch_metadata(["SPY"]), dict)
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_data/test_provider.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 實作 `quantcore/data/provider.py`**

```python
"""DataProvider 介面與 tidy schema（規格 §4.1）。

引擎任何模組不得 import 具體 adapter；只認識本 Protocol 與快照格式。
tidy 格式：columns = [date, ticker, close, adj_close, volume]。
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd

PRICE_COLUMNS = ["date", "ticker", "close", "adj_close", "volume"]


def empty_prices() -> pd.DataFrame:
    """回傳符合 tidy schema 的空 DataFrame。"""
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "ticker": pd.Series(dtype="object"),
            "close": pd.Series(dtype="float64"),
            "adj_close": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="float64"),
        }
    )


@runtime_checkable
class DataProvider(Protocol):
    def fetch_prices(
        self, tickers: list[str], start: date, end: date
    ) -> pd.DataFrame:
        """tidy 格式：columns = [date, ticker, close, adj_close, volume]。"""
        ...

    def fetch_metadata(self, tickers: list[str]) -> dict:
        """每檔：inception_date、name（可含 asset_class）。"""
        ...

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.Series:
        """總經/利率序列（FRED 用），index 為日期。"""
        ...
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_data/test_provider.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: commit**

```bash
uv run ruff check quantcore/data/provider.py tests/test_data/test_provider.py
uv run black quantcore/data/provider.py tests/test_data/test_provider.py
git add quantcore/data/provider.py tests/test_data/test_provider.py
git commit -m "feat(data): DataProvider Protocol 與 tidy schema（§4.1）"
```

---

## Task 4: NYSE 日曆（`calendar.py`）

**Files:**
- Create: `quantcore/data/calendar.py`
- Test: `tests/test_data/test_calendar.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_data/test_calendar.py`**

```python
"""NYSE 日曆封裝。"""

import pandas as pd

from quantcore.data.calendar import NyseCalendar


def test_known_session_and_holiday():
    cal = NyseCalendar()
    # 2020-01-02 為交易日；2020-01-01（元旦）非交易日
    assert cal.is_session(pd.Timestamp("2020-01-02"))
    assert not cal.is_session(pd.Timestamp("2020-01-01"))


def test_sessions_in_range_are_sorted_unique():
    cal = NyseCalendar()
    sessions = cal.sessions_in_range("2020-01-01", "2020-01-10")
    assert list(sessions) == sorted(sessions)
    assert len(set(sessions)) == len(sessions)
    # 2020-01-02..01-10 有 7 個交易日（01-01 假日、週末排除）
    assert len(sessions) == 7
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_data/test_calendar.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 實作 `quantcore/data/calendar.py`**

```python
"""NYSE 交易日曆封裝（規格 §4.3-4/5，套件 exchange_calendars XNYS）。"""

from __future__ import annotations

import exchange_calendars as xcals
import pandas as pd


class NyseCalendar:
    """XNYS 交易日曆的薄封裝，對外只暴露本專案需要的查詢。"""

    def __init__(self) -> None:
        self._cal = xcals.get_calendar("XNYS")

    def is_session(self, day: pd.Timestamp) -> bool:
        return self._cal.is_session(pd.Timestamp(day).normalize())

    def sessions_in_range(self, start, end) -> pd.DatetimeIndex:
        sessions = self._cal.sessions_in_range(
            pd.Timestamp(start), pd.Timestamp(end)
        )
        # 回傳 tz-naive、normalize 到午夜的 DatetimeIndex
        return pd.DatetimeIndex(sessions).tz_localize(None).normalize()
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_data/test_calendar.py -v`
Expected: PASS（2 passed）。若 session 數與註解不符，以實際 XNYS 日曆為準修正註解，不改邏輯。

- [ ] **Step 5: commit**

```bash
uv run ruff check quantcore/data/calendar.py tests/test_data/test_calendar.py
uv run black quantcore/data/calendar.py tests/test_data/test_calendar.py
git add quantcore/data/calendar.py tests/test_data/test_calendar.py
git commit -m "feat(data): NYSE 日曆封裝（exchange_calendars XNYS）"
```

---

## Task 5: yfinance adapter（primary）

**Files:**
- Create: `quantcore/data/providers/yfinance_adapter.py`
- Test: `tests/test_data/test_yfinance_normalize.py`

只測純正規化函數（離線）；網路邊界於 Task 12 端到端驗證。

- [ ] **Step 1: 寫失敗測試 `tests/test_data/test_yfinance_normalize.py`**

```python
"""yfinance 正規化：單一 ticker 原始 frame → tidy 長格式。"""

import numpy as np
import pandas as pd

from quantcore.data.provider import PRICE_COLUMNS
from quantcore.data.providers.yfinance_adapter import normalize_yfinance


def _raw_single_ticker():
    idx = pd.to_datetime(["2020-01-02", "2020-01-03"])
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.5],
            "Adj Close": [100.2, 101.7],
            "Volume": [1_000_000, 1_200_000],
        },
        index=idx,
    )


def test_normalize_shape_and_columns():
    tidy = normalize_yfinance(_raw_single_ticker(), "SPY")
    assert list(tidy.columns) == PRICE_COLUMNS
    assert len(tidy) == 2
    assert (tidy["ticker"] == "SPY").all()
    assert tidy["adj_close"].iloc[0] == 100.2
    assert tidy["date"].dtype.kind == "M"


def test_normalize_empty_returns_schema():
    tidy = normalize_yfinance(pd.DataFrame(), "SPY")
    assert list(tidy.columns) == PRICE_COLUMNS
    assert tidy.empty
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_data/test_yfinance_normalize.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 實作 `quantcore/data/providers/yfinance_adapter.py`**

```python
"""yfinance adapter（primary，規格 §4.1/§4.5）。

拆為薄網路邊界（fetch_prices/fetch_metadata/fetch_dividends）與純正規化函數
（normalize_yfinance）。引擎其他層不得 import 本模組。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from quantcore.data.provider import PRICE_COLUMNS, empty_prices


def normalize_yfinance(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """單一 ticker 的 yfinance 原始 frame → tidy 長格式。"""
    if raw is None or raw.empty:
        return empty_prices()
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw.index).tz_localize(None).normalize(),
            "ticker": ticker,
            "close": raw["Close"].to_numpy(dtype="float64"),
            "adj_close": raw["Adj Close"].to_numpy(dtype="float64"),
            "volume": raw["Volume"].to_numpy(dtype="float64"),
        }
    )
    return out[PRICE_COLUMNS].reset_index(drop=True)


class YFinanceAdapter:
    """primary provider。網路邊界；離線測試以 normalize_yfinance 為準。"""

    def fetch_prices(
        self, tickers: list[str], start: date, end: date
    ) -> pd.DataFrame:
        import yfinance as yf

        frames = []
        for t in tickers:
            raw = yf.download(
                t, start=start, end=end, auto_adjust=False,
                actions=False, progress=False,
            )
            frames.append(normalize_yfinance(raw, t))
        return (
            pd.concat(frames, ignore_index=True) if frames else empty_prices()
        )

    def fetch_metadata(self, tickers: list[str]) -> dict:
        import yfinance as yf

        meta: dict = {}
        for t in tickers:
            info = yf.Ticker(t).history_metadata
            first = info.get("firstTradeDate") if isinstance(info, dict) else None
            inception = (
                pd.Timestamp(first, unit="s").strftime("%Y-%m-%d")
                if first is not None else None
            )
            meta[t] = {"inception_date": inception, "name": t}
        return meta

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.Series:
        raise NotImplementedError("yfinance 不供利率序列；DTB3 用 FredAdapter。")

    def fetch_dividends(
        self, ticker: str, start: date, end: date
    ) -> pd.DataFrame:
        """§4.3-1 總報酬檢查用：columns = [date, dividend]。"""
        import yfinance as yf

        div = yf.Ticker(ticker).dividends
        if div is None or len(div) == 0:
            return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"),
                                 "dividend": pd.Series(dtype="float64")})
        div = div[(div.index >= pd.Timestamp(start, tz=div.index.tz))
                  & (div.index <= pd.Timestamp(end, tz=div.index.tz))]
        return pd.DataFrame(
            {
                "date": pd.to_datetime(div.index).tz_localize(None).normalize(),
                "dividend": div.to_numpy(dtype="float64"),
            }
        ).reset_index(drop=True)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_data/test_yfinance_normalize.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: commit**

```bash
uv run ruff check quantcore/data/providers/yfinance_adapter.py tests/test_data/test_yfinance_normalize.py
uv run black quantcore/data/providers/yfinance_adapter.py tests/test_data/test_yfinance_normalize.py
git add quantcore/data/providers/yfinance_adapter.py tests/test_data/test_yfinance_normalize.py
git commit -m "feat(data): yfinance adapter（primary，normalize + 網路邊界）"
```

---

## Task 6: Tiingo adapter（validation）

**Files:**
- Create: `quantcore/data/providers/tiingo_adapter.py`
- Test: `tests/test_data/test_tiingo_normalize.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_data/test_tiingo_normalize.py`**

```python
"""Tiingo 正規化：REST JSON payload → tidy 長格式。"""

from quantcore.data.provider import PRICE_COLUMNS
from quantcore.data.providers.tiingo_adapter import normalize_tiingo


def _payload():
    return [
        {"date": "2020-01-02T00:00:00.000Z", "close": 101.0,
         "adjClose": 100.2, "volume": 1000000},
        {"date": "2020-01-03T00:00:00.000Z", "close": 102.5,
         "adjClose": 101.7, "volume": 1200000},
    ]


def test_normalize_columns_and_values():
    tidy = normalize_tiingo(_payload(), "SPY")
    assert list(tidy.columns) == PRICE_COLUMNS
    assert len(tidy) == 2
    assert tidy["adj_close"].iloc[1] == 101.7
    assert (tidy["ticker"] == "SPY").all()


def test_normalize_empty_payload():
    tidy = normalize_tiingo([], "SPY")
    assert list(tidy.columns) == PRICE_COLUMNS
    assert tidy.empty
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_data/test_tiingo_normalize.py -v`
Expected: FAIL。

- [ ] **Step 3: 實作 `quantcore/data/providers/tiingo_adapter.py`**

```python
"""Tiingo adapter（validation，規格 §4.5）。

免費 API key，adjClose 含息，供跨源總報酬比對。key 由 secrets.get_secret 讀取。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from quantcore.data.provider import PRICE_COLUMNS, empty_prices
from quantcore.data.secrets import get_secret

_BASE = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"


def normalize_tiingo(payload: list[dict], ticker: str) -> pd.DataFrame:
    """Tiingo REST JSON（list[dict]）→ tidy 長格式。"""
    if not payload:
        return empty_prices()
    df = pd.DataFrame(payload)
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize(),
            "ticker": ticker,
            "close": df["close"].to_numpy(dtype="float64"),
            "adj_close": df["adjClose"].to_numpy(dtype="float64"),
            "volume": df["volume"].to_numpy(dtype="float64"),
        }
    )
    return out[PRICE_COLUMNS].reset_index(drop=True)


class TiingoAdapter:
    """validation provider。網路邊界；離線測試以 normalize_tiingo 為準。"""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or get_secret("TIINGO_API_KEY")

    def fetch_prices(
        self, tickers: list[str], start: date, end: date
    ) -> pd.DataFrame:
        import requests

        frames = []
        for t in tickers:
            resp = requests.get(
                _BASE.format(ticker=t),
                params={
                    "startDate": str(start),
                    "endDate": str(end),
                    "format": "json",
                    "token": self._api_key,
                },
                timeout=30,
            )
            resp.raise_for_status()
            frames.append(normalize_tiingo(resp.json(), t))
        return (
            pd.concat(frames, ignore_index=True) if frames else empty_prices()
        )

    def fetch_metadata(self, tickers: list[str]) -> dict:
        return {t: {"inception_date": None, "name": t} for t in tickers}

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.Series:
        raise NotImplementedError("Tiingo 不供本專案利率序列。")
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_data/test_tiingo_normalize.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: commit**

```bash
uv run ruff check quantcore/data/providers/tiingo_adapter.py tests/test_data/test_tiingo_normalize.py
uv run black quantcore/data/providers/tiingo_adapter.py tests/test_data/test_tiingo_normalize.py
git add quantcore/data/providers/tiingo_adapter.py tests/test_data/test_tiingo_normalize.py
git commit -m "feat(data): Tiingo adapter（validation，normalize + 網路邊界）"
```

---

## Task 7: FRED adapter（DTB3，keyless）

**Files:**
- Create: `quantcore/data/providers/fred_adapter.py`
- Test: `tests/test_data/test_fred_normalize.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_data/test_fred_normalize.py`**

```python
"""FRED 正規化：DTB3 原始序列 → 清理後 Series（去除缺值標記）。"""

import numpy as np
import pandas as pd

from quantcore.data.providers.fred_adapter import normalize_fred


def test_normalize_drops_nan_and_sorts():
    idx = pd.to_datetime(["2020-01-03", "2020-01-02"])
    raw = pd.Series([1.55, np.nan], index=idx, name="DTB3")
    out = normalize_fred(raw)
    assert out.name == "DTB3"
    assert list(out.index) == [pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-03")]
    # NaN 保留位置但排序；缺值處理交給驗證層。此處僅排序 + 命名 + tz-naive
    assert out.index.tz is None
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_data/test_fred_normalize.py -v`
Expected: FAIL。

- [ ] **Step 3: 實作 `quantcore/data/providers/fred_adapter.py`**

```python
"""FRED adapter（DTB3 現金利率，規格 §4.4）。

keyless：使用 pandas-datareader 的 FRED 端點（fredgraph.csv），無需 API key。
"""

from __future__ import annotations

from datetime import date

import pandas as pd


def normalize_fred(raw: pd.Series) -> pd.Series:
    """FRED 原始序列 → tz-naive、依日期排序、保留原名。"""
    s = raw.copy()
    s.index = pd.to_datetime(s.index)
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    s.index = s.index.normalize()
    return s.sort_index()


class FredAdapter:
    """DTB3 provider。keyless 網路邊界。"""

    def fetch_prices(self, tickers, start, end):
        raise NotImplementedError("FRED 只供利率序列，用 fetch_series。")

    def fetch_metadata(self, tickers):
        raise NotImplementedError

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.Series:
        from pandas_datareader import data as pdr

        raw = pdr.DataReader(series_id, "fred", start, end)[series_id]
        return normalize_fred(raw.rename(series_id))
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_data/test_fred_normalize.py -v`
Expected: PASS（1 passed）。

- [ ] **Step 5: commit**

```bash
uv run ruff check quantcore/data/providers/fred_adapter.py tests/test_data/test_fred_normalize.py
uv run black quantcore/data/providers/fred_adapter.py tests/test_data/test_fred_normalize.py
git add quantcore/data/providers/fred_adapter.py tests/test_data/test_fred_normalize.py
git commit -m "feat(data): FRED adapter（DTB3，keyless）"
```

---

## Task 8: Stooq adapter（arbiter，預留）

實作正規化 + 邊界，但 v1 不併入交叉驗證（設計決策）。

**Files:**
- Create: `quantcore/data/providers/stooq_adapter.py`
- Test: `tests/test_data/test_stooq_normalize.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_data/test_stooq_normalize.py`**

```python
"""Stooq 正規化：CSV（僅拆分調整，無含息 adj）→ tidy；adj_close = NaN。"""

import numpy as np
import pandas as pd

from quantcore.data.provider import PRICE_COLUMNS
from quantcore.data.providers.stooq_adapter import normalize_stooq


def _csv_frame():
    return pd.DataFrame(
        {
            "Date": ["2020-01-02", "2020-01-03"],
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.5],
            "Volume": [1000000, 1200000],
        }
    )


def test_normalize_sets_adj_close_nan():
    tidy = normalize_stooq(_csv_frame(), "SPY")
    assert list(tidy.columns) == PRICE_COLUMNS
    assert tidy["adj_close"].isna().all()  # Stooq 不含息
    assert tidy["close"].iloc[0] == 101.0
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_data/test_stooq_normalize.py -v`
Expected: FAIL。

- [ ] **Step 3: 實作 `quantcore/data/providers/stooq_adapter.py`**

```python
"""Stooq adapter（arbiter，規格 §4.5；v1 預留，暫不併入交叉驗證）。

免金鑰；僅拆分調整、不含息，故 adj_close 設為 NaN，只可比對價格報酬。
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from quantcore.data.provider import PRICE_COLUMNS, empty_prices

_URL = "https://stooq.com/q/d/l/?s={ticker}.us&d1={d1}&d2={d2}&i=d"


def normalize_stooq(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Stooq CSV frame → tidy；adj_close = NaN（不含息）。"""
    if raw is None or raw.empty:
        return empty_prices()
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["Date"]).dt.normalize(),
            "ticker": ticker,
            "close": raw["Close"].to_numpy(dtype="float64"),
            "adj_close": np.nan,
            "volume": raw["Volume"].to_numpy(dtype="float64"),
        }
    )
    return out[PRICE_COLUMNS].reset_index(drop=True)


class StooqAdapter:
    """arbiter provider（預留）。網路邊界。"""

    def fetch_prices(
        self, tickers: list[str], start: date, end: date
    ) -> pd.DataFrame:
        import io

        import requests

        frames = []
        for t in tickers:
            url = _URL.format(
                ticker=t.lower(),
                d1=f"{start:%Y%m%d}", d2=f"{end:%Y%m%d}",
            )
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            frames.append(normalize_stooq(pd.read_csv(io.StringIO(resp.text)), t))
        return (
            pd.concat(frames, ignore_index=True) if frames else empty_prices()
        )

    def fetch_metadata(self, tickers: list[str]) -> dict:
        return {t: {"inception_date": None, "name": t} for t in tickers}

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.Series:
        raise NotImplementedError
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_data/test_stooq_normalize.py -v`
Expected: PASS（1 passed）。

- [ ] **Step 5: commit**

```bash
uv run ruff check quantcore/data/providers/stooq_adapter.py tests/test_data/test_stooq_normalize.py
uv run black quantcore/data/providers/stooq_adapter.py tests/test_data/test_stooq_normalize.py
git add quantcore/data/providers/stooq_adapter.py tests/test_data/test_stooq_normalize.py
git commit -m "feat(data): Stooq adapter（arbiter，預留介面）"
```

---

## Task 9: 資料驗證（`validation.py`，§4.3 五項）

**Files:**
- Create: `quantcore/data/validation.py`
- Test: `tests/test_data/test_validation.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_data/test_validation.py`**

```python
"""§4.3 五項資料驗證。"""

import numpy as np
import pandas as pd

from quantcore.data.calendar import NyseCalendar
from quantcore.data.validation import (
    check_calendar,
    check_extreme_returns,
    check_missing_values,
    check_monotonic,
    check_total_return,
)


def _prices(ticker, dates, close, adj):
    return pd.DataFrame(
        {"date": pd.to_datetime(dates), "ticker": ticker,
         "close": close, "adj_close": adj,
         "volume": [1e6] * len(dates)}
    )


def test_total_return_passes_when_consistent():
    # 除息日：adj 報酬 ≈ close 報酬 + div/prev_close
    dates = ["2020-03-19", "2020-03-20"]
    close = [100.0, 101.0]
    div = 1.0
    # adj_close 建構成滿足關係：adj_ret = close_ret + div/prev_close
    adj = [100.0, 100.0 * (1 + (101.0 / 100.0 - 1) + div / 100.0)]
    prices = _prices("SPY", dates, close, adj)
    dividends = pd.DataFrame({"date": pd.to_datetime(["2020-03-20"]),
                              "dividend": [div]})
    res = check_total_return(prices, dividends, tol_bps=10)
    assert res.passed


def test_total_return_fails_when_dividend_ignored():
    dates = ["2020-03-19", "2020-03-20"]
    close = [100.0, 101.0]
    adj = [100.0, 101.0]  # adj 沒反映股息 → 應失敗
    prices = _prices("SPY", dates, close, adj)
    dividends = pd.DataFrame({"date": pd.to_datetime(["2020-03-20"]),
                              "dividend": [1.0]})
    res = check_total_return(prices, dividends, tol_bps=10)
    assert not res.passed
    assert res.hard_fail


def test_extreme_returns_flagged():
    prices = _prices("XLE", ["2020-03-08", "2020-03-09"],
                     [50.0, 35.0], [50.0, 35.0])  # -30%
    res = check_extreme_returns(prices, threshold=0.20)
    assert not res.passed
    assert len(res.report) == 1


def test_missing_values_reject_on_long_gap():
    adj = [100.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, 101.0]
    dates = pd.bdate_range("2020-01-02", periods=8)
    prices = _prices("SPY", dates, [100.0] * 8, adj)
    res = check_missing_values(prices, max_consecutive_nan=5)
    assert not res.passed
    assert res.hard_fail


def test_calendar_rejects_non_session():
    prices = _prices("SPY", ["2020-01-01"], [100.0], [100.0])  # 元旦非交易日
    res = check_calendar(prices, NyseCalendar())
    assert not res.passed


def test_monotonic_rejects_duplicate_dates():
    prices = _prices("SPY", ["2020-01-02", "2020-01-02"], [100.0, 101.0],
                     [100.0, 101.0])
    res = check_monotonic(prices)
    assert not res.passed
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_data/test_validation.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 實作 `quantcore/data/validation.py`**

```python
"""資料驗證（規格 §4.3）。純函數；任一 hard_fail 即拒絕產出快照。

門檻一律由呼叫端（快照流程）自 config.data_quality 傳入，模組不內嵌數字。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class ValidationResult:
    name: str
    passed: bool
    hard_fail: bool
    message: str = ""
    report: list[dict] = field(default_factory=list)


def _per_ticker_returns(prices: pd.DataFrame, price_col: str) -> pd.DataFrame:
    df = prices.sort_values(["ticker", "date"]).copy()
    df["ret"] = df.groupby("ticker")[price_col].pct_change()
    return df


def check_total_return(
    prices: pd.DataFrame, dividends: pd.DataFrame, tol_bps: float
) -> ValidationResult:
    """§4.3-1：除息日 adj 報酬 ≈ close 報酬 + 股息/前收盤（容差內）。"""
    df = prices.sort_values("date").copy()
    df["close_ret"] = df["close"].pct_change()
    df["adj_ret"] = df["adj_close"].pct_change()
    df["prev_close"] = df["close"].shift(1)
    div = dividends.set_index("date")["dividend"]
    tol = tol_bps / 1e4
    bad = []
    for _, row in df.dropna(subset=["close_ret", "adj_ret"]).iterrows():
        d = row["date"]
        div_amt = float(div.get(d, 0.0))
        if div_amt == 0.0:
            continue
        expected_adj = row["close_ret"] + div_amt / row["prev_close"]
        if abs(row["adj_ret"] - expected_adj) > tol:
            bad.append({"date": str(d.date()), "adj_ret": row["adj_ret"],
                        "expected": expected_adj})
    passed = not bad
    return ValidationResult("total_return", passed, hard_fail=not passed,
                            report=bad,
                            message="" if passed else f"{len(bad)} 個除息日總報酬不一致")


def check_extreme_returns(
    prices: pd.DataFrame, threshold: float
) -> ValidationResult:
    """§4.3-2：單日 |r| > threshold 的列入人工確認清單（軟性）。"""
    df = _per_ticker_returns(prices, "adj_close")
    hits = df[df["ret"].abs() > threshold]
    report = [{"ticker": r["ticker"], "date": str(r["date"].date()),
               "ret": r["ret"]} for _, r in hits.iterrows()]
    passed = not report
    return ValidationResult("extreme_returns", passed, hard_fail=False,
                            report=report,
                            message="" if passed else f"{len(report)} 筆極端值待人工確認")


def check_missing_values(
    prices: pd.DataFrame, max_consecutive_nan: int
) -> ValidationResult:
    """§4.3-3：上市後序列中間 NaN → 報告；連續 > 上限 → 拒絕。"""
    report = []
    hard = False
    for ticker, g in prices.sort_values("date").groupby("ticker"):
        s = g["adj_close"].to_numpy()
        # 去除上市前的前導 NaN
        first_valid = np.argmax(~np.isnan(s)) if (~np.isnan(s)).any() else len(s)
        core = s[first_valid:]
        run = 0
        max_run = 0
        for v in core:
            run = run + 1 if np.isnan(v) else 0
            max_run = max(max_run, run)
        if max_run > 0:
            report.append({"ticker": ticker, "max_consecutive_nan": int(max_run)})
        if max_run > max_consecutive_nan:
            hard = True
    passed = not hard
    return ValidationResult("missing_values", passed, hard_fail=hard,
                            report=report,
                            message="" if passed else "存在超過上限的連續缺值")


def check_calendar(prices: pd.DataFrame, calendar) -> ValidationResult:
    """§4.3-4：所有日期 ∈ NYSE 交易日曆。"""
    dates = pd.to_datetime(prices["date"]).dt.normalize().unique()
    lo, hi = dates.min(), dates.max()
    sessions = set(calendar.sessions_in_range(lo, hi))
    bad = [str(pd.Timestamp(d).date()) for d in dates
           if pd.Timestamp(d) not in sessions]
    passed = not bad
    return ValidationResult("calendar", passed, hard_fail=not passed,
                            report=[{"date": d} for d in bad],
                            message="" if passed else f"{len(bad)} 個非交易日日期")


def check_monotonic(prices: pd.DataFrame) -> ValidationResult:
    """§4.3-5：每檔資產日期嚴格遞增、無重複。"""
    bad = []
    for ticker, g in prices.groupby("ticker"):
        d = pd.to_datetime(g["date"])
        if d.duplicated().any() or not d.is_monotonic_increasing:
            bad.append(ticker)
    passed = not bad
    return ValidationResult("monotonic", passed, hard_fail=not passed,
                            report=[{"ticker": t} for t in bad],
                            message="" if passed else f"{len(bad)} 檔日期非單調或重複")
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_data/test_validation.py -v`
Expected: PASS（7 passed）。

- [ ] **Step 5: commit**

```bash
uv run ruff check quantcore/data/validation.py tests/test_data/test_validation.py
uv run black quantcore/data/validation.py tests/test_data/test_validation.py
git add quantcore/data/validation.py tests/test_data/test_validation.py
git commit -m "feat(data): §4.3 五項資料驗證（純函數）"
```

---

## Task 10: 跨源交叉驗證（`crosssource.py`，§4.5）

**Files:**
- Create: `quantcore/data/crosssource.py`
- Test: `tests/test_data/test_crosssource.py`

- [ ] **Step 1: 寫失敗測試 `tests/test_data/test_crosssource.py`**

```python
"""§4.5 跨源日報酬比對（v1：yfinance vs Tiingo）。"""

import numpy as np
import pandas as pd

from quantcore.data.crosssource import cross_validate


def _prices(ticker, dates, adj):
    return pd.DataFrame(
        {"date": pd.to_datetime(dates), "ticker": ticker,
         "close": adj, "adj_close": adj, "volume": [1e6] * len(dates)}
    )


def test_identical_sources_pass():
    dates = pd.bdate_range("2020-01-02", periods=40)
    adj = list(100 + np.arange(40) * 0.5)
    primary = _prices("SPY", dates, adj)
    validation = _prices("SPY", dates, adj)
    res = cross_validate(primary, validation,
                         discrepancy_bps=50, window_days=30, window_max_hits=3)
    assert res.passed
    assert len(res.report) == 0


def test_isolated_discrepancy_passes_but_reported():
    dates = pd.bdate_range("2020-01-02", periods=40)
    adj_p = list(100 + np.arange(40) * 0.5)
    adj_v = adj_p.copy()
    adj_v[10] = adj_v[10] * 1.02  # 單一日 ~2% 差異（孤立）
    primary = _prices("SPY", dates, adj_p)
    validation = _prices("SPY", dates, adj_v)
    res = cross_validate(primary, validation,
                         discrepancy_bps=50, window_days=30, window_max_hits=3)
    assert res.passed          # 孤立差異放行
    assert len(res.report) >= 1  # 但仍入報告


def test_clustered_discrepancy_fails():
    dates = pd.bdate_range("2020-01-02", periods=40)
    adj_p = list(100 + np.arange(40) * 0.5)
    adj_v = adj_p.copy()
    for i in (10, 12, 14):       # 30 日窗內 3 筆 → 失敗
        adj_v[i] = adj_v[i] * 1.02
    primary = _prices("SPY", dates, adj_p)
    validation = _prices("SPY", dates, adj_v)
    res = cross_validate(primary, validation,
                         discrepancy_bps=50, window_days=30, window_max_hits=3)
    assert not res.passed
    assert "SPY" in res.failed_assets
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_data/test_crosssource.py -v`
Expected: FAIL。

- [ ] **Step 3: 實作 `quantcore/data/crosssource.py`**

```python
"""跨源交叉驗證（規格 §4.5）。比對日報酬（非價格水準）。

同一資產 window_days 交易日窗內差異 >= window_max_hits 筆 → 快照建立失敗。
門檻由呼叫端自 config.data_quality 傳入。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class CrossSourceResult:
    passed: bool
    report: list[dict] = field(default_factory=list)     # 所有超門檻的差異
    failed_assets: list[str] = field(default_factory=list)


def _returns(prices: pd.DataFrame) -> pd.DataFrame:
    df = prices.sort_values(["ticker", "date"]).copy()
    df["ret"] = df.groupby("ticker")["adj_close"].pct_change()
    return df[["date", "ticker", "ret"]]


def cross_validate(
    primary: pd.DataFrame,
    validation: pd.DataFrame,
    *,
    discrepancy_bps: float,
    window_days: int,
    window_max_hits: int,
) -> CrossSourceResult:
    rp = _returns(primary).rename(columns={"ret": "ret_p"})
    rv = _returns(validation).rename(columns={"ret": "ret_v"})
    merged = rp.merge(rv, on=["date", "ticker"], how="inner").dropna(
        subset=["ret_p", "ret_v"]
    )
    thresh = discrepancy_bps / 1e4
    merged["diff"] = (merged["ret_p"] - merged["ret_v"]).abs()
    flagged = merged[merged["diff"] > thresh].copy()

    report = [
        {"ticker": r["ticker"], "date": str(r["date"].date()),
         "ret_p": r["ret_p"], "ret_v": r["ret_v"], "diff": r["diff"]}
        for _, r in flagged.sort_values(["ticker", "date"]).iterrows()
    ]

    failed = []
    for ticker, g in flagged.sort_values("date").groupby("ticker"):
        dates = g["date"].reset_index(drop=True)
        # 任一 window_days 日窗內達到 window_max_hits 筆即失敗
        for i in range(len(dates)):
            window_hi = dates[i] + pd.Timedelta(days=window_days)
            hits = ((dates >= dates[i]) & (dates < window_hi)).sum()
            if hits >= window_max_hits:
                failed.append(ticker)
                break

    return CrossSourceResult(passed=not failed, report=report,
                             failed_assets=sorted(set(failed)))
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_data/test_crosssource.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: commit**

```bash
uv run ruff check quantcore/data/crosssource.py tests/test_data/test_crosssource.py
uv run black quantcore/data/crosssource.py tests/test_data/test_crosssource.py
git add quantcore/data/crosssource.py tests/test_data/test_crosssource.py
git commit -m "feat(data): §4.5 跨源交叉驗證（v1 兩源，30 日窗裁決）"
```

---

## Task 11: 快照組裝與 CLI（`snapshot.py`）

**Files:**
- Create: `quantcore/data/snapshot.py`
- Test: `tests/test_data/test_snapshot.py`

用 fake providers 離線測試整條組裝流程與 hash 決定性。

- [ ] **Step 1: 寫失敗測試 `tests/test_data/test_snapshot.py`**

```python
"""快照組裝：決定性 hash、唯讀、MANIFEST、載入往返（全離線，用 fake providers）。"""

import numpy as np
import pandas as pd
import pytest

from quantcore.config import load_config
from quantcore.data.snapshot import create_snapshot, load_snapshot
from quantcore.config.schema import QuantConfig

CONFIG_YAML = "quantcore/config/default.yaml"


def _tidy(ticker, dates, adj):
    return pd.DataFrame(
        {"date": pd.to_datetime(dates), "ticker": ticker,
         "close": adj, "adj_close": adj, "volume": [1e6] * len(dates)}
    )


class _FakePrimary:
    def __init__(self, menu, dates):
        self._menu, self._dates = menu, dates

    def fetch_prices(self, tickers, start, end):
        adj = list(100 + np.arange(len(self._dates)) * 0.1)
        return pd.concat([_tidy(t, self._dates, adj) for t in tickers],
                         ignore_index=True)

    def fetch_metadata(self, tickers):
        return {t: {"inception_date": "2000-01-03", "name": t} for t in tickers}

    def fetch_series(self, series_id, start, end):
        raise NotImplementedError

    def fetch_dividends(self, ticker, start, end):
        return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"),
                             "dividend": pd.Series(dtype="float64")})


class _FakeValidation(_FakePrimary):
    pass


class _FakeRates:
    def __init__(self, dates):
        self._dates = dates

    def fetch_series(self, series_id, start, end):
        return pd.Series([1.5] * len(self._dates),
                         index=pd.to_datetime(self._dates), name=series_id)


def _small_config(tmp_path) -> QuantConfig:
    cfg = load_config(CONFIG_YAML)
    small = cfg.model_copy(deep=True)
    small.universe.menu = ["SPY", "QQQ"]
    small.signal.top_k = 2
    return small


def _sessions():
    import exchange_calendars as xcals
    cal = xcals.get_calendar("XNYS")
    s = cal.sessions_in_range(pd.Timestamp("2020-01-02"),
                              pd.Timestamp("2020-02-14"))
    return pd.DatetimeIndex(s).tz_localize(None).normalize()


def test_snapshot_deterministic_hash(tmp_path):
    cfg = _small_config(tmp_path)
    dates = _sessions()
    def build():
        return create_snapshot(
            cfg,
            primary=_FakePrimary(cfg.universe.menu, dates),
            validation=_FakeValidation(cfg.universe.menu, dates),
            rates=_FakeRates(dates),
            out_root=tmp_path / "snapshots",
            build_date=pd.Timestamp("2026-07-13"),
        )
    d1 = build()
    d2 = build()
    assert d1.name == d2.name  # 同資料同日 → 同 hash → 同目錄名


def test_snapshot_files_and_load(tmp_path):
    cfg = _small_config(tmp_path)
    dates = _sessions()
    d = create_snapshot(
        cfg,
        primary=_FakePrimary(cfg.universe.menu, dates),
        validation=_FakeValidation(cfg.universe.menu, dates),
        rates=_FakeRates(dates),
        out_root=tmp_path / "snapshots",
        build_date=pd.Timestamp("2026-07-13"),
    )
    for fn in ("prices.parquet", "rates.parquet", "metadata.json", "MANIFEST.json"):
        assert (d / fn).exists()
    snap = load_snapshot(d)
    assert set(snap["prices"]["ticker"].unique()) == {"SPY", "QQQ"}
    # MANIFEST 的 content hash 與重算一致（唯讀完整性）
    assert snap["manifest"]["content_hashes"]["prices.parquet"]


def test_snapshot_fails_on_calendar_violation(tmp_path):
    cfg = _small_config(tmp_path)
    bad_dates = pd.DatetimeIndex([pd.Timestamp("2020-01-01")])  # 元旦非交易日
    with pytest.raises(ValueError, match="驗證失敗|calendar"):
        create_snapshot(
            cfg,
            primary=_FakePrimary(cfg.universe.menu, bad_dates),
            validation=_FakeValidation(cfg.universe.menu, bad_dates),
            rates=_FakeRates(bad_dates),
            out_root=tmp_path / "snapshots",
            build_date=pd.Timestamp("2026-07-13"),
        )
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_data/test_snapshot.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 實作 `quantcore/data/snapshot.py`**

```python
"""不可變快照的建立/載入/hash（規格 §4.2）+ CLI。

回測永不直連網路；只有本模組的 create 連網。建立流程：
抓取 → §4.3 驗證 → §4.5 跨源 → 全過才寫檔（canonical hash）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quantcore.config import QuantConfig, load_config
from quantcore.data import validation as v
from quantcore.data.calendar import NyseCalendar
from quantcore.data.crosssource import cross_validate
from quantcore.data.hashing import (
    canonical_hash,
    canonicalize,
    combined_hash,
    config_hash,
    snapshot_id,
)
from quantcore.data.provider import PRICE_COLUMNS

_RATES_SERIES = "DTB3"


def _run_validation(prices: pd.DataFrame, dividends: pd.DataFrame,
                    cfg: QuantConfig, calendar: NyseCalendar) -> list:
    dq = cfg.data_quality
    spy = prices[prices["ticker"] == "SPY"]
    results = [
        v.check_total_return(spy, dividends, dq.total_return_tol_bps),
        v.check_extreme_returns(prices, dq.extreme_return),
        v.check_missing_values(prices, dq.max_consecutive_nan),
        v.check_calendar(prices, calendar),
        v.check_monotonic(prices),
    ]
    return results


def create_snapshot(
    cfg: QuantConfig,
    *,
    primary,
    validation,
    rates,
    out_root: Path,
    build_date: pd.Timestamp,
) -> Path:
    """建立快照目錄並回傳其 Path。任一硬性驗證失敗 → raise ValueError。"""
    out_root = Path(out_root)
    menu = cfg.universe.menu
    start, end = cfg.backtest.start, build_date.date()
    calendar = NyseCalendar()

    prices = primary.fetch_prices(menu, start, end)[PRICE_COLUMNS]
    val_prices = validation.fetch_prices(menu, start, end)[PRICE_COLUMNS]
    metadata_raw = primary.fetch_metadata(menu)
    dividends = pd.concat(
        [primary.fetch_dividends(t, start, end) for t in menu], ignore_index=True
    ) if menu else pd.DataFrame({"date": [], "dividend": []})
    rates_series = rates.fetch_series(_RATES_SERIES, start, end)

    # §4.3 驗證
    results = _run_validation(prices, dividends, cfg, calendar)
    hard_failures = [r for r in results if r.hard_fail and not r.passed]
    if hard_failures:
        names = ", ".join(r.name for r in hard_failures)
        raise ValueError(f"資料驗證失敗（§4.3）：{names}")

    # §4.5 跨源
    dq = cfg.data_quality
    xs = cross_validate(prices, val_prices,
                        discrepancy_bps=dq.discrepancy_bps,
                        window_days=dq.window_days,
                        window_max_hits=dq.window_max_hits)
    if not xs.passed:
        raise ValueError(
            f"跨源驗證失敗（§4.5），需人工裁決：{xs.failed_assets}"
        )

    # canonical 化 + hash
    prices_c = canonicalize(prices, ["ticker", "date"])
    rates_df = canonicalize(
        pd.DataFrame({"date": pd.to_datetime(rates_series.index),
                      _RATES_SERIES: rates_series.to_numpy(dtype="float64")}),
        ["date"],
    )
    metadata = {"tickers": metadata_raw, "overrides": [],
                "sources": {"primary": "yfinance", "validation": ["tiingo"]}}
    meta_bytes = json.dumps(metadata, sort_keys=True,
                            ensure_ascii=False).encode("utf-8")

    ph = canonical_hash(prices_c)
    rh = canonical_hash(rates_df)
    import hashlib
    mh = hashlib.sha256(meta_bytes).hexdigest()
    ch = config_hash(cfg.model_dump(mode="json"))
    disc_hash = combined_hash([r["ticker"] + r["date"] for r in xs.report]) \
        if xs.report else None

    combined = combined_hash([ch, ph, rh, mh])
    sid = snapshot_id(build_date, combined)
    out_dir = out_root / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    prices_c.to_parquet(out_dir / "prices.parquet", index=False)
    rates_df.to_parquet(out_dir / "rates.parquet", index=False)
    (out_dir / "metadata.json").write_bytes(meta_bytes)

    manifest = {
        "snapshot_id": sid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config_hash": ch,
        "content_hashes": {"prices.parquet": ph, "rates.parquet": rh,
                           "metadata.json": mh},
        "discrepancy_report_hash": disc_hash,
        "discrepancy_report": xs.report,
        "providers": {"primary": "yfinance", "validation": ["tiingo"]},
        "quantcore_version": "0.1.0",
    }
    (out_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out_dir


def load_snapshot(snapshot_dir: str | Path) -> dict:
    """載入快照並驗證 content hash（唯讀完整性）。"""
    d = Path(snapshot_dir)
    manifest = json.loads((d / "MANIFEST.json").read_text(encoding="utf-8"))
    prices = pd.read_parquet(d / "prices.parquet")
    rates = pd.read_parquet(d / "rates.parquet")
    metadata = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    # 完整性檢查
    if canonical_hash(prices) != manifest["content_hashes"]["prices.parquet"]:
        raise ValueError(f"快照 prices.parquet hash 不符：{d}")
    return {"prices": prices, "rates": rates, "metadata": metadata,
            "manifest": manifest}


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m quantcore.data.snapshot")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="建立不可變快照")
    create.add_argument("--config", required=True)
    args = parser.parse_args(argv)

    if args.command == "create":
        from quantcore.data.providers.fred_adapter import FredAdapter
        from quantcore.data.providers.tiingo_adapter import TiingoAdapter
        from quantcore.data.providers.yfinance_adapter import YFinanceAdapter

        cfg = load_config(args.config)
        out = create_snapshot(
            cfg,
            primary=YFinanceAdapter(),
            validation=TiingoAdapter(),
            rates=FredAdapter(),
            out_root=Path("snapshots"),
            build_date=pd.Timestamp.now().normalize(),
        )
        print(f"快照已建立：{out}")
        print(f"請將 default.yaml 的 snapshot: 欄位填為 {out.as_posix()}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_data/test_snapshot.py -v`
Expected: PASS（3 passed）。若 parquet 往返使 dtype 微變導致 `load_snapshot` hash 不符，於 `create_snapshot` 寫檔前把 `prices_c`/`rates_df` 的 dtype 明確固定（date→datetime64[ns]、數值→float64），並在 `canonicalize` 後、寫檔前重算 hash（確保寫入磁碟的即為被 hash 的物件）。

- [ ] **Step 5: 全部 test_data 綠 + commit**

```bash
uv run pytest tests/test_data/ -v
uv run ruff check quantcore/data/snapshot.py tests/test_data/test_snapshot.py
uv run black quantcore/data/snapshot.py tests/test_data/test_snapshot.py
git add quantcore/data/snapshot.py tests/test_data/test_snapshot.py
git commit -m "feat(data): 快照組裝、決定性 hash、載入完整性 + snapshot create CLI"
```

---

## Task 12: 真實快照建立（端到端 AC 驗收，需網路）

**此 Task 需與使用者一起執行**（設計決策：先離線全綠，再一起跑真實快照）。

**Files:**
- Modify: `quantcore/config/default.yaml`（填入實際 snapshot 目錄）
- Modify: `PROGRESS.md`（標記 Phase 1 完成）
- 產出：`snapshots/<id>/`（parquet gitignore；`MANIFEST.json` 進 git）

- [ ] **Step 1: 確認 `.env` 已設定 Tiingo key**

Run: `uv run python -c "from quantcore.data.secrets import get_secret; print('key ok' if get_secret('TIINGO_API_KEY') else 'missing')"`
Expected: `key ok`（若失敗，在專案根 `.env` 填入 `TIINGO_API_KEY=…`）。

- [ ] **Step 2: 建立真實快照**

Run: `uv run python -m quantcore.data.snapshot create --config quantcore/config/default.yaml`
Expected: 印出「快照已建立：snapshots/YYYY-MM-DD_xxxxxx」。

**若跨源驗證失敗**（§4.5 觸發人工裁決）：檢視印出的 `failed_assets` 與 `MANIFEST.json` 的 `discrepancy_report`，逐檔判斷是哪一源的拆分/配息調整錯誤，把裁決結果寫入 `metadata.json` 的 `overrides`（此步驟與使用者討論後再進行；本 plan 不預設自動放行）。

- [ ] **Step 3: 驗證同日重建 hash 相同（AC-4）**

Run: 再次執行 Step 2 的指令。
Expected: 印出相同的快照目錄名（同一 `snapshots/YYYY-MM-DD_xxxxxx`）。

- [ ] **Step 4: 把快照目錄填入 config**

把 `quantcore/config/default.yaml` 的 `snapshot:` 由 `snapshots/PLACEHOLDER` 改為 Step 2 印出的實際目錄。

- [ ] **Step 5: 全測試綠 + 提交**

```bash
uv run pytest -q
git add quantcore/config/default.yaml "snapshots/<id>/MANIFEST.json"
git commit -m "chore(phase1): 建立首份快照並綁定 config（Phase 1 AC 達成）"
```

（注意：`.gitignore` 已排除 `snapshots/*`，需 `git add -f` 或確認 `!snapshots/.gitkeep` 規則；MANIFEST 須進版控——用 `git add -f snapshots/<id>/MANIFEST.json`。）

- [ ] **Step 6: 更新 `PROGRESS.md`**

把 Phase 1 各任務與 AC 的 `[ ]` 改為 `[x]`，狀態 `⬜` 改 `✅`，並在「變更紀錄」加一行：`2026-07-13：Phase 1 資料層完成（provider/adapters/日曆/驗證/跨源/快照 CLI，test_data 全綠，首份快照建立、AC 全達成）。`

```bash
git add PROGRESS.md
git commit -m "docs(phase1): 標記 Phase 1 完成 — AC 全達成"
```

---

## Self-Review 檢核（已於撰寫後執行）

- **Spec 覆蓋**：§4.1 provider→Task 3；§4.2 快照/hash→Task 2+11；§4.3 五項→Task 9；§4.4 FRED→Task 7；§4.5 跨源→Task 10；NYSE 日曆→Task 4；四 adapters→Task 5–8；CLI→Task 11；AC 端到端→Task 12；config data_quality→Task 1。✅
- **Placeholder**：無 TBD；每個程式步驟均含完整程式碼。
- **型別一致**：`PRICE_COLUMNS`、`empty_prices`、`ValidationResult`、`CrossSourceResult`、`canonical_hash`/`canonicalize`/`config_hash`/`combined_hash`/`snapshot_id`、`create_snapshot`/`load_snapshot` 跨 Task 命名一致。
- **已知風險**：parquet 往返 dtype 一致性（Task 11 Step 4 已給對策）；yfinance metadata 欄位名可能隨版本變動（Task 12 端到端修正）。
