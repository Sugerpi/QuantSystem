"""跨源交叉驗證（規格 §4.5）。比對日報酬（非價格水準）。

同一資產 window_days 交易日窗內差異 >= window_max_hits 筆 → 快照建立失敗。
門檻由呼叫端自 config.data_quality 傳入。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class CrossSourceResult:
    passed: bool
    report: list[dict] = field(default_factory=list)  # 所有超門檻的差異
    failed_assets: list[str] = field(default_factory=list)


def _returns(prices: pd.DataFrame) -> pd.DataFrame:
    df = prices.sort_values(["ticker", "date"]).copy()
    df["ret"] = df.groupby("ticker")["adj_close"].pct_change()
    return df[["date", "ticker", "ret"]]


def cross_validate(
    primary: pd.DataFrame,
    validation: pd.DataFrame,
    *,
    discrepancy_bps: float,
    window_days: int,
    window_max_hits: int,
) -> CrossSourceResult:
    rp = _returns(primary).rename(columns={"ret": "ret_p"})
    rv = _returns(validation).rename(columns={"ret": "ret_v"})
    merged = rp.merge(rv, on=["date", "ticker"], how="inner").dropna(subset=["ret_p", "ret_v"])
    thresh = discrepancy_bps / 1e4
    merged["diff"] = (merged["ret_p"] - merged["ret_v"]).abs()
    flagged = merged[merged["diff"] > thresh].copy()

    report = [
        {
            "ticker": r["ticker"],
            "date": str(r["date"].date()),
            "ret_p": r["ret_p"],
            "ret_v": r["ret_v"],
            "diff": r["diff"],
        }
        for _, r in flagged.sort_values(["ticker", "date"]).iterrows()
    ]

    failed = []
    for ticker, g in flagged.sort_values("date").groupby("ticker"):
        dates = g["date"].reset_index(drop=True)
        # 任一 window_days 日窗內達到 window_max_hits 筆即失敗
        for i in range(len(dates)):
            window_hi = dates[i] + pd.Timedelta(days=window_days)
            hits = ((dates >= dates[i]) & (dates < window_hi)).sum()
            if hits >= window_max_hits:
                failed.append(ticker)
                break

    return CrossSourceResult(passed=not failed, report=report, failed_assets=sorted(set(failed)))
