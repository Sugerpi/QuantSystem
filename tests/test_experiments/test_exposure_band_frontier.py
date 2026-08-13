"""換手率–追蹤誤差前沿純函數（純邏輯，不跑回測）。"""

from __future__ import annotations

import pandas as pd
import pytest

from quantcore.experiments.exposure_band_frontier import (
    assemble_frontier,
    frontier_dominates,
    pareto_front,
)


def test_pareto_front_drops_dominated():
    pts = [(1.0, 0.05), (1.5, 0.06), (2.0, 0.04), (3.0, 0.03)]
    assert pareto_front(pts) == [(1.0, 0.05), (2.0, 0.04), (3.0, 0.03)]


def test_frontier_dominates_true_when_log_weakly_better_everywhere():
    log_pts = [(1.0, 0.03), (2.0, 0.02)]
    abs_pts = [(1.5, 0.05), (2.5, 0.04)]
    assert frontier_dominates(log_pts, abs_pts) is True


def test_frontier_dominates_false_when_abs_has_unreachable_point():
    log_pts = [(1.0, 0.03), (2.0, 0.02)]
    abs_pts = [(0.5, 0.01)]  # 更低換手且更低追蹤誤差，log 觸不到
    assert frontier_dominates(log_pts, abs_pts) is False


def test_assemble_frontier_parses_band_and_tracking_error():
    df = pd.DataFrame(
        [
            {
                "cell_label": "risk.exposure_band=0.08",
                "strategy_id": "full",
                "annualized_turnover": 2.0,
                "annualized_vol": 0.12,
                "sharpe": 0.9,
            },
            {
                "cell_label": "baseline",
                "strategy_id": "full",
                "annualized_turnover": 9.9,
                "annualized_vol": 0.30,
                "sharpe": 0.1,
            },
        ]
    )
    out = assemble_frontier(df, mode="absolute", sigma_star=0.10)
    assert list(out.columns) == [
        "mode",
        "band",
        "strategy_id",
        "turnover",
        "tracking_error",
        "sharpe",
    ]
    # baseline 列被略過（非 risk.exposure_band= 網格格）
    assert len(out) == 1
    row = out.iloc[0]
    assert row["band"] == 0.08 and row["mode"] == "absolute"
    assert row["turnover"] == 2.0
    assert row["tracking_error"] == pytest.approx(0.02)  # |0.12 − 0.10|


def test_run_frontier_orchestrates_absolute_then_log(monkeypatch, tmp_path):
    # 不跑真回測：monkeypatch load_config/load_snapshot/run_ablation，
    # 只驗證 run_frontier 的協調——兩趟(absolute→log)、正確 grid、併表含兩 mode。
    import quantcore.experiments.exposure_band_frontier as mod
    from tests.fixtures.synthetic import make_cfg

    cfg = make_cfg(["SPY", "QQQ"], signal={"top_k": 2})
    monkeypatch.setattr("quantcore.config.load_config", lambda _p: cfg)
    monkeypatch.setattr("quantcore.data.snapshot.load_snapshot", lambda _s: {"dummy": True})

    seen: list = []

    def _fake_run_ablation(*, base_cfg, snapshot, strategy_ids, param_grid, out_root, label):
        seen.append(
            (base_cfg.risk.exposure_band_mode, tuple(param_grid["risk.exposure_band"]), label)
        )
        run_dir = tmp_path / label
        run_dir.mkdir()
        rows = []
        for sid in strategy_ids:
            for b in param_grid["risk.exposure_band"]:
                rows.append(
                    {
                        "cell_label": f"risk.exposure_band={b}",
                        "strategy_id": sid,
                        "annualized_turnover": 1.0 + b,
                        "annualized_vol": 0.10 + b,  # → tracking_error = b
                        "sharpe": 0.5,
                    }
                )
        pd.DataFrame(rows).to_parquet(run_dir / "comparison.parquet")
        return run_dir

    monkeypatch.setattr("quantcore.experiments.ablation.run_ablation", _fake_run_ablation)

    front = mod.run_frontier(
        "dummy.yaml",
        out_root=str(tmp_path),
        strategies=("voltarget_only", "full"),
        abs_bands=(0.06, 0.10),
        log_bands=(0.15, 0.25),
    )

    # 兩趟，順序 absolute 後 log，各自帶對的 grid
    assert [s[0] for s in seen] == ["absolute", "log"]
    assert seen[0][1] == (0.06, 0.10) and seen[1][1] == (0.15, 0.25)
    # 併表含兩 mode、兩策略，tracking_error = band（因 vol=0.10+band, σ*=0.10）
    assert set(front["mode"]) == {"absolute", "log"}
    assert set(front["strategy_id"]) == {"voltarget_only", "full"}
    is_abs = front["mode"] == "absolute"
    is_band = front["band"] == 0.06
    is_full = front["strategy_id"] == "full"
    row = front[is_abs & is_band & is_full].iloc[0]
    assert row["tracking_error"] == pytest.approx(0.06)
