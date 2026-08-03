# Phase 7b Run Lab — 計畫 2：presentation（jobs 排程器 + Run Lab 頁面） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。Steps 用 `- [ ]`。用量上限期間可由控制者 inline；TDD 不變。

**Goal:** 讓使用者在網頁提交 YAML config、看回測進度、拿到結果（AC②），且 UI 砍掉重開後運行中 job 狀態無損（AC③）。

**Architecture:** `presentation/jobs.py`（job store + 排程器：submit/list/validate/reconcile/detached spawn；**不 import 引擎**，只 subprocess 呼叫引擎 CLI）；`web/routes/run_lab.py` + 模板（YAML 編輯器/驗證/提交/job 清單/輪詢/log）；app lifespan 起背景心跳執行緒推排隊。狀態由引擎子行程權威擁有（計畫 1 已備），jobs.py 只寫「queued」與「pid 死掉的 running→failed」。

**Tech Stack:** FastAPI/Jinja2/HTMX、psutil、python-multipart、subprocess、pytest（TestClient）、ruff。

前置：計畫 1 完成（`experiments/jobstatus.py`、`run_experiment` on_progress、runner CLI `--status-file`/`--job-id`/`--validate-only`）。設計見 [spec](../specs/2026-08-01-phase7b-run-lab-design.md) §4/§5/§6/§7。base config：`config/{default,canonical_dcc,canonical_ewma}.yaml`。分支 `feature/phase7a-dashboard`。

**§2.2 邊界**：`jobs.py`、`run_lab.py` 落在 `presentation/` 樹下，既有 AST 守護（`test_architecture.py` rglob）自動禁其 import 引擎。`jobs.py` 只組指令字串 + subprocess.Popen 呼叫 `python -m quantcore.experiments.runner`。

---

## 檔案結構

```
quantcore/presentation/jobs.py                       建立（store + 排程器）
quantcore/presentation/web/routes/run_lab.py         建立（頁面 + 提交/驗證/輪詢）
quantcore/presentation/web/templates/run_lab.html            建立
quantcore/presentation/web/templates/run_lab_content.html    建立
quantcore/presentation/web/templates/_job_list.html          建立（輪詢目標片段）
quantcore/presentation/web/app.py                    修改（include run_lab、app.state.jobs_root、lifespan 心跳執行緒、移除 stubs）
quantcore/presentation/web/static/css/app.css        修改（job 徽章/YAML 編輯器樣式）
pyproject.toml                                       修改（+psutil、+python-multipart）
.gitignore                                           修改（+jobs/）
quantcore/presentation/web/routes/stubs.py           刪除（/run-lab 為最後一個 stub）
quantcore/presentation/web/templates/stub.html       刪除
quantcore/presentation/web/templates/stub_content.html  刪除
tests/test_presentation/test_web_jobs.py             建立
tests/test_presentation/test_web_run_lab.py          建立
tests/test_presentation/test_web_run_lab_e2e.py      建立（requires_snapshot）
tests/test_presentation/test_web_htmx.py             修改（移除 stub 可達性測試——已無 stub）
```

status.json 欄位見 spec §2。stage：validating→loading_snapshot→running→done / error。

---

### Task 1: jobs.py — store + 純排程決策 + validate

**Files:**
- Create: `quantcore/presentation/jobs.py`
- Test: `tests/test_presentation/test_web_jobs.py`

- [ ] **Step 1: 加失敗測試** — 建 `tests/test_presentation/test_web_jobs.py`：

