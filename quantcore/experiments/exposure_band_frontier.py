"""曝險帶 absolute vs log 的換手率–追蹤誤差前沿消融（規格 §1.7、設計文件 §7）。

純核心（pareto_front / frontier_dominates / assemble_frontier）可單測；
CLI 驅動（run_frontier）已實作，重用 experiments.ablation.run_ablation 跑兩趟消融。
presentation 不涉入；此為 experiments 層。
"""

from __future__ import annotations

import argparse
import sys

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


def run_frontier(
    config_path: str,
    out_root: str = "runs",
    strategies: tuple[str, ...] = ("voltarget_only", "full"),
    abs_bands: tuple[float, ...] = (0.06, 0.08, 0.10, 0.13, 0.16),
    log_bands: tuple[float, ...] = (0.10, 0.15, 0.20, 0.25),
) -> pd.DataFrame:
    """跑 absolute/log 兩趟帶寬掃描，回合併前沿表並印各策略支配判定。"""
    from quantcore.config import load_config
    from quantcore.data.snapshot import load_snapshot
    from quantcore.experiments.ablation import run_ablation

    cfg = load_config(config_path)
    snapshot = load_snapshot(cfg.snapshot)
    sids = list(strategies)

    def _pass(mode: str, bands: tuple[float, ...]) -> pd.DataFrame:
        risk = cfg.risk.model_copy(update={"exposure_band_mode": mode})
        base = cfg.model_copy(update={"risk": risk})
        run_dir = run_ablation(
            base_cfg=base,
            snapshot=snapshot,
            strategy_ids=sids,
            param_grid={"risk.exposure_band": list(bands)},
            out_root=out_root,
            label=f"frontier_{mode}",
        )
        table = pd.read_parquet(run_dir / "comparison.parquet")
        return assemble_frontier(table, mode, cfg.risk.vol_target_annual)

    front = pd.concat([_pass("absolute", abs_bands), _pass("log", log_bands)], ignore_index=True)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    degenerate = front[front[["turnover", "tracking_error"]].isna().any(axis=1)]
    if not degenerate.empty:
        print("⚠ 前沿含 NaN（退化格）——支配判定可能不可靠：")
        print(degenerate.to_string(index=False))
    print("=== 曝險帶前沿（換手率↓ / 追蹤誤差↓）===")
    print(front.sort_values(["strategy_id", "mode", "band"]).to_string(index=False))
    print("\n=== 支配判定（log 弱支配 absolute？）===")
    for sid in sids:
        sub = front[front["strategy_id"] == sid]
        log_sub = sub[sub["mode"] == "log"]
        abs_sub = sub[sub["mode"] == "absolute"]
        log_f = pareto_front(list(zip(log_sub["turnover"], log_sub["tracking_error"], strict=True)))
        abs_f = pareto_front(list(zip(abs_sub["turnover"], abs_sub["tracking_error"], strict=True)))
        verdict = "支配" if frontier_dominates(log_f, abs_f) else "未支配"
        print(f"  {sid}: log {verdict} absolute")
    return front


def _cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m quantcore.experiments.exposure_band_frontier")
    p.add_argument("--config", default="quantcore/config/default.yaml")
    p.add_argument("--out-root", default="runs")
    args = p.parse_args(argv)
    run_frontier(args.config, args.out_root)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
