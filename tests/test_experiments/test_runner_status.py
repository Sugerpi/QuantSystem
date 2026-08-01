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
