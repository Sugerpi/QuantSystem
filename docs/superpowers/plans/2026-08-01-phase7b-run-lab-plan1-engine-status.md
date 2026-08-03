# Phase 7b Run Lab — 計畫 1：引擎端狀態管線 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development（建議）或 executing-plans。Steps 用 `- [ ]` checkbox。用量上限期間可由控制者 inline 執行；TDD 不變。

**Goal:** 讓引擎 CLI 在提供 `--status-file` 時，於各階段/每支策略邊界原子寫 `status.json`，供 Run Lab（計畫 2）監看；並加 `--validate-only` 快檢 config。既有 CLI 預設行為完全不變。

**Architecture:** 新增 `experiments/jobstatus.py`（原子 merge 寫 status.json，純檔案操作）；`run_experiment` 加 `on_progress` callback（預設 None、向後相容）；`runner._cli` 加 `--status-file`/`--job-id`/`--validate-only`，用 try/except 把階段與 done/failed 寫入 status.json。

**Tech Stack:** Python 3.11、stdlib（json/os/datetime）、pytest、ruff。無新依賴（psutil/python-multipart 屬計畫 2）。

設計文件：[2026-08-01-phase7b-run-lab-design.md](../specs/2026-08-01-phase7b-run-lab-design.md)（§2 status.json 合約、§3 引擎改動）。

分支：`feature/phase7a-dashboard`（延續）。

---

## 檔案結構

```
quantcore/experiments/jobstatus.py       建立（write_status 原子 merge 寫）
quantcore/experiments/runner.py          修改（run_experiment 加 on_progress；_cli 加三旗標 + 狀態寫入）
tests/test_experiments/test_jobstatus.py 建立
tests/test_experiments/test_runner_status.py 建立
```

status.json 由引擎子行程權威擁有；stage 值：`validating` → `loading_snapshot` → `running`（含 strategy_index/total/current_strategy）→ `done`；失敗為 `error`。（設計 §3.3 的 writing_artifacts 階段簡化省略：run_experiment 回傳即視為完成。）

---

### Task 1: `experiments/jobstatus.py` — 原子 merge 寫 status.json

**Files:**
- Create: `quantcore/experiments/jobstatus.py`
- Test: `tests/test_experiments/test_jobstatus.py`

- [ ] **Step 1: 寫失敗測試** — 建 `tests/test_experiments/test_jobstatus.py`：

```python
import json

from quantcore.experiments.jobstatus import write_status


def test_write_status_merges_and_updates_heartbeat(tmp_path):
    sf = tmp_path / "status.json"
    write_status(sf, job_id="j1", state="queued")
    write_status(sf, state="running", pid=123)  # merge，不得丟失 job_id
    d = json.loads(sf.read_text(encoding="utf-8"))
    assert d["job_id"] == "j1"
    assert d["state"] == "running"
    assert d["pid"] == 123
    assert "heartbeat_at" in d


def test_write_status_is_atomic_no_tmp_left(tmp_path):
    sf = tmp_path / "status.json"
    write_status(sf, state="queued")
    assert sf.exists()
    assert not (tmp_path / "status.json.tmp").exists()
```

- [ ] **Step 2: RED** — `uv run pytest tests/test_experiments/test_jobstatus.py -q` → FAIL（模組不存在）。

- [ ] **Step 3: 實作** — 建 `quantcore/experiments/jobstatus.py`：

```python
"""Run Lab job 狀態的原子寫入（規格 §2/§3.1）。純檔案操作、無引擎依賴。

status.json 由回測子行程權威擁有：每次 merge 傳入欄位 + 更新 heartbeat_at，
以 temp + os.replace 原子寫回（UI 讀到不會是半寫檔）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def write_status(status_file: str | Path, **fields) -> None:
    """讀現有 status.json（若有）→ merge fields → 更新 heartbeat_at → 原子寫回。"""
    path = Path(status_file)
    current: dict = {}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    current.update(fields)
    current["heartbeat_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
```

