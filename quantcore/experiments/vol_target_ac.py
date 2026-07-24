"""σ*±2% AC 條件式量測（設計文件 §4）。純讀 run 產物，不重跑回測。

voltarget_only（無 absmom）= 全期乾淨測；full = 日層級閾值子集（管轄日的
absmom 轉現金比例 ≤ 閾值）。另報嚴格版（比例=0）當敏感度。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


def realized_annual_vol(nav: pd.Series) -> float:
    """實現年化波動 = std(日報酬, ddof=1) × √252。"""
    r = nav.pct_change().dropna().to_numpy()
    if len(r) < 2:
        return float("nan")
    return float(np.std(r, ddof=1) * np.sqrt(252))


def _cash_fraction(absmom_json: str, w_risky_json: str) -> float:
    """該次 selection 的 absmom 轉現金比例 = Σ_{absmom False} w_risky。"""
    absmom = json.loads(absmom_json)
    w_risky = json.loads(w_risky_json)
    return float(sum(w for t, w in w_risky.items() if not absmom.get(t, False)))


def full_conditional_realized_vol(
    decisions: pd.DataFrame, nav: pd.Series, threshold: float
) -> dict:
    """full 的條件式實現波動：只納入「管轄日 absmom 轉現金比例 ≤ threshold」的日子。

    decisions：full 的決策表（含 event/execution_date/absmom/w_risky）。
    nav：full 的 nav，DatetimeIndex。
    """
    sel = decisions[
        (decisions["strategy_id"] == "full") & (decisions["event"] == "selection")
    ].copy()
    sel["exec"] = pd.to_datetime(sel["execution_date"])
    sel = sel.dropna(subset=["exec"]).sort_values("exec")
    sel["cash_frac"] = [
        _cash_fraction(a, w) for a, w in zip(sel["absmom"], sel["w_risky"], strict=True)
    ]
    exec_dates = sel["exec"].to_numpy()
    cash_fracs = sel["cash_frac"].to_numpy()

    ret = nav.pct_change().dropna()
    ret_days = ret.index.to_numpy()
    # 每個報酬日的管轄 selection = 最後一個 exec ≤ 該日
    ret_pos = np.searchsorted(exec_dates, ret_days, side="right") - 1
    included = np.array([p >= 0 and cash_fracs[p] <= threshold for p in ret_pos])
    sub = ret[included]
    n_total = int(len(ret))
    n_included = int(included.sum())
    vol = float(np.std(sub.to_numpy(), ddof=1) * np.sqrt(252)) if n_included >= 2 else float("nan")
    return {
        "realized_vol": vol,
        "n_included": n_included,
        "n_total": n_total,
        "threshold": threshold,
    }


def measure_vol_target_ac(run_dir: str | Path, threshold: float) -> dict:
    """讀 run 目錄，回 voltarget_only（全期）與 full（閾值+嚴格）的實現波動與 AC 判定。"""
    run = Path(run_dir)
    nav = pd.read_parquet(run / "nav.parquet")
    dec = pd.read_parquet(run / "decisions.parquet")

    def _nav_of(sid: str) -> pd.Series:
        n = nav[nav["strategy_id"] == sid].sort_values("date")
        return pd.Series(n["nav"].to_numpy(), index=pd.to_datetime(n["date"].to_numpy()))

    def _pass(v: float) -> bool:
        return bool(0.08 <= v <= 0.12) if np.isfinite(v) else False

    vt_vol = realized_annual_vol(_nav_of("voltarget_only"))
    full_nav = _nav_of("full")
    full_thr = full_conditional_realized_vol(dec, full_nav, threshold)
    full_strict = full_conditional_realized_vol(dec, full_nav, 0.0)
    return {
        "voltarget_only": {"realized_vol": vt_vol, "passes": _pass(vt_vol)},
        "full_threshold": {**full_thr, "passes": _pass(full_thr["realized_vol"])},
        "full_strict": {**full_strict, "passes": _pass(full_strict["realized_vol"])},
    }
