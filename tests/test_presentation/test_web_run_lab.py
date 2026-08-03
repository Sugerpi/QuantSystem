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