- [ ] **Step 4: GREEN** — `uv run pytest tests/test_experiments/test_jobstatus.py -q` → PASS（2 項）。

- [ ] **Step 5: ruff** — `uv run ruff check quantcore/experiments/jobstatus.py tests/test_experiments/test_jobstatus.py` + `ruff format --check`；必要時 `ruff format`。

- [ ] **Step 6: Commit**

```bash
git add quantcore/experiments/jobstatus.py tests/test_experiments/test_jobstatus.py
git commit -m "feat(phase7b): jobstatus.write_status—原子 merge 寫 status.json"
```

---

### Task 2: `run_experiment` 加 `on_progress` callback

**Files:**
- Modify: `quantcore/experiments/runner.py`（`run_experiment` 簽名 + 策略迴圈）
- Test: `tests/test_experiments/test_runner_status.py`

- [ ] **Step 1: 寫失敗測試** — 建 `tests/test_experiments/test_runner_status.py`：

```python
import numpy as np
import pandas as pd

from quantcore.config import load_config
from quantcore.experiments.runner import run_experiment
from tests.fixtures.synthetic import make_dates, make_snapshot


def _synthetic():
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["SPY", "QQQ", "IWM"]
    cfg.universe.min_history_days = 5
    cfg.signal.top_k = 2
    cfg.signal.momentum_lookback = 5
    cfg.signal.momentum_skip = 1
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    cfg.risk.vol_model = "ewma"
    cfg.risk.corr_model = "ewma"
    dates = make_dates(80)
    rng = np.random.default_rng(3)
    snap = make_snapshot(
        {
            "SPY": list(100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, 80))),
            "QQQ": list(200.0 * np.cumprod(1 + rng.normal(0.0005, 0.012, 80))),
            "IWM": list(150.0 * np.cumprod(1 + rng.normal(0.0005, 0.013, 80))),
        },
        dates,
    )
    return cfg, snap


def test_run_experiment_calls_on_progress_once_per_strategy(tmp_path):
    cfg, snap = _synthetic()
    calls = []
    run_experiment(
        cfg=cfg,
        snapshot=snap,
        out_root=tmp_path,
        label="t",
        strategy_ids=["bh_spy", "full"],
        now=pd.Timestamp("2026-08-01T10:00:00"),
        on_progress=lambda i, n, sid: calls.append((i, n, sid)),
    )
    assert calls == [(1, 2, "bh_spy"), (2, 2, "full")]


def test_run_experiment_without_on_progress_unchanged(tmp_path):
    cfg, snap = _synthetic()
    run_dir = run_experiment(
        cfg=cfg,
        snapshot=snap,
        out_root=tmp_path,
        label="t",
        strategy_ids=["bh_spy"],
        now=pd.Timestamp("2026-08-01T10:00:00"),
    )
    assert (run_dir / "nav.parquet").exists()
```

- [ ] **Step 2: RED** — `uv run pytest tests/test_experiments/test_runner_status.py -q` → FAIL（`on_progress` 非 run_experiment 參數 → TypeError）。

- [ ] **Step 3: 實作** — 改 `quantcore/experiments/runner.py`：

在檔頭 import 區加（`from collections.abc import Callable`）：

```python
from collections.abc import Callable
```

把 `run_experiment` 簽名（約 runner.py:132-139）改為新增 `on_progress` 參數：

```python
def run_experiment(
    cfg: QuantConfig,
    snapshot: dict,
    out_root: str | Path,
    label: str,
    strategy_ids: list[str],
    now: pd.Timestamp | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> Path:
```

把策略迴圈（約 runner.py:154）`for s in strategies:` 改為附進度回呼：

```python
    for i, s in enumerate(strategies, start=1):
        if on_progress is not None:
            on_progress(i, len(strategies), s.strategy_id)
        nav_df, w_df, d_df, t_df = run_strategy(snapshot, clock, s, cfg)
```