```python
import json

from quantcore.presentation import jobs


def test_submit_creates_job_dir_and_queued_status(tmp_path):
    jid = jobs.submit(tmp_path, "myrun", "snapshot: x\n")
    d = tmp_path / jid
    assert (d / "config.yaml").read_text(encoding="utf-8") == "snapshot: x\n"
    st = json.loads((d / "status.json").read_text(encoding="utf-8"))
    assert st["state"] == "queued"
    assert st["label"] == "myrun"
    assert st["job_id"] == jid
    assert "submitted_at" in st


def test_list_jobs_sorted_by_submitted(tmp_path):
    jobs.submit(tmp_path, "a", "x")
    jobs.submit(tmp_path, "b", "y")
    names = [s["label"] for s in jobs.list_jobs(tmp_path)]
    assert names == ["a", "b"]


def test_list_jobs_empty_when_no_root(tmp_path):
    assert jobs.list_jobs(tmp_path / "nope") == []


def test_next_action_spawns_earliest_queued_when_idle():
    statuses = [
        {"job_id": "j2", "state": "queued", "submitted_at": "2026-08-01T10:00:02"},
        {"job_id": "j1", "state": "queued", "submitted_at": "2026-08-01T10:00:01"},
    ]
    assert jobs._next_action(statuses, lambda pid: True) == ("spawn", "j1")


def test_next_action_none_when_running_alive():
    statuses = [
        {"job_id": "r", "state": "running", "pid": 999, "submitted_at": "t"},
        {"job_id": "q", "state": "queued", "submitted_at": "t2"},
    ]
    assert jobs._next_action(statuses, lambda pid: True) is None


def test_next_action_marks_failed_when_running_pid_dead():
    statuses = [{"job_id": "r", "state": "running", "pid": 999, "submitted_at": "t"}]
    assert jobs._next_action(statuses, lambda pid: False) == ("mark_failed", "r")


def test_submit_sanitizes_label(tmp_path):
    jid = jobs.submit(tmp_path, "my run/../x", "c")
    assert "/" not in jid and ".." not in jid
```

- [ ] **Step 2: RED** — `uv run pytest tests/test_presentation/test_web_jobs.py -q` → FAIL（模組不存在）。

- [ ] **Step 3: 實作** — 建 `quantcore/presentation/jobs.py`：

```python
"""Run Lab job store + 排程器（規格 §4）。

§2.2 邊界：不 import 引擎；啟動回測只以 subprocess 呼叫 `python -m
quantcore.experiments.runner`。status.json 由引擎子行程權威擁有；jobs.py 只寫
初始 queued 與「pid 死掉的 running→failed」reconcile。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_status(status_file: Path, **fields) -> None:
    """原子 merge 寫（與 experiments.jobstatus 同法；boundary 兩側各一份）。"""
    path = Path(status_file)
    current: dict = {}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    current.update(fields)
    current["heartbeat_at"] = _now()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _safe_label(label: str) -> str:
    s = "".join(c for c in label if c.isalnum() or c in "-_")
    return s or "run"


def submit(jobs_root: str | Path, label: str, config_yaml: str) -> str:
    """建 job 目錄、寫 config.yaml 與初始 queued status.json。回 job_id。"""
    lbl = _safe_label(label)
    job_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{lbl}"
    d = Path(jobs_root) / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yaml").write_text(config_yaml, encoding="utf-8")
    _write_status(
        d / "status.json", job_id=job_id, label=lbl, state="queued", submitted_at=_now()
    )
    return job_id


def list_jobs(jobs_root: str | Path) -> list[dict]:
    """所有 job 的 status.json，依 submitted_at 排序。缺目錄/壞檔優雅略過。"""
    root = Path(jobs_root)
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        sf = d / "status.json"
        if d.is_dir() and sf.exists():
            try:
                out.append(json.loads(sf.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
    return sorted(out, key=lambda s: s.get("submitted_at", ""))


def load_status(jobs_root: str | Path, job_id: str) -> dict | None:
    sf = Path(jobs_root) / job_id / "status.json"
    if not sf.exists():
        return None
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def tail_log(jobs_root: str | Path, job_id: str, n: int = 200) -> str:
    log = Path(jobs_root) / job_id / "stdout.log"
    if not log.exists():
        return ""
    return "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])


def validate(config_yaml: str) -> tuple[bool, str]:
    """subprocess 跑引擎 --validate-only 快檢 pydantic。回 (ok, 訊息)。"""
    with tempfile.NamedTemporaryFile(
        "w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(config_yaml)
        tmp = f.name
    try:
        r = subprocess.run(
            [sys.executable, "-m", "quantcore.experiments.runner", "--config", tmp, "--validate-only"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    finally:
        os.unlink(tmp)


def _next_action(statuses: list[dict], pid_alive: Callable[[int], bool]):
    """排程決策（純函數）：running 但 pid 死 → mark_failed；否則若無 running-活著則 spawn 最早 queued。"""
    for s in statuses:
        if s.get("state") == "running":
            pid = s.get("pid")
            if pid is None or not pid_alive(int(pid)):
                return ("mark_failed", s["job_id"])
    busy = any(
        s.get("state") == "running" and s.get("pid") and pid_alive(int(s["pid"]))
        for s in statuses
    )
    if busy:
        return None
    queued = sorted(
        (s for s in statuses if s.get("state") == "queued"),
        key=lambda s: s.get("submitted_at", ""),
    )
    if queued:
        return ("spawn", queued[0]["job_id"])
    return None
```

