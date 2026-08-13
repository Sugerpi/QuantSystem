"""曝險帶 absolute vs log 的換手率–追蹤誤差前沿消融（規格 §1.7、設計文件 §7）。

純核心（pareto_front / frontier_dominates / assemble_frontier）可單測；
CLI 驅動（run_frontier）於後續任務加入，重用 experiments.ablation.run_ablation。
presentation 不涉入；此為 experiments 層。
"""

from __future__ import annotations

import pandas as pd

_EPS = 1e-12


def pareto_front(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """(turnover, tracking_error) 皆越小越好。回非被支配點，依 turnover 升序。"""
    front: list[tuple[float, float]] = []
    best_te = float("inf")
    for turn, te in sorted(set(points)):
        if te < best_te - _EPS:
            front.append((turn, te))
            best_te = te
    return front


def frontier_dominates(
    log_pts: list[tuple[float, float]], abs_pts: list[tuple[float, float]]
) -> bool:
    """log 是否弱支配 abs：每個 abs 點都有某 log 點 turnover≤ 且 tracking≤。"""
    return all(any(lt <= at + _EPS and le <= ae + _EPS for lt, le in log_pts) for at, ae in abs_pts)


def assemble_frontier(comparison: pd.DataFrame, mode: str, sigma_star: float) -> pd.DataFrame:
    """comparison.parquet（cell_label/strategy_id/annualized_turnover/annualized_vol/sharpe）
    → 前沿長表。只取 cell_label 形如 'risk.exposure_band=<v>' 的網格格（略過 baseline）。
    """
    rows = []
    for _, r in comparison.iterrows():
        label = str(r["cell_label"])
        if not label.startswith("risk.exposure_band="):
            continue
        band = float(label.split("=", 1)[1])
        rows.append(
            {
                "mode": mode,
                "band": band,
                "strategy_id": r["strategy_id"],
                "turnover": float(r["annualized_turnover"]),
                "tracking_error": abs(float(r["annualized_vol"]) - sigma_star),
                "sharpe": float(r["sharpe"]),
            }
        )
    return pd.DataFrame(
        rows, columns=["mode", "band", "strategy_id", "turnover", "tracking_error", "sharpe"]
    )
