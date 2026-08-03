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
