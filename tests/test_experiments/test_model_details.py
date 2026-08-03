"""runner 落盤 trades.parquet + model_details/（Phase 7a）。"""

import numpy as np
import pandas as pd

from quantcore.config import load_config
from quantcore.experiments.runner import run_experiment
from tests.fixtures.synthetic import make_dates, make_snapshot


def _cfg():
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["SPY", "QQQ", "IWM"]
    cfg.universe.min_history_days = 5
    cfg.signal.momentum_lookback = 5
    cfg.signal.momentum_skip = 1
    cfg.signal.top_k = 2
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    cfg.risk.corr_model = "ewma"
    cfg.risk.vol_model = "ewma"
    return cfg


def _snap(n=80):
    dates = make_dates(n)
    rng = np.random.default_rng(3)
    return make_snapshot(
        {
            "SPY": list(100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))),
            "QQQ": list(200.0 * np.cumprod(1 + rng.normal(0.0005, 0.012, n))),
            "IWM": list(150.0 * np.cumprod(1 + rng.normal(0.0005, 0.013, n))),
        },
        dates,
    )


def test_run_emits_trades_and_model_details(tmp_path):
    d = run_experiment(
        cfg=_cfg(),
        snapshot=_snap(),
        out_root=tmp_path,
        label="md",
        strategy_ids=["bh_spy", "full"],
        now=pd.Timestamp("2026-07-29T10:00:00"),
    )
    trades = pd.read_parquet(d / "trades.parquet")
    assert {"execution_date", "strategy_id", "ticker", "delta_weight", "fill_price", "cost"} <= set(
        trades.columns
    )
    assert (trades["strategy_id"] == "bh_spy").any()

    corr = pd.read_parquet(d / "model_details" / "correlation.parquet")
    assert set(corr["strategy_id"].unique()) == {"full"}
    assert {"ticker_i", "ticker_j", "corr"} <= set(corr.columns)

    resid = pd.read_parquet(d / "model_details" / "residuals.parquet")
    assert {"strategy_id", "ticker", "date", "std_resid"} <= set(resid.columns)
    assert "bh_spy" not in resid["strategy_id"].unique()

    dec = pd.read_parquet(d / "decisions.parquet")
    assert "corr_fell_back" in dec.columns
