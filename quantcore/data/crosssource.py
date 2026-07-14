"""跨源交叉驗證（規格 §4.5）。比對日報酬（非價格水準）。

同一資產於「對齊後共同交易日」的 window_days 交易日窗內差異 >= window_max_hits 筆 → 快照建立失敗。
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

    report: list[dict] = []
    failed: list[str] = []
    # window_days 以「對齊後共同交易日」為軸（reset_index 後的序位即交易日序），非日曆日
    for ticker, g in merged.sort_values("date").groupby("ticker"):
        g = g.reset_index(drop=True)
        flagged = g[g["diff"] > thresh]
        for _, r in flagged.iterrows():
            report.append(
                {
                    "ticker": ticker,
                    "date": str(r["date"].date()),
                    "ret_p": r["ret_p"],
                    "ret_v": r["ret_v"],
                    "diff": r["diff"],
                }
            )
        positions = flagged.index.to_numpy()  # 交易日序位置（g 已 reset_index(drop=True)）
        for i in range(len(positions)):
            hits = ((positions >= positions[i]) & (positions < positions[i] + window_days)).sum()
            if hits >= window_max_hits:
                failed.append(ticker)
                break

    report.sort(key=lambda x: (x["ticker"], x["date"]))
    return CrossSourceResult(passed=not failed, report=report, failed_assets=sorted(set(failed)))
