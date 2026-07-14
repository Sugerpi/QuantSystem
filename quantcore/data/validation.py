"""資料驗證（規格 §4.3）。純函數；任一 hard_fail 即拒絕產出快照。

門檻一律由呼叫端（快照流程）自 config.data_quality 傳入，模組不內嵌數字。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class ValidationResult:
    name: str
    passed: bool
    hard_fail: bool
    message: str = ""
    report: list[dict] = field(default_factory=list)


def _per_ticker_returns(prices: pd.DataFrame, price_col: str) -> pd.DataFrame:
    df = prices.sort_values(["ticker", "date"]).copy()
    df["ret"] = df.groupby("ticker")[price_col].pct_change()
    return df


def check_total_return(
    prices: pd.DataFrame, dividends: pd.DataFrame, tol_bps: float
) -> ValidationResult:
    """§4.3-1：除息日 adj 報酬 ≈ close 報酬 + 股息/前收盤（容差內）。"""
    df = prices.sort_values("date").copy()
    df["close_ret"] = df["close"].pct_change()
    df["adj_ret"] = df["adj_close"].pct_change()
    df["prev_close"] = df["close"].shift(1)
    div = dividends.set_index("date")["dividend"]
    tol = tol_bps / 1e4
    bad = []
    for _, row in df.dropna(subset=["close_ret", "adj_ret"]).iterrows():
        d = row["date"]
        div_amt = float(div.get(d, 0.0))
        if div_amt == 0.0:
            continue
        expected_adj = row["close_ret"] + div_amt / row["prev_close"]
        if abs(row["adj_ret"] - expected_adj) > tol:
            bad.append({"date": str(d.date()), "adj_ret": row["adj_ret"], "expected": expected_adj})
    passed = not bad
    return ValidationResult(
        "total_return",
        passed,
        hard_fail=not passed,
        report=bad,
        message="" if passed else f"{len(bad)} 個除息日總報酬不一致",
    )


def check_extreme_returns(prices: pd.DataFrame, threshold: float) -> ValidationResult:
    """§4.3-2：單日 |r| > threshold 的列入人工確認清單（軟性）。"""
    df = _per_ticker_returns(prices, "adj_close")
    hits = df[df["ret"].abs() > threshold]
    report = [
        {"ticker": r["ticker"], "date": str(r["date"].date()), "ret": r["ret"]}
        for _, r in hits.iterrows()
    ]
    passed = not report
    return ValidationResult(
        "extreme_returns",
        passed,
        hard_fail=False,
        report=report,
        message="" if passed else f"{len(report)} 筆極端值待人工確認",
    )


def check_missing_values(prices: pd.DataFrame, max_consecutive_nan: int) -> ValidationResult:
    """§4.3-3：上市後序列中間 NaN → 報告；連續 > 上限 → 拒絕。"""
    report = []
    hard = False
    for ticker, g in prices.sort_values("date").groupby("ticker"):
        s = g["adj_close"].to_numpy()
        # 去除上市前的前導 NaN
        first_valid = np.argmax(~np.isnan(s)) if (~np.isnan(s)).any() else len(s)
        core = s[first_valid:]
        run = 0
        max_run = 0
        for v in core:
            run = run + 1 if np.isnan(v) else 0
            max_run = max(max_run, run)
        if max_run > 0:
            report.append({"ticker": ticker, "max_consecutive_nan": int(max_run)})
        if max_run > max_consecutive_nan:
            hard = True
    passed = not hard
    return ValidationResult(
        "missing_values",
        passed,
        hard_fail=hard,
        report=report,
        message="" if passed else "存在超過上限的連續缺值",
    )


def check_calendar(prices: pd.DataFrame, calendar) -> ValidationResult:
    """§4.3-4：所有日期 ∈ NYSE 交易日曆。"""
    dates = pd.to_datetime(prices["date"]).dt.normalize().unique()
    lo, hi = dates.min(), dates.max()
    sessions = set(calendar.sessions_in_range(lo, hi))
    bad = [str(pd.Timestamp(d).date()) for d in dates if pd.Timestamp(d) not in sessions]
    passed = not bad
    return ValidationResult(
        "calendar",
        passed,
        hard_fail=not passed,
        report=[{"date": d} for d in bad],
        message="" if passed else f"{len(bad)} 個非交易日日期",
    )


def check_monotonic(prices: pd.DataFrame) -> ValidationResult:
    """§4.3-5：每檔資產日期嚴格遞增、無重複。"""
    bad = []
    for ticker, g in prices.groupby("ticker"):
        d = pd.to_datetime(g["date"])
        if d.duplicated().any() or not d.is_monotonic_increasing:
            bad.append(ticker)
    passed = not bad
    return ValidationResult(
        "monotonic",
        passed,
        hard_fail=not passed,
        report=[{"ticker": t} for t in bad],
        message="" if passed else f"{len(bad)} 檔日期非單調或重複",
    )
