"""通用消融引擎（規格 §7.3）。

一次跑多策略 × 參數敏感度（一次動一參數），彙整成單一比較表。
「跟得上多少跑多少」：只跑已註冊、已實作的策略；vol_target 敏感度留 Phase 4。

紀律（§7.3）：敏感度表用途是確認結論對參數擾動穩健，不是挑最好一格回填 config。
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import ValidationError

from quantcore.backtest.clock import EventClock
from quantcore.backtest.engine import run_strategy
from quantcore.backtest.metrics import compute_metrics
from quantcore.backtest.strategies import STRATEGIES
from quantcore.config import QuantConfig, load_config
from quantcore.data.hashing import config_hash
from quantcore.data.snapshot import load_snapshot
from quantcore.experiments.tracking import QC_VERSION, create_run_dir, git_commit

_DAYS_PER_YEAR = 252


def _apply_override(raw: dict, dotted_key: str, value) -> dict:
    """回傳套用單一 'section.field' 覆寫後的 config dict 副本。

    假設 key 為兩層 'section.field'（split(".", 1)）；深巢狀 key 不在支援範圍。
    """
    out = copy.deepcopy(raw)
    section, field = dotted_key.split(".", 1)
    out[section][field] = value
    return out


def _build_cells(base_raw: dict, param_grid: dict[str, list]) -> list[tuple[str, dict]]:
    """一次動一參數：baseline + 每個參數的每個值。回傳 (cell_label, config_dict)。"""
    cells: list[tuple[str, dict]] = [("baseline", base_raw)]
    for key, values in param_grid.items():
        for v in values:
            cells.append((f"{key}={v}", _apply_override(base_raw, key, v)))
    return cells


def _evaluate(cfg: QuantConfig, snapshot: dict, strategy_ids: list[str]) -> dict[str, dict]:
    """跑指定策略，回傳 {strategy_id: metrics dict}。in-memory，不落 run 目錄。"""
    d = snapshot["prices"]["date"]
    days = pd.DatetimeIndex(sorted(d.unique()))
    days = days[days >= pd.Timestamp(cfg.backtest.start)]

    strategies = [STRATEGIES[sid](cfg) for sid in strategy_ids]
    warmup = max(s.warmup_days for s in strategies)
    clock = EventClock(
        trading_days=days,
        warmup=warmup,
        selection_interval=cfg.schedule.selection_interval,
        exposure_check_interval=cfg.schedule.exposure_check_interval,
    )

    result: dict[str, dict] = {}
    for s in strategies:
        nav_df, _w, _dec = run_strategy(snapshot, clock, s, cfg)
        rate = (
            snapshot["rates"].set_index("date")["DTB3"].reindex(nav_df["date"]).ffill().bfill()
            / 100.0
            / _DAYS_PER_YEAR
        )
        result[s.strategy_id] = compute_metrics(
            nav=nav_df["nav"].reset_index(drop=True),
            rate_daily=rate.reset_index(drop=True),
            total_turnover=float(nav_df["turnover"].sum()),
            total_cost=float(nav_df["cost"].sum()),
            weights=_w,
        )
    return result


def _baseline_returns(
    base_cfg: QuantConfig, snapshot: dict, strategy_ids: list[str]
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """各策略在 baseline config 下的（日報酬, 日rf），同一 clock 對齊。"""
    d = snapshot["prices"]["date"]
    days = pd.DatetimeIndex(sorted(d.unique()))
    days = days[days >= pd.Timestamp(base_cfg.backtest.start)]
    strategies = [STRATEGIES[sid](base_cfg) for sid in strategy_ids]
    warmup = max(s.warmup_days for s in strategies)
    clock = EventClock(
        trading_days=days,
        warmup=warmup,
        selection_interval=base_cfg.schedule.selection_interval,
        exposure_check_interval=base_cfg.schedule.exposure_check_interval,
    )
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for s in strategies:
        nav_df, _w, _dec = run_strategy(snapshot, clock, s, base_cfg)
        rate = (
            snapshot["rates"].set_index("date")["DTB3"].reindex(nav_df["date"]).ffill().bfill()
            / 100.0
            / _DAYS_PER_YEAR
        )
        r = nav_df["nav"].pct_change().dropna().to_numpy()
        rf = rate.to_numpy()[1:]  # 對齊 pct_change 去掉的首日
        out[s.strategy_id] = (r, rf)
    lengths = {len(r) for r, _ in out.values()}
    if len(lengths) != 1:
        raise ValueError(f"baseline 各策略報酬長度不一致：{lengths}（clock 對齊有誤）")
    return out


def _baseline_bootstrap(
    base_cfg: QuantConfig, snapshot: dict, strategy_ids: list[str]
) -> pd.DataFrame:
    """full vs 每個其他策略的 Sharpe/Calmar 配對差異 CI（§6.3）。full 不在則回空表。"""
    from quantcore.backtest.metrics import (
        metric_calmar,
        metric_sharpe,
        paired_metric_diff_ci,
        stationary_bootstrap_indices,
    )

    if "full" not in strategy_ids:
        return pd.DataFrame()
    series = _baseline_returns(base_cfg, snapshot, strategy_ids)
    ra, rf = series["full"]
    n = len(ra)
    rng = np.random.default_rng(base_cfg.seed)  # INV-6
    idx = stationary_bootstrap_indices(
        n, base_cfg.stats.bootstrap_mean_block, base_cfg.stats.bootstrap_reps, rng
    )
    rows = []
    for sid, (rb, _rf) in series.items():
        if sid == "full":
            continue
        for mname, mfn in (("sharpe", metric_sharpe), ("calmar", metric_calmar)):
            res = paired_metric_diff_ci(ra, rb, rf, mfn, idx, base_cfg.stats.bootstrap_alpha)
            rows.append({"vs": sid, "metric": mname, **res})
    return pd.DataFrame(rows)


def _write_manifest(
    run_dir: Path,
    base_cfg: QuantConfig,
    snapshot: dict,
    strategy_ids: list[str],
    param_grid: dict[str, list],
    failed_cells: list[dict],
) -> None:
    """落盤 provenance（INV-6）：讓比較表可回溯到 config/snapshot/commit + 記錄失敗格。"""
    manifest = {
        "snapshot_id": snapshot["manifest"]["snapshot_id"],
        "git_commit": git_commit(),
        "config_hash": config_hash(base_cfg.model_dump(mode="json")),
        "quantcore_version": QC_VERSION,
        "strategy_ids": list(strategy_ids),
        "param_grid": param_grid,
        "failed_cells": failed_cells,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )


def run_ablation(
    base_cfg: QuantConfig,
    snapshot: dict,
    strategy_ids: list[str],
    param_grid: dict[str, list],
    out_root: str | Path,
    label: str,
    now: pd.Timestamp | None = None,
) -> Path:
    """跑消融矩陣並寫出單一比較表 + manifest，回傳 run 目錄。

    單格 config 驗證失敗只記錄並略過（跟得上多少跑多少），不拖垮整批。
    """
    now = pd.Timestamp.now() if now is None else now
    if not strategy_ids:
        raise ValueError("strategy_ids 不可為空")
    unknown = [s for s in strategy_ids if s not in STRATEGIES]
    if unknown:
        raise ValueError(f"未知策略 {unknown}；可用：{sorted(STRATEGIES)}")

    base_raw = base_cfg.model_dump(mode="json")
    rows: list[dict] = []
    failed_cells: list[dict] = []
    for cell_label, cfg_dict in _build_cells(base_raw, param_grid):
        try:
            cfg = QuantConfig.model_validate(cfg_dict)
        except ValidationError as e:
            failed_cells.append({"cell_label": cell_label, "error": f"{type(e).__name__}: {e}"})
            print(f"[消融] 略過無效格 {cell_label!r}：{type(e).__name__}")
            continue
        for sid, metrics in _evaluate(cfg, snapshot, strategy_ids).items():
            rows.append({"cell_label": cell_label, "strategy_id": sid, **metrics})

    table = pd.DataFrame(rows)
    run_dir = create_run_dir(out_root, f"{label}_ablation", now)
    table.to_parquet(run_dir / "comparison.parquet", index=False)
    _write_manifest(run_dir, base_cfg, snapshot, strategy_ids, param_grid, failed_cells)

    bootstrap = _baseline_bootstrap(base_cfg, snapshot, strategy_ids)
    if not bootstrap.empty:
        bootstrap.to_parquet(run_dir / "bootstrap.parquet", index=False)

    _print_summary(table)
    return run_dir


def _print_summary(table: pd.DataFrame) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    base = table[table["cell_label"] == "baseline"].sort_values("sharpe", ascending=False)
    print("=== 消融比較表（baseline，依 Sharpe 排序）===")
    cols = [
        c
        for c in ("strategy_id", "sharpe", "max_drawdown", "calmar", "annualized_turnover")
        if c in base.columns
    ]
    print(base[cols].to_string(index=False))


def _cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m quantcore.experiments.ablation")
    p.add_argument("--config", required=True)
    p.add_argument("--out-root", default="runs")
    p.add_argument("--label", default="default")
    p.add_argument(
        "--strategies",
        default="bh_spy,ew_menu,sixty_forty,mom_only,mom_ivol",
        help="逗號分隔；Phase 3 可跑者",
    )
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    snapshot = load_snapshot(cfg.snapshot)
    grid = {
        "signal.top_k": [3, 5, 8],
        "signal.momentum_lookback": [126, 252],
        "costs.per_side_bps": [0, 5, 10, 20],
    }
    run_dir = run_ablation(
        base_cfg=cfg,
        snapshot=snapshot,
        strategy_ids=[s.strip() for s in args.strategies.split(",") if s.strip()],
        param_grid=grid,
        out_root=args.out_root,
        label=args.label,
    )
    print(f"消融已完成：{run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
