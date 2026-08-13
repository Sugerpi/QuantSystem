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
