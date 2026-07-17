"""INV-6：(config, snapshot_hash, git_commit) 三元組決定輸出（規格 §3、§7.1）。

比對對象是**資料產出**，不是整個目錄——run 目錄名含時間戳、manifest 含 created_at，
兩次跑必然不同。邊界寫在 manifest 的 identity / created_at 切分上（設計文件 §5.2）。
"""

import json

import numpy as np
import pandas as pd

from quantcore.config import load_config
from quantcore.experiments.runner import run_experiment
from tests.fixtures.synthetic import make_dates, make_snapshot

DATA_FILES = ("nav.parquet", "weights.parquet", "decisions.parquet", "metrics.json")


def _cfg():
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["SPY", "QQQ"]
    cfg.universe.min_history_days = 5
    cfg.signal.top_k = 2
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    return cfg


def _snap(n=40):
    dates = make_dates(n)
    rng = np.random.default_rng(11)
    return make_snapshot(
        {
            "SPY": list(100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))),
            "QQQ": list(200.0 * np.cumprod(1 + rng.normal(0.0005, 0.012, n))),
        },
        dates,
    )


def _run(tmp_path, name):
    return run_experiment(
        cfg=_cfg(),
        snapshot=_snap(),
        out_root=tmp_path / name,
        label="repro",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )


def test_two_runs_produce_byte_identical_data_artifacts(tmp_path):
    a = _run(tmp_path, "a")
    b = _run(tmp_path, "b")
    for fn in DATA_FILES:
        assert (a / fn).read_bytes() == (b / fn).read_bytes(), fn


def test_two_runs_share_identity_but_may_differ_in_created_at(tmp_path):
    a = json.loads((_run(tmp_path, "a") / "manifest.json").read_text(encoding="utf-8"))
    b = json.loads((_run(tmp_path, "b") / "manifest.json").read_text(encoding="utf-8"))
    assert a["identity"] == b["identity"]
    assert set(a) == {"identity", "created_at"}


def test_changing_config_changes_config_hash(tmp_path):
    a = json.loads((_run(tmp_path, "a") / "manifest.json").read_text(encoding="utf-8"))

    cfg = _cfg()
    cfg.costs.per_side_bps = 20.0
    d = run_experiment(
        cfg=cfg,
        snapshot=_snap(),
        out_root=tmp_path / "c",
        label="repro",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )
    b = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert a["identity"]["config_hash"] != b["identity"]["config_hash"]


def test_changing_cost_changes_nav(tmp_path):
    """config_hash 變了但輸出沒變 = hash 沒綁到真正影響結果的東西。"""
    a = pd.read_parquet(_run(tmp_path, "a") / "nav.parquet")

    cfg = _cfg()
    cfg.costs.per_side_bps = 20.0
    d = run_experiment(
        cfg=cfg,
        snapshot=_snap(),
        out_root=tmp_path / "c",
        label="repro",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )
    b = pd.read_parquet(d / "nav.parquet")
    assert not np.allclose(a["nav"].to_numpy(), b["nav"].to_numpy())
