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


def test_submit_rapid_same_label_unique_no_silent_overwrite(tmp_path):
    ids = {jobs.submit(tmp_path, "x", f"c{i}") for i in range(20)}
    assert len(ids) == 20  # 全部 job_id 唯一
    assert len(jobs.list_jobs(tmp_path)) == 20  # 無靜默覆蓋，20 個 job 都在


def _rec(root, **kw):
    # 注入 runs_root（tmp）+ 可注入 pid_alive/spawn
    return jobs.reconcile_and_advance(root, root / "runs", **kw)


def test_reconcile_marks_failed_running_with_dead_pid(tmp_path):
    jid = jobs.submit(tmp_path, "r", "c")
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