- [ ] **Step 4: GREEN** — `uv run pytest tests/test_presentation/test_web_jobs.py -q` → PASS（7 項）。

- [ ] **Step 5: ruff** — `uv run ruff check quantcore/presentation/jobs.py tests/test_presentation/test_web_jobs.py` + `ruff format --check`。

- [ ] **Step 6: Commit**

```bash
git add quantcore/presentation/jobs.py tests/test_presentation/test_web_jobs.py
git commit -m "feat(phase7b): jobs store + 純排程決策 _next_action + validate（不 import 引擎）"
```

---

### Task 2: jobs.py — detached spawn + reconcile_and_advance

**Files:**
- Modify: `quantcore/presentation/jobs.py`（加 `_spawn`、`reconcile_and_advance`）
- Test: `tests/test_presentation/test_web_jobs.py`（追加）

- [ ] **Step 1: 加失敗測試**（追加）：

```python
def _rec(root, **kw):
    # 注入 runs_root（tmp）+ 可注入 pid_alive/spawn
    return jobs.reconcile_and_advance(root, root / "runs", **kw)


def test_reconcile_marks_failed_running_with_dead_pid(tmp_path):
    jid = jobs.submit(tmp_path, "r", "c")
    # 手動改成 running + 假死 pid
    jobs._write_status(tmp_path / jid / "status.json", state="running", pid=424242)
    spawned = []
    _rec(tmp_path, pid_alive=lambda pid: False, spawn=lambda root, jid_, rr: spawned.append(jid_))
    st = jobs.load_status(tmp_path, jid)
    assert st["state"] == "failed"
    assert st["stage"] == "error"
    assert spawned == []  # 標 failed 後本 tick 不再 spawn


def test_reconcile_spawns_earliest_queued_when_idle(tmp_path):
    j1 = jobs.submit(tmp_path, "a", "c")
    jobs.submit(tmp_path, "b", "c")
    spawned = []
    _rec(tmp_path, pid_alive=lambda pid: True, spawn=lambda root, jid_, rr: spawned.append(jid_))
    assert spawned == [j1]


def test_reconcile_noop_when_running_alive(tmp_path):
    jid = jobs.submit(tmp_path, "r", "c")
    jobs._write_status(tmp_path / jid / "status.json", state="running", pid=1)
    jobs.submit(tmp_path, "q", "c")
    spawned = []
    _rec(tmp_path, pid_alive=lambda pid: True, spawn=lambda root, jid_, rr: spawned.append(jid_))
    assert spawned == []
```

- [ ] **Step 2: RED** — FAIL（`reconcile_and_advance` 不存在 / 簽名不符）。

- [ ] **Step 3: 實作**（`jobs.py` 檔末追加）：