（迴圈其餘內容不變。）

- [ ] **Step 4: GREEN** — `uv run pytest tests/test_experiments/test_runner_status.py -q` → PASS（2 項）。

- [ ] **Step 5: 回歸** — `uv run pytest tests/test_experiments -q`（既有 runner/tracking 測試不受影響，on_progress 預設 None）。

- [ ] **Step 6: ruff + Commit**

```bash
uv run ruff check quantcore/experiments/runner.py tests/test_experiments/test_runner_status.py
git add quantcore/experiments/runner.py tests/test_experiments/test_runner_status.py
git commit -m "feat(phase7b): run_experiment 加 on_progress（每策略回呼，預設 None 向後相容）"
```

---

### Task 3: `runner._cli` 加 `--status-file` / `--job-id` / `--validate-only`

**Files:**
- Modify: `quantcore/experiments/runner.py`（`_cli`）
- Test: `tests/test_experiments/test_runner_status.py`（追加）

- [ ] **Step 1: 寫失敗測試**（追加到 `test_runner_status.py`）：

```python
import json
from pathlib import Path

import yaml

from quantcore.experiments.runner import _cli


def test_cli_validate_only_accepts_default_config():
    assert _cli(["--config", "quantcore/config/default.yaml", "--validate-only"]) == 0


def test_cli_validate_only_rejects_bad_config(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("universe:\n  menu: 123\n", encoding="utf-8")  # 缺欄位/型別錯
    assert _cli(["--config", str(bad), "--validate-only"]) == 1


def test_cli_writes_failed_status_on_missing_snapshot(tmp_path):
    base = yaml.safe_load(Path("quantcore/config/default.yaml").read_text(encoding="utf-8"))
    base["snapshot"] = str(tmp_path / "does_not_exist")  # 合法 config、但快照不在
    cfgp = tmp_path / "c.yaml"
    cfgp.write_text(yaml.safe_dump(base), encoding="utf-8")
    sf = tmp_path / "status.json"
    rc = _cli(
        [
            "--config", str(cfgp),
            "--out-root", str(tmp_path / "runs"),
            "--strategies", "bh_spy",
            "--status-file", str(sf),
            "--job-id", "j1",
        ]
    )
    assert rc == 1
    d = json.loads(sf.read_text(encoding="utf-8"))
    assert d["state"] == "failed"
    assert d["stage"] == "error"
    assert d["error"]
    assert d["job_id"] == "j1"
```

- [ ] **Step 2: RED** — `uv run pytest tests/test_experiments/test_runner_status.py -q` → FAIL（未知旗標 `--validate-only` → argparse SystemExit / 或無狀態寫入）。

- [ ] **Step 3: 實作** — 改 `quantcore/experiments/runner.py` 的 `_cli`。先在檔頭 import 區加 `import os`（若無）。將 `_cli` 全函式（約 runner.py:214-240）替換為：

