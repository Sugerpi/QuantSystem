"""Walk-forward 波動預測評估 + GARCH vs EWMA 比較表（規格 §5.4，Phase 4a AC）。

每 interval 個交易日 refit，產 H 步預測，對齊未來 H 日已實現變異數 proxy，
逐資產算 QLIKE 與 MZ-R²。CLI 產出比較表（本機閘門：需真實快照）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from quantcore.config import load_config
from quantcore.data.hashing import config_hash
from quantcore.data.snapshot import load_snapshot
from quantcore.experiments.tracking import QC_VERSION, git_commit
from quantcore.models.volatility import fit_volatility
from quantcore.models.volatility.eval import mincer_zarnowitz_r2, qlike


def walk_forward_vol_eval(
    returns: pd.Series,
    spec: str,
    *,
    warmup: int,
    interval: int,
    horizon: int,
    ewma_lambda: float,
) -> dict:
    """單資產 walk-forward 評估。

    在每個 refit 點 t（warmup 後，每 interval 步）以 t 前資料 fit，
    forecast 平均變異數 vs t+1..t+horizon 的已實現平均日變異數 proxy。
    """
    r = returns.astype("float64").dropna()
    vals = r.to_numpy()
    n = len(vals)
    forecasts: list[float] = []
    realized: list[float] = []
    n_fallback = 0

    t = warmup
    while t + horizon <= n:
        window = r.iloc[:t]
        outcome = fit_volatility(spec, window, ewma_lambda=ewma_lambda)
        n_fallback += int(outcome.fell_back)
        per_step = outcome.model.forecast(horizon)
        forecast_var = float(per_step.mean())  # 平均每日變異數（還原尺度）
        future = vals[t : t + horizon]
        realized_var = float(np.mean(future**2))  # 已實現平均日變異數 proxy
        # 髒資料（如窗內全零報酬）可致 realized_var == 0 或非有限值：qlike 對此類點
        # 無定義（會 raise），故整批表不應因單一 refit 點而崩潰——僅跳過該點計分，
        # fallback 計數仍照實累計。
        if (
            np.isfinite(forecast_var)
            and np.isfinite(realized_var)
            and forecast_var > 0
            and realized_var > 0
        ):
            forecasts.append(forecast_var)
            realized.append(realized_var)
        t += interval

    fa = np.asarray(forecasts)
    ra = np.asarray(realized)
    return {
        "spec": spec,
        "n_points": len(forecasts),
        "n_fallback": n_fallback,
        "qlike": qlike(ra, fa) if len(forecasts) else float("nan"),
        "mz_r2": mincer_zarnowitz_r2(ra, fa) if len(forecasts) else float("nan"),
    }


def _returns_by_ticker(snapshot: dict) -> dict[str, pd.Series]:
    prices = snapshot["prices"]
    out: dict[str, pd.Series] = {}
    for ticker, grp in prices.groupby("ticker"):
        s = grp.sort_values("date").set_index("date")["adj_close"].astype("float64")
        out[ticker] = s.pct_change().dropna()
    return out


def compare_garch_ewma(config_path: str, out_dir: str) -> pd.DataFrame:
    """對快照每檔資產跑 GARCH 與 EWMA walk-forward，輸出比較表 + provenance。"""
    cfg = load_config(config_path)
    snapshot = load_snapshot(cfg.snapshot)
    rets = _returns_by_ticker(snapshot)

    rows = []
    for ticker in sorted(rets):
        for spec in ("garch_arch", "ewma"):
            # 穩健性粒度為「單一 (ticker, spec) 格」：一格失敗記 error row、不丟其餘資產。
            # 格內單一 refit 點的非退化例外目前不可達（warmup=252 ≥ _min_obs=100，
            # GarchDegenerateError 已由 fit_volatility fallback 接住）。4b 若縮小 window
            # 使其可達，再於此加 point-level 跳過（backlog）。
            try:
                res = walk_forward_vol_eval(
                    rets[ticker],
                    spec,
                    warmup=cfg.universe.min_history_days,
                    interval=cfg.schedule.selection_interval,
                    horizon=cfg.risk.forecast_horizon,
                    ewma_lambda=cfg.risk.ewma_lambda,
                )
                rows.append({"ticker": ticker, **res})
            except Exception as exc:  # noqa: BLE001 — 批次表：單格失敗不應丟失其餘資產，留痕續跑
                rows.append(
                    {
                        "ticker": ticker,
                        "spec": spec,
                        "n_points": 0,
                        "n_fallback": 0,
                        "qlike": float("nan"),
                        "mz_r2": float("nan"),
                        "error": str(exc),
                    }
                )
    table = pd.DataFrame(rows).sort_values(["ticker", "spec"]).reset_index(drop=True)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out / "vol_eval_comparison.parquet", index=False)
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "snapshot_id": snapshot["manifest"]["snapshot_id"],
                "git_commit": git_commit(),
                "config_hash": config_hash(cfg.model_dump(mode="json")),
                "quantcore_version": QC_VERSION,
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return table


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GARCH vs EWMA 波動預測比較表（§5.4）")
    ap.add_argument("--config", default="quantcore/config/default.yaml")
    ap.add_argument("--out", default="runs/vol_eval")
    args = ap.parse_args(argv)
    table = compare_garch_ewma(args.config, args.out)
    print(table.to_string(index=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
