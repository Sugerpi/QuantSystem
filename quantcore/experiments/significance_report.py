"""消融顯著性檢定編排 + CLI（規格 §3、§5.2；設計 2026-08-16）。

讀一個消融 run 目錄（comparison.parquet + cell_returns.parquet + manifest.json），
自動數 N、算目標策略 DSR、PBO（鎖定該策略、以消融格為候選集）、full vs 各殘缺版
的置換 p-value，落 significance.json。隨機性走 cfg.seed（INV-6）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, skew

from quantcore.backtest.metrics import metric_calmar, metric_sharpe
from quantcore.backtest.significance import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    pbo_cscv,
    permutation_test_paired,
    psr,
)
from quantcore.config import QuantConfig, load_config
from quantcore.data.snapshot import load_snapshot

_DAYS_PER_YEAR = 252


def _sharpe_ratio(r: np.ndarray) -> float:
    """每期（非年化）Sharpe = mean/std(ddof=1)。零變異回 nan。

    DSR 端餵超額報酬（ret−rf）算每期 SR；PBO 端餵各格原始日報酬作候選排名指標
    （rf 對各格相同、不影響排名），兩處共用同一定義。
    """
    sd = r.std(ddof=1)
    return float(r.mean() / sd) if sd > 0 else float("nan")


def _daily_rf(snapshot: dict, dates: pd.Series) -> np.ndarray:
    return (
        snapshot["rates"].set_index("date")["DTB3"].reindex(dates).ffill().bfill().to_numpy()
        / 100.0
        / _DAYS_PER_YEAR
    )


def build_significance_report(cfg: QuantConfig, snapshot: dict, run_dir: str | Path) -> dict:
    """算 DSR/PBO/置換並落 significance.json，回傳同一 dict。"""
    run_dir = Path(run_dir)
    target = cfg.stats.significance_strategy
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    comp = pd.read_parquet(run_dir / "comparison.parquet")
    cell_ret = pd.read_parquet(run_dir / "cell_returns.parquet")

    # 目標策略存在性檢查（設計 §4）：config 不反向依賴 backtest.STRATEGIES，
    # 改對本次 run 的實際策略集驗證——避免誤設策略時靜默產出 nan/空結果。
    available = set(cell_ret["strategy_id"].unique())
    if target not in available:
        raise ValueError(
            f"significance_strategy={target!r} 不在消融 run 的策略中：{sorted(available)}"
        )

    cells = list(comp["cell_label"].unique())
    n_trials = len(cells)

    # --- DSR：目標策略 baseline 格的每期 SR + 各格 SR 橫斷面變異 ---
    tgt = cell_ret[cell_ret["strategy_id"] == target]
    base = tgt[tgt["cell_label"] == "baseline"].sort_values("date")
    rf = _daily_rf(snapshot, base["date"])
    excess = base["ret"].to_numpy() - rf
    sr = _sharpe_ratio(excess)
    n_days = int(len(excess))
    sk = float(skew(excess))
    ku = float(kurtosis(excess, fisher=False))  # 非超額
    cell_srs = []
    for cl in cells:
        sub = tgt[tgt["cell_label"] == cl].sort_values("date")
        e = sub["ret"].to_numpy() - _daily_rf(snapshot, sub["date"])
        cell_srs.append(_sharpe_ratio(e))
    sr_var = float(np.nanvar(np.asarray(cell_srs), ddof=1)) if n_trials > 1 else 0.0
    dsr = {
        "strategy": target,
        "sr": sr,
        "psr": psr(sr, n_days, sk, ku, cfg.stats.psr_benchmark_sr),
        "expected_max_sr": expected_max_sharpe(sr_var, n_trials),
        "dsr": deflated_sharpe_ratio(sr, n_days, sk, ku, sr_var, n_trials),
        "n_days": n_days,
        "skew": sk,
        "kurt": ku,
        "sr_variance": sr_var,
    }

    # --- PBO：目標策略各格日報酬矩陣 T×N ---
    # 用 pivot（非 pivot_table）：每格每日僅一筆，重複 (date,cell) 應報錯而非靜默平均。
    # dropna 取各格共同日期（不同 momentum_lookback 使 warmup 起點不同），對齊成矩陣。
    wide = tgt.pivot(index="date", columns="cell_label", values="ret").sort_index().dropna()
    pbo = pbo_cscv(wide.to_numpy(), cfg.stats.pbo_n_splits, _sharpe_ratio)

    # --- 置換：full vs baseline 格各其他策略 ---
    base_ret = cell_ret[cell_ret["cell_label"] == "baseline"]
    strategies = [s for s in base_ret["strategy_id"].unique() if s != target]
    tgt_base = base_ret[base_ret["strategy_id"] == target].sort_values("date")
    ra = tgt_base["ret"].to_numpy()
    rf_a = _daily_rf(snapshot, tgt_base["date"])
    rng = np.random.default_rng(cfg.seed)  # INV-6
    perm = []
    for sid in sorted(strategies):
        sub = base_ret[base_ret["strategy_id"] == sid].sort_values("date")
        rb = sub["ret"].to_numpy()
        for mname, mfn in (("sharpe", metric_sharpe), ("calmar", metric_calmar)):
            res = permutation_test_paired(
                ra, rb, rf_a, mfn, cfg.stats.mc_permutations, cfg.stats.bootstrap_mean_block, rng
            )
            perm.append({"vs": sid, "metric": mname, **res})

    report = {
        "provenance": {
            "git_commit": manifest.get("git_commit"),
            "config_hash": manifest.get("config_hash"),
            "snapshot_id": manifest.get("snapshot_id"),
            "N": n_trials,
        },
        "dsr": dsr,
        "pbo": pbo,
        "permutation": perm,
    }
    (run_dir / "significance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def _cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m quantcore.experiments.significance_report")
    p.add_argument("--config", required=True)
    p.add_argument("--run-dir", required=True, help="消融 run 目錄")
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    snapshot = load_snapshot(cfg.snapshot)
    report = build_significance_report(cfg, snapshot, args.run_dir)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"DSR={report['dsr']['dsr']:.4f}  PBO={report['pbo']['value']:.4f}")
    print(f"significance.json 已寫入：{args.run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
