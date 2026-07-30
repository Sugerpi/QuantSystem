from pathlib import Path

from quantcore.presentation import controls


def test_runs_root_prefers_session_then_env_then_default(monkeypatch):
    monkeypatch.delenv("QUANTCORE_RUNS_ROOT", raising=False)
    assert controls.runs_root({}) == Path("runs")
    monkeypatch.setenv("QUANTCORE_RUNS_ROOT", "/tmp/r")
    assert controls.runs_root({}) == Path("/tmp/r")
    assert controls.runs_root({"runs_root": "/tmp/s"}) == Path("/tmp/s")  # session 優先


def test_selection_accessors_default_empty():
    assert controls.selected_runs({}) == []
    assert controls.selected_strategies({}) == []
    assert controls.date_range({}) == (None, None)


def test_selection_accessors_read_state():
    st = {"selected_runs": ["r1"], "selected_strategies": ["full"], "date_range": ("2020", "2021")}
    assert controls.selected_runs(st) == ["r1"]
    assert controls.selected_strategies(st) == ["full"]
    assert controls.date_range(st) == ("2020", "2021")
