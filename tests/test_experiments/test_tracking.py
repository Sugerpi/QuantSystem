"""run 目錄、manifest、決定性寫檔（規格 §7.1、INV-6）。"""

import json

import pandas as pd
import pytest

from quantcore.experiments.tracking import create_run_dir, git_commit, write_artifacts


def test_create_run_dir_uses_label_and_timestamp(tmp_path):
    d = create_run_dir(tmp_path, "default", pd.Timestamp("2026-07-17T14:32:11"))
    assert d.name == "2026-07-17_1432_default"
    assert d.is_dir()


def test_create_run_dir_rejects_collision(tmp_path):
    ts = pd.Timestamp("2026-07-17T14:32:11")
    create_run_dir(tmp_path, "default", ts)
    with pytest.raises(FileExistsError):
        create_run_dir(tmp_path, "default", ts)


def test_git_commit_marks_dirty_working_tree():
    """INV-6 的三元組含 git_commit；工作區髒了卻回乾淨的 sha 就是撒謊。"""
    c = git_commit()
    assert isinstance(c, str) and len(c) >= 7


def test_manifest_separates_identity_from_created_at(tmp_path):
    d = create_run_dir(tmp_path, "x", pd.Timestamp("2026-07-17T14:32:11"))
    write_artifacts(
        run_dir=d,
        cfg_dict={"seed": 42},
        identity={
            "config_hash": "abc",
            "snapshot_id": "s1",
            "git_commit": "c1",
            "quantcore_version": "0.1.0",
        },
        created_at="2026-07-17T14:32:11+00:00",
        nav=pd.DataFrame(
            {
                "date": [pd.Timestamp("2020-01-02")],
                "strategy_id": ["a"],
                "nav": [1.0],
                "turnover": [0.0],
                "cost": [0.0],
            }
        ),
        weights=pd.DataFrame(
            {
                "date": [pd.Timestamp("2020-01-02")],
                "strategy_id": ["a"],
                "ticker": ["CASH"],
                "weight": [1.0],
            }
        ),
        decisions=pd.DataFrame(),
        trades=pd.DataFrame(),
        correlations=pd.DataFrame(),
        residuals=pd.DataFrame(),
        metrics={"a": {"sharpe": 1.0}},
    )
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert set(m) == {"identity", "content_hashes", "created_at"}
    assert m["identity"]["config_hash"] == "abc"
    assert set(m["content_hashes"]) == {
        "nav.parquet",
        "weights.parquet",
        "decisions.parquet",
        "trades.parquet",
        "metrics.json",
    }


def test_all_artifacts_written(tmp_path):
    d = create_run_dir(tmp_path, "x", pd.Timestamp("2026-07-17T14:32:11"))
    write_artifacts(
        run_dir=d,
        cfg_dict={"seed": 42},
        identity={
            "config_hash": "abc",
            "snapshot_id": "s1",
            "git_commit": "c1",
            "quantcore_version": "0.1.0",
        },
        created_at="2026-07-17T14:32:11+00:00",
        nav=pd.DataFrame(
            {
                "date": [pd.Timestamp("2020-01-02")],
                "strategy_id": ["a"],
                "nav": [1.0],
                "turnover": [0.0],
                "cost": [0.0],
            }
        ),
        weights=pd.DataFrame(
            {
                "date": [pd.Timestamp("2020-01-02")],
                "strategy_id": ["a"],
                "ticker": ["CASH"],
                "weight": [1.0],
            }
        ),
        decisions=pd.DataFrame(),
        trades=pd.DataFrame(),
        correlations=pd.DataFrame(),
        residuals=pd.DataFrame(),
        metrics={"a": {"sharpe": 1.0}},
    )
    for fn in (
        "config.yaml",
        "manifest.json",
        "nav.parquet",
        "weights.parquet",
        "decisions.parquet",
        "trades.parquet",
        "metrics.json",
    ):
        assert (d / fn).exists(), fn
