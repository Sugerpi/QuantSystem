"""AC-2：決策 diagnostics 完整落盤（規格 §6.2）。"""

import json

import pandas as pd

from quantcore.experiments.runner import run_experiment
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def test_mom_ivol_decisions_have_full_diagnostics(tmp_path):
    dates = make_dates(30)
    prices = {
        "WIN": [10.0 + i * 0.6 for i in range(30)],
        "MID": [10.0 + i * 0.3 for i in range(30)],
        "LOSE": [40.0 - i * 0.3 for i in range(30)],
        "SPY": [100.0 + i * 0.2 for i in range(30)],
        "IEF": [50.0 + i * 0.05 for i in range(30)],
    }
    snap = make_snapshot(prices, dates)
    cfg = make_cfg(
        ["WIN", "MID", "LOSE", "SPY", "IEF"],
        signal={"momentum_lookback": 4, "momentum_skip": 1, "top_k": 2},
        universe={"min_history_days": 5},
        risk={"vol_model": "rolling_std", "vol_window": 3},
        schedule={"selection_interval": 3, "exposure_check_interval": 2},
        backtest={"start": dates[0].date().isoformat(), "initial_nav": 1.0},
    )
    run_dir = run_experiment(
        cfg=cfg, snapshot=snap, out_root=tmp_path, label="t", strategy_ids=["mom_ivol"]
    )
    dec = pd.read_parquet(run_dir / "decisions.parquet")
    assert len(dec) > 0
    row = dec.iloc[0]
    assert json.loads(row["momentum_scores"])  # 非空
    assert json.loads(row["absmom"])
    assert json.loads(row["sigma_hat"])
    assert json.loads(row["w_risky"])
    # Phase 4 才有的曝險欄維持缺值
    assert pd.isna(row["sigma_p"])
    assert pd.isna(row["exposure_applied"])
