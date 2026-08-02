import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quantcore.presentation import jobs
from quantcore.presentation.web.app import create_app


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


@pytest.mark.requires_snapshot
def test_ac2_submit_real_config_runs_to_done(tmp_path):
    # 用真 canonical config（本機有快照時）經 UI 提交 → 排程 → 跑到 done
    cfg_yaml = Path("quantcore/config/canonical_ewma.yaml").read_text(encoding="utf-8")
    jobs_root = tmp_path / "jobs"
    client = TestClient(create_app(runs_root=Path("runs"), jobs_root=jobs_root))
    client.post("/run-lab/submit", data={"label": "e2e", "config_yaml": cfg_yaml})

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
