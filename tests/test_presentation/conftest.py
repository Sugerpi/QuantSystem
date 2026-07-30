"""合成 run fixture：以 run_experiment 在合成快照上產出真實結構的 run 目錄（CI 可跑）。

注意：這是唯一「間接經由 experiments 產生測試資料」之處，屬測試 setup、非 presentation 執行期
import；presentation 執行期仍只讀檔案（架構守護測試覆蓋 quantcore/presentation/ 原始碼）。
"""

import numpy as np
import pandas as pd
import pytest

from quantcore.config import load_config
from quantcore.experiments.runner import run_experiment
from tests.fixtures.synthetic import make_dates, make_snapshot


@pytest.fixture(scope="session")
def run_dir(tmp_path_factory):
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
    out = tmp_path_factory.mktemp("runs")
    return run_experiment(
        cfg=cfg,
        snapshot=snap,
        out_root=out,
        label="fix",
        strategy_ids=["bh_spy", "full"],
        now=pd.Timestamp("2026-07-30T10:00:00"),
    )


@pytest.fixture(scope="session")
def runs_root(run_dir):
    """run_dir 的父目錄——作為 dashboard 的 runs 根（含一個合成 run）。"""
    return run_dir.parent