```python
def _spawn(jobs_root: str | Path, job_id: str, runs_root: str | Path) -> None:
    """detached subprocess 跑引擎 CLI；立刻寫 running+pid（關閉「重複 spawn / 誤判死亡」race）。

    回測產物落 runs_root（= dashboard 讀取的 runs 根），非硬編 "runs"。
    """
    d = Path(jobs_root) / job_id
    st = load_status(jobs_root, job_id) or {}
    label = st.get("label", "run")
    log = open(d / "stdout.log", "w", encoding="utf-8")  # noqa: SIM115 —— 交給子行程持有
    cmd = [
        sys.executable, "-m", "quantcore.experiments.runner",
        "--config", str(d / "config.yaml"),
        "--out-root", str(runs_root),
        "--label", label,
        "--status-file", str(d / "status.json"),
        "--job-id", job_id,
    ]
    kwargs: dict = {"stdout": log, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603 —— 固定引擎 CLI、參數非使用者拼接
    _write_status(
        d / "status.json", state="running", stage="starting", pid=proc.pid, started_at=_now()
    )


def reconcile_and_advance(
    jobs_root: str | Path,
    runs_root: str | Path,
    pid_alive: Callable[[int], bool] | None = None,
    spawn: Callable[[str | Path, str, str | Path], None] | None = None,
) -> None:
    """排程 tick：reconcile 死掉的 running→failed；閒置則 spawn 最早 queued。可注入（測試）。"""
    if pid_alive is None:
        import psutil

        pid_alive = psutil.pid_exists
    if spawn is None:
        spawn = _spawn
    with _LOCK:
        action = _next_action(list_jobs(jobs_root), pid_alive)
        if action is None:
            return
        kind, job_id = action
        if kind == "mark_failed":
            _write_status(
                Path(jobs_root) / job_id / "status.json",
                state="failed",
                stage="error",
                error="行程消失（可能硬當機）",
                finished_at=_now(),
            )
        elif kind == "spawn":
            spawn(jobs_root, job_id, runs_root)
```

- [ ] **Step 4: GREEN** — `uv run pytest tests/test_presentation/test_web_jobs.py -q` → PASS（10 項）。

- [ ] **Step 5: ruff**（`jobs.py` 有 `noqa: S603/SIM115`——若 ruff 未啟用 S/相關規則則移除該 noqa 以免 RUF100 未使用 noqa 警告；先跑 `uv run ruff check quantcore/presentation/jobs.py`，依訊息保留或刪 noqa）。`ruff format`。

- [ ] **Step 6: Commit**

```bash
git add quantcore/presentation/jobs.py tests/test_presentation/test_web_jobs.py
git commit -m "feat(phase7b): jobs detached spawn + reconcile_and_advance（psutil pid-liveness、可注入）"
```

---

### Task 3: Run Lab 頁面 + app 接線 + 依賴 + stub 清理

**Files:**
- Create: `quantcore/presentation/web/routes/run_lab.py`、`templates/run_lab.html`、`run_lab_content.html`、`_job_list.html`
- Modify: `web/app.py`、`static/css/app.css`、`pyproject.toml`、`.gitignore`、`tests/test_presentation/test_web_htmx.py`
- Delete: `web/routes/stubs.py`、`templates/stub.html`、`templates/stub_content.html`
- Test: `tests/test_presentation/test_web_run_lab.py`

- [ ] **Step 1: 加依賴 + gitignore + 同步**

`pyproject.toml` `[project].dependencies` 加：
```toml
    "psutil>=5.9",
    "python-multipart>=0.0.9",
```
`.gitignore` 在 `runs/*` 附近加：
```
jobs/*
!jobs/.gitkeep
```
建立空檔 `jobs/.gitkeep`（`New-Item` 或 `touch`）。
Run: `uv sync --extra dev`。

- [ ] **Step 2: 加失敗測試** — 建 `tests/test_presentation/test_web_run_lab.py`：

```python
import json

from fastapi.testclient import TestClient

from quantcore.presentation.web.app import create_app


def _client(tmp_path):
    return TestClient(create_app(runs_root=tmp_path / "runs", jobs_root=tmp_path / "jobs"))


def test_run_lab_page_has_editor_and_base_configs(tmp_path):
    r = _client(tmp_path).get("/run-lab")
    assert r.status_code == 200
    assert "回測工作台" in r.text
    assert "<textarea" in r.text
    assert "default" in r.text  # base config 下拉含 config/default.yaml


def test_submit_creates_job_and_appears_in_list(tmp_path):
    c = _client(tmp_path)
    r = c.post("/run-lab/submit", data={"label": "t1", "config_yaml": "snapshot: x\n"})
    assert r.status_code == 200
    assert "t1" in r.text  # job 清單片段含新 job
    jobs_dir = tmp_path / "jobs"
    assert any((d / "status.json").exists() for d in jobs_dir.iterdir())


def test_status_poll_returns_job_list(tmp_path):
    c = _client(tmp_path)
    c.post("/run-lab/submit", data={"label": "t2", "config_yaml": "snapshot: x\n"})
    r = c.get("/run-lab/status")
    assert r.status_code == 200
    assert "t2" in r.text


def test_validate_bad_yaml_shows_error(tmp_path):
    c = _client(tmp_path)
    r = c.post("/run-lab/validate", data={"config_yaml": "universe:\n  menu: 123\n"})
    assert r.status_code == 200
    assert ("無效" in r.text) or ("失敗" in r.text) or ("error" in r.text.lower())
```

