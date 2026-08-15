"""AC5 決策分析：曝險帶 absolute vs log 是否值得翻預設（設計文件 §8 AC5）。

比 exposure_band_frontier.run_frontier 更嚴：對 voltarget_only + full 的寬帶寬網格，
各格跑一次真回測並**保留日報酬**，輸出 turnover / σ* 追蹤誤差 / 成本拖累(bps/年) / Sharpe
前沿；再對每策略取 turnover 最接近的一對 absolute/log，做 stationary block bootstrap
配對 Sharpe 差 CI（比照 §6.3、Phase 4c/5a/5b；seed 走 config 守 INV-6）。

結論（2026-08-14，default.yaml 快照，寬網格 absolute{0.05-0.22}/log{0.10-0.40}）：
兩策略在匹配 turnover 下 log−absolute 的 Sharpe 差點估計 ~±0.004、95% CI 皆含 0、成本差
<1 bps/年、追蹤誤差兩 mode 皆 <0.5%——**無統計顯著差異，維持 default=absolute**，log 留
config 選項。與 DCC/ERC/garch_own 一致：加的複雜度未自證其值 → 簡單者續為預設。

純分析、不寫 runs/；experiments 層（允許 import backtest/config/data）。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantcore.backtest.clock import EventClock
from quantcore.backtest.engine import run_strategy
from quantcore.backtest.metrics import (
    compute_metrics,
    metric_sharpe,
    paired_metric_diff_ci,
    stationary_bootstrap_indices,
)
from quantcore.backtest.strategies import STRATEGIES
from quantcore.config import QuantConfig, load_config
from quantcore.data.snapshot import load_snapshot

_DAYS_PER_YEAR = 252
_FRONT_COLS = ["strategy_id", "mode", "band", "turnover", "tracking_error", "cost_bps_yr", "sharpe"]


def matched_turnover_pair(front: pd.DataFrame, strategy_id: str) -> tuple[pd.Series, pd.Series]:
    """回該策略下 turnover 最接近的 (absolute 列, log 列)。前沿須含該策略兩 mode 各≥1 格。"""
    sub = front[front["strategy_id"] == strategy_id]
    a = sub[sub["mode"] == "absolute"]
    lg = sub[sub["mode"] == "log"]
    if a.empty or lg.empty:
        raise ValueError(f"{strategy_id} 缺 absolute 或 log 格，無法配對")
    best: tuple[float, pd.Series, pd.Series] | None = None
    for _, ar in a.iterrows():
        for _, lr in lg.iterrows():
            d = abs(float(ar["turnover"]) - float(lr["turnover"]))
            if best is None or d < best[0]:
                best = (d, ar, lr)
    assert best is not None
    return best[1], best[2]


@dataclass(frozen=True)
class _Variant:
    metrics: dict
    ret: np.ndarray  # 日報酬（bootstrap 用）
    rf: np.ndarray  # 對齊的日無風險利率


def _variant_cfg(cfg: QuantConfig, mode: str, band: float) -> QuantConfig:
    risk = cfg.risk.model_copy(update={"exposure_band_mode": mode, "exposure_band": band})
    return cfg.model_copy(update={"risk": risk})


def _clock(cfg: QuantConfig, snapshot: dict, sid: str) -> EventClock:
    days = pd.DatetimeIndex(sorted(snapshot["prices"]["date"].unique()))
    days = days[days >= pd.Timestamp(cfg.backtest.start)]
    warmup = STRATEGIES[sid](cfg).warmup_days
    return EventClock(
        days, warmup, cfg.schedule.selection_interval, cfg.schedule.exposure_check_interval
    )


def _daily_rate(snapshot: dict, dates: pd.Series) -> pd.Series:
    return (
        snapshot["rates"].set_index("date")["DTB3"].reindex(dates).ffill().bfill()
        / 100.0
        / _DAYS_PER_YEAR
    )


def _run_variant(cfg: QuantConfig, snapshot: dict, clock: EventClock, sid: str) -> _Variant:
    strat = STRATEGIES[sid](cfg)
    nav_df, weights, _dec, _tr = run_strategy(snapshot, clock, strat, cfg)
    rate = _daily_rate(snapshot, nav_df["date"]).reset_index(drop=True)
    nav = nav_df["nav"].reset_index(drop=True)
    m = compute_metrics(
        nav=nav,
        rate_daily=rate,
        total_turnover=float(nav_df["turnover"].sum()),
        total_cost=float(nav_df["cost"].sum()),
        weights=weights,
    )
    return _Variant(metrics=m, ret=nav.pct_change().dropna().to_numpy(), rf=rate.to_numpy()[1:])


def run_ac5(
    config_path: str,
    strategies: tuple[str, ...] = ("voltarget_only", "full"),
    abs_bands: tuple[float, ...] = (0.05, 0.08, 0.12, 0.16, 0.22),
    log_bands: tuple[float, ...] = (0.10, 0.15, 0.22, 0.30, 0.40),
) -> pd.DataFrame:
    """跑寬網格 + 成本 + 匹配-turnover 配對 Sharpe bootstrap，印前沿與判定，回前沿表。"""
    cfg = load_config(config_path)
    snapshot = load_snapshot(cfg.snapshot)
    sigma_star = cfg.risk.vol_target_annual

    rows: list[dict] = []
    variants: dict[tuple[str, str, float], _Variant] = {}
    for sid in strategies:
        clock = _clock(cfg, snapshot, sid)
        for mode, bands in (("absolute", abs_bands), ("log", log_bands)):
            for b in bands:
                v = _run_variant(_variant_cfg(cfg, mode, b), snapshot, clock, sid)
                variants[(sid, mode, b)] = v
                rows.append(
                    {
                        "strategy_id": sid,
                        "mode": mode,
                        "band": b,
                        "turnover": v.metrics["annualized_turnover"],
                        "tracking_error": abs(v.metrics["annualized_vol"] - sigma_star),
                        "cost_bps_yr": v.metrics["cost_drag_bps_per_year"],
                        "sharpe": v.metrics["sharpe"],
                    }
                )
    front = pd.DataFrame(rows, columns=_FRONT_COLS)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("=== AC5 前沿（GARCH 全歷史；換手率↓ 追蹤誤差↓ 成本↓）===")
    print(front.sort_values(["strategy_id", "mode", "band"]).to_string(index=False))

    print("\n=== 匹配-turnover 配對 Sharpe bootstrap（log − absolute；CI 含 0 = 無顯著差異）===")
    for sid in strategies:
        ar, lr = matched_turnover_pair(front, sid)
        va = variants[(sid, "absolute", float(ar["band"]))]
        vl = variants[(sid, "log", float(lr["band"]))]
        n = min(len(va.ret), len(vl.ret))
        rng = np.random.default_rng(cfg.seed)  # INV-6
        idx = stationary_bootstrap_indices(
            n, cfg.stats.bootstrap_mean_block, cfg.stats.bootstrap_reps, rng
        )
        res = paired_metric_diff_ci(
            vl.ret[:n], va.ret[:n], vl.rf[:n], metric_sharpe, idx, cfg.stats.bootstrap_alpha
        )
        verdict = "顯著≠0" if res["excludes_zero"] else "含 0（無顯著差異）"
        print(
            f"\n  {sid}: absolute(band={ar['band']:.2f}, turn={ar['turnover']:.3f}, "
            f"sharpe={ar['sharpe']:.3f}, cost={ar['cost_bps_yr']:.1f}bps) vs "
            f"log(band={lr['band']:.2f}, turn={lr['turnover']:.3f}, "
            f"sharpe={lr['sharpe']:.3f}, cost={lr['cost_bps_yr']:.1f}bps)"
        )
        print(
            f"    Sharpe 差(log−abs) point={res['point']:+.4f} "
            f"CI=[{res['lo']:+.4f}, {res['hi']:+.4f}] → {verdict}"
        )
    return front


def _cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m quantcore.experiments.ac5_exposure_band")
    p.add_argument("--config", default="quantcore/config/default.yaml")
    args = p.parse_args(argv)
    run_ac5(args.config)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
