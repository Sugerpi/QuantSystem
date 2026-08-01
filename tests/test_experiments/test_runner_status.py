import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from quantcore.config import load_config
from quantcore.experiments.runner import _cli, run_experiment
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
            "--config",
            str(cfgp),
            "--out-root",
            str(tmp_path / "runs"),
            "--strategies",
            "bh_spy",
            "--status-file",
            str(sf),
            "--job-id",
            "j1",
        ]
    )
    assert rc == 1
    d = json.loads(sf.read_text(encoding="utf-8"))
    assert d["state"] == "failed"
    assert d["stage"] == "error"
    assert d["error"]
    assert d["job_id"] == "j1"
