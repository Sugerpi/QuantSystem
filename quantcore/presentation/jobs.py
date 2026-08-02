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
import uuid
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
    job_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{lbl}_{uuid.uuid4().hex[:8]}"
    d = Path(jobs_root) / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yaml").write_text(config_yaml, encoding="utf-8")
    _write_status(d / "status.json", job_id=job_id, label=lbl, state="queued", submitted_at=_now())
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
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(config_yaml)
        tmp = f.name
    try:
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "quantcore.experiments.runner",
                "--config",
                tmp,
                "--validate-only",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    finally:
        os.unlink(tmp)


def _next_action(statuses: list[dict], pid_alive: Callable[[int], bool]):
    """排程決策（純函數）。

    running 但 pid 死 → mark_failed；否則若無 running-活著則 spawn 最早 queued。
    """
    for s in statuses:
        if s.get("state") == "running":
            pid = s.get("pid")
            if pid is None or not pid_alive(int(pid)):
                return ("mark_failed", s["job_id"])
    busy = any(
        s.get("state") == "running" and s.get("pid") and pid_alive(int(s["pid"])) for s in statuses
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


def _spawn(jobs_root: str | Path, job_id: str, runs_root: str | Path) -> None:
    """detached subprocess 跑引擎 CLI；立刻寫 running+pid（關閉「重複 spawn / 誤判死亡」race）。

    回測產物落 runs_root（= dashboard 讀取的 runs 根），非硬編 "runs"。
    """
    d = Path(jobs_root) / job_id
    st = load_status(jobs_root, job_id) or {}
    label = st.get("label", "run")
    cmd = [
        sys.executable,
        "-m",
        "quantcore.experiments.runner",
        "--config",
        str(d / "config.yaml"),
        "--out-root",
        str(runs_root),
        "--label",
        label,
        "--status-file",
        str(d / "status.json"),
        "--job-id",
        job_id,
    ]
    kwargs: dict = {"stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    with open(d / "stdout.log", "w", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, stdout=log, **kwargs)  # noqa: S603 —— 固定引擎 CLI、參數非使用者拼接
    # 父端檔柄於此關閉；子行程已於 Popen 時 dup 自己的 fd，仍可寫入
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