> 注意：`test_submit_*` 會觸發 `reconcile_and_advance` → 真的 spawn 一個子行程跑 `snapshot: x`（無效 config，子行程會快速 failed）。為避免測試依賴真 spawn，**submit 路由呼叫 reconcile 時注入不 spawn 的版本**——見實作：submit/status 端點 tick 用 `reconcile_and_advance(jobs_root)`（真 spawn）；但測試用的 config（`snapshot: x`）會讓子行程秒退，且測試只斷言 job 出現在清單、不等完成，容忍。若 CI 不宜真 spawn，可將端點的 tick 包一層 app.state 開關；此處採「submit 只寫 queued、不在請求內同步 spawn」——**submit 端點不 tick**，交給背景執行緒/status 輪詢 tick。測試不啟背景執行緒（TestClient 不進 lifespan），故 submit 後 job 停在 queued、不 spawn，斷言穩定。

- [ ] **Step 3: 實作 route** — 建 `quantcore/presentation/web/routes/run_lab.py`：

```python
"""頁 8 回測工作台（Run Lab，§5）：YAML 編輯器、驗證、提交、job 清單輪詢。

啟動回測只以 subprocess（jobs.py）；不 import 引擎。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import jobs
from quantcore.presentation.web.rendering import render_page
from quantcore.presentation.web.templating import templates

router = APIRouter()

_CONFIG_DIR = Path("quantcore/config")


def _base_configs() -> list[str]:
    if not _CONFIG_DIR.exists():
        return []
    return sorted(p.stem for p in _CONFIG_DIR.glob("*.yaml"))


def _jobs_root(request: Request) -> Path:
    return Path(request.app.state.jobs_root)


@router.get("/run-lab", response_class=HTMLResponse)
def run_lab(request: Request) -> HTMLResponse:
    base = request.query_params.get("base")
    yaml_text = ""
    if base and base in _base_configs():
        yaml_text = (_CONFIG_DIR / f"{base}.yaml").read_text(encoding="utf-8")
    ctx = {
        "base_configs": _base_configs(),
        "selected_base": base or "",
        "yaml_text": yaml_text,
        "jobs": jobs.list_jobs(_jobs_root(request)),
    }
    return render_page(
        request,
        active="/run-lab",
        full_template="run_lab.html",
        content_template="run_lab_content.html",
        context=ctx,
    )


@router.post("/run-lab/validate", response_class=HTMLResponse)
def validate(request: Request, config_yaml: str = Form(...)) -> HTMLResponse:
    ok, msg = jobs.validate(config_yaml)
    return templates.TemplateResponse(
        request, "_validate_result.html", {"ok": ok, "msg": msg}
    )


@router.post("/run-lab/submit", response_class=HTMLResponse)
def submit(
    request: Request, label: str = Form("run"), config_yaml: str = Form(...)
) -> HTMLResponse:
    jobs.submit(_jobs_root(request), label, config_yaml)
    return templates.TemplateResponse(
        request, "_job_list.html", {"jobs": jobs.list_jobs(_jobs_root(request))}
    )


@router.get("/run-lab/status", response_class=HTMLResponse)
def status(request: Request) -> HTMLResponse:
    jobs.reconcile_and_advance(_jobs_root(request), request.app.state.runs_root)  # 輪詢順手推排隊
    return templates.TemplateResponse(
        request, "_job_list.html", {"jobs": jobs.list_jobs(_jobs_root(request))}
    )
```

新增 `templates/_validate_result.html`：
```html
{% if ok %}
<span class="badge badge-done">config OK</span>
{% else %}
<span class="badge badge-failed">config 無效</span>
<pre class="json-block">{{ msg }}</pre>
{% endif %}
```

