"""AC-1：消融跑得動並產出比較表（規格 §7.3）。"""

import json

import pandas as pd
import pytest

from quantcore.experiments.ablation import run_ablation
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def _cfg_and_snap():
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
        # mom_ivol 已遷移到 VolForecaster（GARCH/EWMA），不再支援 rolling_std（§6.3）
        risk={"vol_model": "ewma", "vol_window": 3},
        schedule={"selection_interval": 3, "exposure_check_interval": 2},
        backtest={"start": dates[0].date().isoformat(), "initial_nav": 1.0},
    )
    return cfg, snap


def test_ablation_produces_comparison_table(tmp_path):
    cfg, snap = _cfg_and_snap()
    run_dir = run_ablation(
        base_cfg=cfg,
        snapshot=snap,
        strategy_ids=["mom_only", "mom_ivol", "ew_menu"],
        param_grid={"signal.top_k": [2, 3]},
        out_root=tmp_path,
        label="test",
    )
    table = pd.read_parquet(run_dir / "comparison.parquet")
    assert len(table) > 0
    # 三策略 × (baseline + top_k 變體)
    assert set(table["strategy_id"]) == {"mom_only", "mom_ivol", "ew_menu"}
    for col in ("cell_label", "strategy_id", "sharpe", "max_drawdown"):
        assert col in table.columns


def test_ablation_grid_varies_one_param_at_a_time(tmp_path):
    cfg, snap = _cfg_and_snap()
    run_dir = run_ablation(
        base_cfg=cfg,
        snapshot=snap,
        strategy_ids=["mom_only"],
        param_grid={"signal.top_k": [2, 3], "costs.per_side_bps": [0, 10]},
        out_root=tmp_path,
        label="test",
    )
    table = pd.read_parquet(run_dir / "comparison.parquet")
    # cells: baseline + top_k(2 值) + cost(2 值) = 5 個 cell（一次動一參數，含 baseline）
    assert set(table["cell_label"]) == {
        "baseline",
        "signal.top_k=2",
        "signal.top_k=3",
        "costs.per_side_bps=0",
        "costs.per_side_bps=10",
    }


def test_ablation_override_actually_changes_metrics(tmp_path):
    cfg, snap = _cfg_and_snap()  # default per_side_bps=5
    run_dir = run_ablation(
        base_cfg=cfg,
        snapshot=snap,
        strategy_ids=["mom_only"],
        param_grid={"costs.per_side_bps": [50]},
        out_root=tmp_path,
        label="test",
    )
    table = pd.read_parquet(run_dir / "comparison.parquet")
    metric_cols = [c for c in table.columns if c not in ("cell_label", "strategy_id")]
    base = table[table["cell_label"] == "baseline"].iloc[0]
    variant = table[table["cell_label"] == "costs.per_side_bps=50"].iloc[0]
    assert not base[metric_cols].equals(variant[metric_cols])  # 至少一項指標改變


def test_ablation_writes_manifest_provenance(tmp_path):
    cfg, snap = _cfg_and_snap()
    run_dir = run_ablation(
        base_cfg=cfg,
        snapshot=snap,
        strategy_ids=["mom_only"],
        param_grid={"signal.top_k": [2]},
        out_root=tmp_path,
        label="test",
    )
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    for key in ("snapshot_id", "git_commit", "config_hash", "quantcore_version"):
        assert key in manifest
    assert manifest["strategy_ids"] == ["mom_only"]
    assert manifest["param_grid"] == {"signal.top_k": [2]}


def test_ablation_rejects_unknown_strategy(tmp_path):
    cfg, snap = _cfg_and_snap()
    with pytest.raises(ValueError):
        run_ablation(
            base_cfg=cfg,
            snapshot=snap,
            strategy_ids=["nope"],
            param_grid={},
            out_root=tmp_path,
            label="test",
        )


def test_ablation_skips_invalid_cell_keeps_valid(tmp_path):
    cfg, snap = _cfg_and_snap()  # 5-ticker menu → top_k=999 違反驗證
    run_dir = run_ablation(
        base_cfg=cfg,
        snapshot=snap,
        strategy_ids=["mom_only"],
        param_grid={"signal.top_k": [2, 999]},
        out_root=tmp_path,
        label="test",
    )
    table = pd.read_parquet(run_dir / "comparison.parquet")
    labels = set(table["cell_label"])
    assert "baseline" in labels and "signal.top_k=2" in labels
    assert "signal.top_k=999" not in labels  # 無效格被略過而非炸掉整批
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert any(f["cell_label"] == "signal.top_k=999" for f in manifest["failed_cells"])


def test_ablation_writes_bootstrap_table_when_full_present(tmp_path):
    import numpy as np
    import pandas as pd

    from quantcore.experiments.ablation import run_ablation
    from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot

    n = 340
    dates = make_dates(n)
    rng = np.random.default_rng(4)
    # voltarget_only 內部硬編碼持有 "SPY"（與 universe.menu 無關），
    # 快照須含 SPY 價格序列才能跑通，即便選單本身是 A/B/C/D。
    prices = {
        tk: list(100 * np.cumprod(1 + rng.normal(0.0003 * (i + 1), 0.01, n)))
        for i, tk in enumerate(["A", "B", "C", "D", "SPY"])
    }
    snap = make_snapshot(prices, dates)
    cfg = make_cfg(
        ["A", "B", "C", "D"],
        risk={"vol_model": "ewma", "corr_window": 60, "garch_window": 100},
        signal={"top_k": 2, "momentum_lookback": 120, "momentum_skip": 5},
        universe={"min_history_days": 130},
        stats={"bootstrap_reps": 50},
    )
    run_dir = run_ablation(cfg, snap, ["full", "mom_ivol", "voltarget_only"], {}, tmp_path, "test")
    bt = pd.read_parquet(run_dir / "bootstrap.parquet")
    assert set(bt["vs"]) == {"mom_ivol", "voltarget_only"}
    assert set(bt["metric"]) == {"sharpe", "calmar"}
    assert {"point", "lo", "hi", "excludes_zero"} <= set(bt.columns)
