"""單次實驗 pipeline（規格 §7.1）。"""

import json

import numpy as np
import pandas as pd

from quantcore.config import load_config
from quantcore.experiments.runner import run_experiment
from tests.fixtures.synthetic import make_dates, make_snapshot


def _cfg():
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["SPY", "QQQ"]
    cfg.universe.min_history_days = 5
    cfg.signal.top_k = 2
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    return cfg


def _snap(n=30):
    dates = make_dates(n)
    rng = np.random.default_rng(3)
    return make_snapshot(
        {
            "SPY": list(100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))),
            "QQQ": list(200.0 * np.cumprod(1 + rng.normal(0.0005, 0.012, n))),
        },
        dates,
    )


def test_run_experiment_writes_all_artifacts_for_both_strategies(tmp_path):
    d = run_experiment(
        cfg=_cfg(),
        snapshot=_snap(),
        out_root=tmp_path,
        label="test",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )
    nav = pd.read_parquet(d / "nav.parquet")
    assert set(nav["strategy_id"].unique()) == {"bh_spy", "ew_menu"}

    metrics = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
    assert set(metrics) == {"bh_spy", "ew_menu"}
    assert "sharpe" in metrics["bh_spy"]


def test_all_strategies_share_the_same_nav_start_date(tmp_path):
    """warmup 全 run 統一（設計文件 §2.3）——否則七策略比較表不可比。"""
    d = run_experiment(
        cfg=_cfg(),
        snapshot=_snap(),
        out_root=tmp_path,
        label="test",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )
    nav = pd.read_parquet(d / "nav.parquet")
    starts = nav.groupby("strategy_id")["date"].min()
    assert starts.nunique() == 1


def test_metrics_json_carries_subperiod_analysis(tmp_path):
    """§6.4 子期間分析須實際產出：metrics.json 每策略含 subperiods 分解，
    每個 config 子期間一格（有資料格帶完整 metrics、空格為 n_days=0）。"""
    cfg = _cfg()
    cfg.stats = cfg.stats.model_copy(update={"subperiods": [(2020, 2020), (2021, 2021)]})
    d = run_experiment(
        cfg=cfg,
        snapshot=_snap(),  # make_dates 自 2020-01-02 起 → 全落在 2020
        out_root=tmp_path,
        label="test",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )
    metrics = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
    sub = metrics["bh_spy"]["subperiods"]
    assert set(sub) == {"2020-2020", "2021-2021"}
    assert sub["2020-2020"]["n_days"] > 0 and "sharpe" in sub["2020-2020"]  # 有資料
    assert sub["2021-2021"] == {"n_days": 0}  # 無資料格


def test_decisions_carry_null_model_columns(tmp_path):
    """Phase 2 無模型，欄位須存在但為 null（設計文件 §0、§4）。"""
    d = run_experiment(
        cfg=_cfg(),
        snapshot=_snap(),
        out_root=tmp_path,
        label="test",
        strategy_ids=["ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )
    dec = pd.read_parquet(d / "decisions.parquet")
    assert not dec.empty
    for col in ("momentum_scores", "sigma_hat", "sigma_p", "exposure_applied", "band_blocked"):
        assert col in dec.columns
        assert dec[col].isna().all()
    assert dec["eligible"].iloc[0] == '["QQQ", "SPY"]'
