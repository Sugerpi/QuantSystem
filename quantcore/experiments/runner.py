"""單次實驗：config → 完整 pipeline → artifacts（規格 §7.1）+ CLI。

CLI 是 Phase 7 Run Lab 的 subprocess 對象（§11.1：行程邊界取代 import 邊界）。

策略在外、天在內（設計文件 §0）：run_strategy 為獨立單元，本模組只負責
逐策略呼叫、concat、落地。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from quantcore.backtest.clock import EventClock
from quantcore.backtest.engine import run_strategy
from quantcore.backtest.metrics import compute_metrics, subperiod_metrics
from quantcore.backtest.strategies import STRATEGIES
from quantcore.backtest.strategies.vol_target_base import VolTargetStrategy
from quantcore.config import QuantConfig, load_config
from quantcore.data.hashing import config_hash
from quantcore.data.snapshot import load_snapshot
from quantcore.experiments.tracking import (
    QC_VERSION,
    create_run_dir,
    git_commit,
    write_artifacts,
)

_DAYS_PER_YEAR = 252


def _trading_days(snapshot: dict, start) -> pd.DatetimeIndex:
    d = snapshot["prices"]["date"]
    days = pd.DatetimeIndex(sorted(d.unique()))
    return days[days >= pd.Timestamp(start)]


def _diagnostics_row(diag) -> dict:
    """Diagnostics → parquet 可存的欄位。dict/list 以 JSON 字串存（決定性：sort_keys）。"""

    def j(v):
        return None if v is None else json.dumps(v, sort_keys=True, ensure_ascii=False)

    return {
        "eligible": j(diag.eligible),
        "selected": j(diag.selected),
        "momentum_scores": j(diag.momentum_scores),
        "absmom": j(diag.absmom),
        "sigma_hat": j(diag.sigma_hat),
        "w_risky": j(diag.w_risky),
        "sigma_p": diag.sigma_p,
        "exposure_raw": diag.exposure_raw,
        "exposure_applied": diag.exposure_applied,
        "band_blocked": diag.band_blocked,
        "vol_fell_back": j(diag.vol_fell_back),
        "garch_params": j(diag.garch_params),
        "corr_fell_back": diag.corr_fell_back,
    }


def _flatten_decisions(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw
    rows = []
    for r in raw.to_dict("records"):
        row = {
            "decision_date": r["decision_date"],
            "execution_date": r["execution_date"],
            "strategy_id": r["strategy_id"],
            "event": r["event"],
            "target_weights": json.dumps(r["target_weights"], sort_keys=True),
        }
        row.update(_diagnostics_row(r["diagnostics"]))
        rows.append(row)
    out = pd.DataFrame(rows)
    out["sigma_p"] = out["sigma_p"].astype("float64")
    out["exposure_raw"] = out["exposure_raw"].astype("float64")
    out["exposure_applied"] = out["exposure_applied"].astype("float64")
    out["band_blocked"] = out["band_blocked"].astype("boolean")
    out["corr_fell_back"] = out["corr_fell_back"].astype("boolean")
    return out


def _flatten_correlations(raw: pd.DataFrame) -> pd.DataFrame:
    """每決策的 corr_matrix → 長格式（decision_date, strategy_id, ticker_i, ticker_j, corr）。

    只有算 R 的策略（full/full_erc）有；K=1（voltarget_only）或無矩陣者跳過。
    """
    if raw.empty:
        return pd.DataFrame()
    rows = []
    for r in raw.to_dict("records"):
        rmat = r["diagnostics"].corr_matrix
        if rmat is None or rmat.shape[0] < 2:
            continue
        tickers = list(rmat.index)
        for ti in tickers:
            for tj in tickers:
                rows.append(
                    {
                        "decision_date": r["decision_date"],
                        "strategy_id": r["strategy_id"],
                        "ticker_i": ti,
                        "ticker_j": tj,
                        "corr": float(rmat.at[ti, tj]),
                    }
                )
    return pd.DataFrame(rows)


def _residuals_frame(strategy_id: str, resid: dict) -> pd.DataFrame:
    """各檔最後一次標準化殘差 → 長格式（strategy_id, ticker, date, std_resid）。"""
    rows = []
    for ticker, s in resid.items():
        for date, val in s.sort_index().items():
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "ticker": ticker,
                    "date": date,
                    "std_resid": float(val),
                }
            )
    return pd.DataFrame(rows)


def run_experiment(
    cfg: QuantConfig,
    snapshot: dict,
    out_root: str | Path,
    label: str,
    strategy_ids: list[str],
    now: pd.Timestamp | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> Path:
    """跑完所有策略並寫出 run 目錄，回傳該目錄。"""
    now = pd.Timestamp.now() if now is None else now
    days = _trading_days(snapshot, cfg.backtest.start)

    strategies = [STRATEGIES[sid](cfg) for sid in strategy_ids]
    warmup = max(s.warmup_days for s in strategies)  # 全 run 統一（設計文件 §2.3）
    clock = EventClock(
        trading_days=days,
        warmup=warmup,
        selection_interval=cfg.schedule.selection_interval,
        exposure_check_interval=cfg.schedule.exposure_check_interval,
    )

    navs, weights, decisions, trades, correlations, residuals, metrics = [], [], [], [], [], [], {}
    for i, s in enumerate(strategies, start=1):
        if on_progress is not None:
            on_progress(i, len(strategies), s.strategy_id)
        nav_df, w_df, d_df, t_df = run_strategy(snapshot, clock, s, cfg)
        navs.append(nav_df)
        weights.append(w_df)
        decisions.append(_flatten_decisions(d_df))
        trades.append(t_df)
        correlations.append(_flatten_correlations(d_df))
        if isinstance(s, VolTargetStrategy):
            residuals.append(_residuals_frame(s.strategy_id, s.standardized_residuals()))

        rate = (
            snapshot["rates"].set_index("date")["DTB3"].reindex(nav_df["date"]).ffill().bfill()
            / 100.0
            / _DAYS_PER_YEAR
        )
        metrics[s.strategy_id] = compute_metrics(
            nav=nav_df["nav"].reset_index(drop=True),
            rate_daily=rate.reset_index(drop=True),
            total_turnover=float(nav_df["turnover"].sum()),
            total_cost=float(nav_df["cost"].sum()),
            weights=w_df,
        )
        # §6.4 子期間分析：動量績效高度 regime 依賴，單一全期數字會說謊，故切子期間分報。
        dated_idx = pd.DatetimeIndex(nav_df["date"])
        metrics[s.strategy_id]["subperiods"] = subperiod_metrics(
            nav=pd.Series(nav_df["nav"].to_numpy(), index=dated_idx),
            rate_daily=pd.Series(rate.to_numpy(), index=dated_idx),
            subperiods=cfg.stats.subperiods,
        )

    run_dir = create_run_dir(out_root, label, now)
    write_artifacts(
        run_dir=run_dir,
        cfg_dict=cfg.model_dump(mode="json"),
        identity={
            "config_hash": config_hash(cfg.model_dump(mode="json")),
            "snapshot_id": snapshot["manifest"]["snapshot_id"],
            "git_commit": git_commit(),
            "quantcore_version": QC_VERSION,
        },
        created_at=datetime.now(UTC).isoformat(),
        nav=pd.concat(navs, ignore_index=True),
        weights=pd.concat(weights, ignore_index=True),
        decisions=pd.concat(decisions, ignore_index=True)
        if any(len(d) for d in decisions)
        else pd.DataFrame(),
        trades=pd.concat(trades, ignore_index=True)
        if any(len(t) for t in trades)
        else pd.DataFrame(),
        correlations=pd.concat(correlations, ignore_index=True)
        if any(len(c) for c in correlations)
        else pd.DataFrame(),
        residuals=pd.concat(residuals, ignore_index=True)
        if any(len(x) for x in residuals)
        else pd.DataFrame(),
        metrics=metrics,
    )
    return run_dir


def _cli(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    p = argparse.ArgumentParser(prog="python -m quantcore.experiments.runner")
    p.add_argument("--config", required=True)
    p.add_argument("--label", default=None, help="run 目錄後綴；預設取 config 檔名")
    p.add_argument("--out-root", default="runs")
    p.add_argument(
        "--strategies",
        default=",".join(STRATEGIES),
        help=f"逗號分隔；可用：{', '.join(STRATEGIES)}",
    )
    p.add_argument("--status-file", default=None, help="Run Lab 狀態檔（提供則寫 status.json）")
    p.add_argument("--job-id", default=None, help="Run Lab job id（寫入 status.json）")
    p.add_argument(
        "--validate-only", action="store_true", help="只驗證 config（pydantic），不跑回測"
    )
    args = p.parse_args(argv)

    if args.validate_only:
        try:
            load_config(args.config)
        except Exception as e:  # noqa: BLE001 —— CLI 邊界回報所有驗證錯
            print(f"config 無效：{type(e).__name__}: {e}")
            return 1
        print("OK")
        return 0

    label = args.label or Path(args.config).stem
    strategy_ids = [s.strip() for s in args.strategies.split(",") if s.strip()]

    if args.status_file is None:
        cfg = load_config(args.config)
        snapshot = load_snapshot(cfg.snapshot)
        run_dir = run_experiment(
            cfg=cfg,
            snapshot=snapshot,
            out_root=args.out_root,
            label=label,
            strategy_ids=strategy_ids,
        )
        print(f"run 已完成：{run_dir}")
        return 0

    from quantcore.experiments.jobstatus import write_status

    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    sf = args.status_file
    try:
        write_status(
            sf,
            job_id=args.job_id,
            state="running",
            stage="validating",
            pid=os.getpid(),
            started_at=_now(),
        )
        cfg = load_config(args.config)
        write_status(sf, stage="loading_snapshot")
        snapshot = load_snapshot(cfg.snapshot)
        run_dir = run_experiment(
            cfg=cfg,
            snapshot=snapshot,
            out_root=args.out_root,
            label=label,
            strategy_ids=strategy_ids,
            on_progress=lambda i, n, sid: write_status(
                sf, stage="running", strategy_index=i, strategy_total=n, current_strategy=sid
            ),
        )
        write_status(sf, state="done", stage="done", finished_at=_now(), run_dir=str(run_dir))
        print(f"run 已完成：{run_dir}")
        return 0
    except Exception as e:  # noqa: BLE001 —— 子行程邊界：任何失敗都要落 status
        write_status(
            sf,
            state="failed",
            stage="error",
            finished_at=_now(),
            error=f"{type(e).__name__}: {e}"[:2000],
        )
        print(f"回測失敗：{type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_cli())