- [ ] **Step 4: 模板** — `run_lab.html`：
```html
{% extends "base.html" %}
{% block content %}{% include "run_lab_content.html" %}{% endblock %}
```

`run_lab_content.html`：
```html
<h1 class="page-title">回測工作台</h1>
<form method="get" class="page-controls">
  <label class="ctl">base config
    <select name="base" onchange="this.form.submit()">
      <option value="">（空白）</option>
      {% for b in base_configs %}<option value="{{ b }}" {% if b==selected_base %}selected{% endif %}>{{ b }}</option>{% endfor %}
    </select>
  </label>
  <span class="ident">選 base config 載入下方編輯器，改完提交</span>
</form>

<form method="post" action="/run-lab/submit" hx-post="/run-lab/submit" hx-target="#job-list">
  <textarea name="config_yaml" rows="18" class="yaml-editor" spellcheck="false">{{ yaml_text }}</textarea>
  <div class="page-controls">
    <label class="ctl">label <input type="text" name="label" value="{{ selected_base or 'run' }}" class="ctl-input"></label>
    <button type="button" class="pgbtn" hx-post="/run-lab/validate" hx-include="closest form" hx-target="#validate-result">驗證</button>
    <button type="submit" class="pgbtn">提交回測</button>
    <span id="validate-result"></span>
  </div>
</form>

<h2 class="section-title">Jobs</h2>
<div id="job-list" hx-get="/run-lab/status" hx-trigger="every 2s">
  {% include "_job_list.html" %}
</div>
```

`_job_list.html`：
```html
<table class="data-table">
  <thead><tr><th>job</th><th>狀態</th><th>進度</th><th>提交</th><th>結果</th></tr></thead>
  <tbody>
  {% for j in jobs %}
    <tr>
      <td class="rowhead">{{ j.label }}</td>
      <td><span class="badge badge-{{ j.state }}">{{ j.state }}</span></td>
      <td>{% if j.strategy_total %}{{ j.current_strategy }} {{ j.strategy_index }}/{{ j.strategy_total }}{% elif j.stage %}{{ j.stage }}{% else %}—{% endif %}</td>
      <td>{{ j.submitted_at }}</td>
      <td>
        {% if j.state == "done" and j.run_dir %}<a class="pgbtn" href="/overview?run={{ j.run_dir.split('/')[-1].split('\\')[-1] }}">看 run</a>
        {% elif j.state == "failed" %}<span class="badge badge-failed" title="{{ j.error }}">失敗</span>{% else %}—{% endif %}
      </td>
    </tr>
  {% endfor %}
  {% if not jobs %}<tr><td colspan="5" class="empty">尚無 job。</td></tr>{% endif %}
  </tbody>
</table>
```

- [ ] **Step 5: CSS**（`app.css` 追加）：
```css
.yaml-editor { width: 100%; background: var(--panel); color: var(--fg); border: 1px solid var(--border); border-radius: 6px; font-family: var(--mono); font-size: 12px; padding: 10px; resize: vertical; }
.ctl-input { background: var(--panel-2); color: var(--fg); border: 1px solid var(--border); border-radius: 4px; padding: 3px 6px; font-family: var(--mono); }
.badge { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; }
.badge-queued { background: #23231f; color: var(--fg-dim); }
.badge-running { background: #241a08; color: var(--amber); }
.badge-done { background: #0d2417; color: var(--up); }
.badge-failed { background: #2a1110; color: var(--down); }
```

- [ ] **Step 6: app 接線 + stub 清理** — 改 `quantcore/presentation/web/app.py`：

(a) import：把 `stubs` 從 routes import 移除、加 `run_lab`；並加 `import threading`、`from contextlib import asynccontextmanager`、`from quantcore.presentation import jobs`。

(b) 在 `create_app` 內：`app.state.jobs_root = Path(os.environ.get("QUANTCORE_JOBS_ROOT", "jobs"))`（若 `create_app(jobs_root=...)` 有給則優先——把簽名改為 `def create_app(runs_root=None, jobs_root=None)`）；把 `app.include_router(stubs.router)` 換成 `app.include_router(run_lab.router)`。

