from pathlib import Path

from quantcore.presentation.web.controls import parse_controls

_RUNS = [
    {"name": "vol_eval", "path": "/r/vol_eval", "strategies": []},
    {"name": "canonical_ewma", "path": "/r/canonical_ewma", "strategies": ["bh_spy", "full"]},
]


def test_default_picks_latest_backtest_run_not_vol_eval():
    c = parse_controls({}, Path("/r"), _RUNS)
    assert c.run == "canonical_ewma"
    assert c.run_dir == Path("/r/canonical_ewma")
    assert c.strategies == ["bh_spy", "full"]
    assert c.available_runs == ["vol_eval", "canonical_ewma"]


def test_default_skips_trailing_non_backtest_run():
    runs = [
        {"name": "canonical_ewma", "path": "/r/canonical_ewma", "strategies": ["bh_spy", "full"]},
        {"name": "vol_eval", "path": "/r/vol_eval", "strategies": []},
    ]
    c = parse_controls({}, Path("/r"), runs)
    assert c.run == "canonical_ewma"
    assert c.strategies == ["bh_spy", "full"]


def test_explicit_run_honoured():
    c = parse_controls({"run": "vol_eval"}, Path("/r"), _RUNS)
    assert c.run == "vol_eval"
    assert c.strategies == []


def test_strat_csv_filtered_to_available():
    c = parse_controls({"strat": "full"}, Path("/r"), _RUNS)
    assert c.strategies == ["full"]


def test_bogus_strat_falls_back_to_all():
    c = parse_controls({"strat": "nope"}, Path("/r"), _RUNS)
    assert c.strategies == ["bh_spy", "full"]


def test_empty_runs_yields_none_run():
    c = parse_controls({}, Path("/r"), [])
    assert c.run is None
    assert c.run_dir is None
    assert c.available_runs == []


def test_query_suffix_roundtrips_selection():
    c = parse_controls({"run": "canonical_ewma", "strat": "full"}, Path("/r"), _RUNS)
    assert c.query_suffix == "?run=canonical_ewma&strat=full"