```python
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
    p.add_argument("--status-file", default=None, help="Run Lab 狀態檔（提供則寫 status.json）")
    p.add_argument("--job-id", default=None, help="Run Lab job id（寫入 status.json）")
    p.add_argument(
        "--validate-only", action="store_true", help="只驗證 config（pydantic），不跑回測"
    )
    args = p.parse_args(argv)

    if args.validate_only:
        try:
            load_config(args.config)
        except Exception as e:  # noqa: BLE001 —— CLI 邊界回報所有驗證錯
            print(f"config 無效：{type(e).__name__}: {e}")
            return 1
        print("OK")
        return 0

    label = args.label or Path(args.config).stem
    strategy_ids = [s.strip() for s in args.strategies.split(",") if s.strip()]

    if args.status_file is None:
        cfg = load_config(args.config)
        snapshot = load_snapshot(cfg.snapshot)
        run_dir = run_experiment(
            cfg=cfg,
            snapshot=snapshot,
            out_root=args.out_root,
            label=label,
            strategy_ids=strategy_ids,
        )
        print(f"run 已完成：{run_dir}")
        return 0

    from quantcore.experiments.jobstatus import write_status

    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    sf = args.status_file
    try:
        write_status(
            sf, job_id=args.job_id, state="running", stage="validating",
            pid=os.getpid(), started_at=_now(),
        )
        cfg = load_config(args.config)
        write_status(sf, stage="loading_snapshot")
        snapshot = load_snapshot(cfg.snapshot)
        run_dir = run_experiment(
            cfg=cfg,
            snapshot=snapshot,
            out_root=args.out_root,
            label=label,
            strategy_ids=strategy_ids,
            on_progress=lambda i, n, sid: write_status(
                sf, stage="running", strategy_index=i, strategy_total=n, current_strategy=sid
            ),
        )
        write_status(sf, state="done", stage="done", finished_at=_now(), run_dir=str(run_dir))
        print(f"run 已完成：{run_dir}")
        return 0
    except Exception as e:  # noqa: BLE001 —— 子行程邊界：任何失敗都要落 status
        write_status(
            sf, state="failed", stage="error", finished_at=_now(),
            error=f"{type(e).__name__}: {e}"[:2000],
        )
        print(f"回測失敗：{type(e).__name__}: {e}", file=sys.stderr)
        return 1
```

- [ ] **Step 4: GREEN** — `uv run pytest tests/test_experiments/test_runner_status.py -q` → PASS（全部）。

- [ ] **Step 5: 回歸 + ruff** — `uv run pytest tests/test_experiments -q`（既有 CLI 無 `--status-file` 路徑不變）；`uv run ruff check quantcore/experiments tests/test_experiments` + `ruff format --check`；必要時 `ruff format`。

- [ ] **Step 6: Commit**

```bash
git add quantcore/experiments/runner.py tests/test_experiments/test_runner_status.py
git commit -m "feat(phase7b): runner CLI 加 --status-file/--job-id/--validate-only + 階段狀態寫入"
```

---

## Self-Review 對照

- **Spec 覆蓋（§3 引擎改動）**：`jobstatus.write_status` 原子 merge（Task 1）✓；`run_experiment` on_progress 每策略（Task 2）✓；`_cli` `--status-file`/`--job-id` 階段狀態（validating/loading_snapshot/running/done/error）+ `--validate-only`（Task 3）✓。
- **向後相容**：`on_progress` 預設 None、`--status-file` 未提供走原路徑——既有 ablation/conftest/CLI 呼叫不受影響（Task 2 Step 5、Task 3 Step 5 回歸驗證）。
- **邊界**：`jobstatus.py` 純檔案操作、無跨層依賴；不動引擎核心邏輯（只在策略迴圈前加一個回呼、CLI 加狀態旁路），INV-1~6 不受影響。
- **CI 安全**：on_progress 用記憶體合成快照測；failed 狀態用「不存在的快照路徑」測（不需真快照）。**happy-path 逐階段狀態（running→done 落實體 status.json）延到計畫 2 的端到端 AC② 測試**（屆時持久化合成快照 + 經 UI 提交跑真 CLI）——此為刻意取捨，避免計畫 1 引入快照存檔設定。
- **無 placeholder**：各 step 附完整程式碼與確切指令。
- **型別一致**：`write_status(status_file, **fields)`、`run_experiment(..., on_progress: Callable[[int,int,str],None]|None)`、`on_progress(i, n, sid)`、CLI 旗標 `--status-file/--job-id/--validate-only` 跨 task 一致。
- **延後**：`jobs.py`（store/排程/detached spawn/reconcile）、Run Lab 頁面、psutil/python-multipart、背景心跳執行緒、端到端 AC②③ → 計畫 2。