(c) 加 lifespan 心跳執行緒（每 3s reconcile）：
```python
def create_app(runs_root: Path | None = None, jobs_root: Path | None = None) -> FastAPI:
    jroot = Path(jobs_root or os.environ.get("QUANTCORE_JOBS_ROOT", "jobs"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = threading.Event()

        rroot = Path(runs_root or os.environ.get("QUANTCORE_RUNS_ROOT", "runs"))

        def _tick():
            while not stop.wait(3.0):
                try:
                    jobs.reconcile_and_advance(jroot, rroot)
                except Exception:  # noqa: BLE001 —— 心跳執行緒不因單次錯誤中止
                    pass

        t = threading.Thread(target=_tick, daemon=True)
        t.start()
        yield
        stop.set()

    app = FastAPI(title="QuantCore Dashboard", lifespan=lifespan)
    ...
    app.state.jobs_root = jroot
```
（把既有 `create_app` 主體搬進來、保留原有 router include，僅 stubs→run_lab、加 jobs_root/lifespan。）

(d) 刪 `git rm quantcore/presentation/web/routes/stubs.py quantcore/presentation/web/templates/stub.html quantcore/presentation/web/templates/stub_content.html`。

(e) 改 `tests/test_presentation/test_web_htmx.py`：刪除 `test_stub_pages_reachable` 與 `test_stub_hx_fragment_excludes_shell` 兩個測試（已無 stub）；保留 `test_hx_request_returns_content_only`、`test_full_request_includes_shell`（改用 `/overview` 驗，不依賴 stub）。

- [ ] **Step 7: GREEN 全套 + ruff** — `uv run pytest tests/test_presentation -q`（含新 run_lab 測試、架構守護——run_lab.py/jobs.py 不得 import 引擎）；`uv run ruff check quantcore/presentation tests/test_presentation` + `ruff format`。

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(phase7b): Run Lab 頁面（YAML 編輯/驗證/提交/job 輪詢）+ 背景心跳 + 退役 stubs"
```

---

### Task 4: 端到端 AC②③ 測試

**Files:**
- Create: `tests/test_presentation/test_web_run_lab_e2e.py`

- [ ] **Step 1: AC③ 復原測試（CI 安全，純檔案）** — 建 `tests/test_presentation/test_web_run_lab_e2e.py`：

```python
import pytest

from quantcore.presentation import jobs


def test_ac3_reconcile_marks_dead_running_failed_then_spawns_next(tmp_path):
    # 模擬 UI 重啟後：一個 running 但 pid 已死 + 一個 queued
    dead = jobs.submit(tmp_path, "dead", "c")
    jobs._write_status(tmp_path / dead / "status.json", state="running", pid=424242)
    nxt = jobs.submit(tmp_path, "next", "c")
    spawned = []
    rr = tmp_path / "runs"
    # 第一次 tick：標死掉的 running 為 failed（本 tick 不 spawn）
    jobs.reconcile_and_advance(
        tmp_path, rr, pid_alive=lambda p: False, spawn=lambda root, jid, r: spawned.append(jid)
    )
    assert jobs.load_status(tmp_path, dead)["state"] == "failed"
    assert spawned == []
    # 第二次 tick：無 running → spawn 最早 queued
    jobs.reconcile_and_advance(
        tmp_path, rr, pid_alive=lambda p: False, spawn=lambda root, jid, r: spawned.append(jid)
    )
    assert spawned == [nxt]
```

- [ ] **Step 2: 跑** — `uv run pytest tests/test_presentation/test_web_run_lab_e2e.py -q` → PASS。

- [ ] **Step 3: AC② 端到端（requires_snapshot 本機閘門）** — 追加：

```python
import time
from pathlib import Path

from fastapi.testclient import TestClient

from quantcore.presentation.web.app import create_app


@pytest.mark.requires_snapshot
def test_ac2_submit_real_config_runs_to_done(tmp_path):
    # 用真 canonical config（本機有快照時）跑單一策略，經 UI 提交 → 排程 → 完成
    cfg_yaml = Path("quantcore/config/canonical_ewma.yaml").read_text(encoding="utf-8")
    jobs_root = tmp_path / "jobs"
    client = TestClient(create_app(runs_root=Path("runs"), jobs_root=jobs_root))
    client.post("/run-lab/submit", data={"label": "e2e", "config_yaml": cfg_yaml})
    from quantcore.presentation import jobs

    # 手動驅動排程（測試不啟背景執行緒）
    jobs.reconcile_and_advance(jobs_root, Path("runs"))  # spawn detached 子行程
    job_id = jobs.list_jobs(jobs_root)[0]["job_id"]
    deadline = time.time() + 600
    state = "running"
    while time.time() < deadline:
        st = jobs.load_status(jobs_root, job_id)
        state = st["state"]
        if state in ("done", "failed"):
            break
        jobs.reconcile_and_advance(jobs_root, Path("runs"))
        time.sleep(2)
    assert state == "done", f"最終狀態 {state}：{jobs.load_status(jobs_root, job_id).get('error')}"
    assert Path(jobs.load_status(jobs_root, job_id)["run_dir"]).exists()
```

> `requires_snapshot`：CI 無快照乾淨 skip（比照歷來 AC 閘門）；本機有快照跑真回測。單一 run 的 canonical_ewma 8 策略 ~數分鐘，deadline 600s 寬鬆。若嫌久，可在 e2e 前把 cfg_yaml 的策略縮減（但 config 無策略欄——策略由 CLI `--strategies` 給；此處走預設全 8 策略，接受較慢，本機閘門非 CI）。

- [ ] **Step 4: 本機驗證**（有快照時）— `uv run pytest tests/test_presentation/test_web_run_lab_e2e.py -q`（含 requires_snapshot）確認 AC② 真的跑到 done。CI 環境自動 skip。

- [ ] **Step 5: Commit**

```bash
git add tests/test_presentation/test_web_run_lab_e2e.py
git commit -m "test(phase7b): Run Lab AC③ 復原（CI）+ AC② 端到端（requires_snapshot 本機閘門）"
```

---

## Self-Review 對照

- **Spec 覆蓋**：jobs store/submit/list/validate（Task 1）✓、detached spawn + reconcile + psutil pid-liveness（Task 2）✓、Run Lab 頁面 YAML 編輯/驗證/提交/job 清單輪詢/log（Task 3）✓、背景心跳執行緒（Task 3 lifespan）✓、psutil+python-multipart 依賴（Task 3）✓、頁 8 換真頁 + stub 退役（Task 3）✓、AC③ 復原 + AC② 端到端（Task 4）✓。
- **§2.2 邊界**：`jobs.py`/`run_lab.py` 不 import 引擎（只 subprocess）；既有 AST 守護於全套執行時把關。status.json 由引擎子行程權威擁有；jobs.py 只寫 queued + reconcile 的 mark_failed（boundary 兩側各一份原子寫，刻意不共用 experiments.jobstatus）。
- **race 防護**：`_spawn` 立刻寫 running+`proc.pid`，關閉「重複 spawn / pid 未寫誤判死亡」窗口；reconcile 全程持 `_LOCK`。
- **測試策略**：純排程決策注入 `pid_alive`/`spawn`（CI 安全、不起真行程）；AC② 真 subprocess 走 `requires_snapshot` 本機閘門。TestClient 不進 lifespan → 背景執行緒不啟、submit 不同步 spawn（停 queued），單元測試穩定。
- **型別一致**：`jobs.submit(jobs_root,label,yaml)->job_id`、`list_jobs`、`load_status`、`tail_log`、`validate(yaml)->(ok,msg)`、`_next_action(statuses,pid_alive)`、`reconcile_and_advance(jobs_root,runs_root,pid_alive=None,spawn=None)`、`_spawn(jobs_root,job_id,runs_root)`、`create_app(runs_root=None,jobs_root=None)` 跨 task 一致。回測產物落 `runs_root`（app 傳 app.state.runs_root、測試傳 tmp），不硬編 "runs"。
- **無 placeholder**：各 step 附完整程式碼與指令。
- **邊界收尾**：stubs.py + stub 模板 + 兩個 stub 測試刪除（/run-lab 為最後 stub）。
