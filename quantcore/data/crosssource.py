"""跨源交叉驗證（規格 §4.5）。比對日報酬（非價格水準）。

同一資產於「對齊後共同交易日」的 window_days 交易日窗內差異 >= window_max_hits 筆 → 快照建立失敗。
門檻由呼叫端自 config.data_quality 傳入。

可選第三源（arbiter，如 Stooq）：僅提供未還原股息的純價格 close，用於在 primary/validation
不一致時「少數服從多數」裁決——哪一方的報酬與 arbiter 較接近即視為正確方，另一方為離群值。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class CrossSourceResult:
    passed: bool
    report: list[dict] = field(default_factory=list)  # 所有超門檻的差異
    failed_assets: list[str] = field(default_factory=list)
    overrides: list[dict] = field(
        default_factory=list
    )  # 仲裁後有明確裁決結果的紀錄（供 metadata 溯源）


def _returns(prices: pd.DataFrame) -> pd.DataFrame:
    df = prices.sort_values(["ticker", "date"]).copy()
    df["ret"] = df.groupby("ticker")["adj_close"].pct_change()
    return df[["date", "ticker", "ret"]]


def _price_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """仲裁源（Stooq）僅有未還原股息的純價格，報酬由 close 計算，非 adj_close。"""
    df = prices.sort_values(["ticker", "date"]).copy()
    df["ret"] = df.groupby("ticker")["close"].pct_change()
    return df[["date", "ticker", "ret"]]


def cross_validate(
    primary: pd.DataFrame,
    validation: pd.DataFrame,
    *,
    discrepancy_bps: float,
    window_days: int,
    window_max_hits: int,
    arbiter: pd.DataFrame | None = None,
) -> CrossSourceResult:
    rp = _returns(primary).rename(columns={"ret": "ret_p"})
    rv = _returns(validation).rename(columns={"ret": "ret_v"})
    merged = rp.merge(rv, on=["date", "ticker"], how="inner").dropna(subset=["ret_p", "ret_v"])
    thresh = discrepancy_bps / 1e4
    merged["diff"] = (merged["ret_p"] - merged["ret_v"]).abs()

    if arbiter is not None:
        ra = _price_returns(arbiter).rename(columns={"ret": "ret_a"})
        merged = merged.merge(ra, on=["date", "ticker"], how="left")
    else:
        merged["ret_a"] = float("nan")

    report: list[dict] = []
    overrides: list[dict] = []
    failed: list[str] = []
    # window_days 以「對齊後共同交易日」為軸（reset_index 後的序位即交易日序），非日曆日。
    # 序位必須以該 ticker「全部對齊列」計算（而非僅計入窗口計數的子集），
    # 才能正確量測被計入之差異彼此間的交易日間隔。
    for ticker, g in merged.sort_values("date").groupby("ticker"):
        g = g.reset_index(drop=True)
        flagged = g[g["diff"] > thresh]

        counted_positions: list[int] = []
        for pos, r in flagged.iterrows():
            verdict = "unresolved"
            ret_a = r["ret_a"]
            if pd.notna(ret_a):
                dp = abs(r["ret_p"] - ret_a)
                dv = abs(r["ret_v"] - ret_a)
                if dp <= thresh and dv > thresh:
                    verdict = "validation_outlier"  # primary 與仲裁一致 → validation 為離群值
                elif dv <= thresh and dp > thresh:
                    verdict = "primary_outlier"  # validation 與仲裁一致 → primary 為離群值
                # 其餘情況（雙方皆與仲裁不一致，或雙方皆與仲裁一致）維持 unresolved

            row = {
                "ticker": ticker,
                "date": str(r["date"].date()),
                "ret_p": r["ret_p"],
                "ret_v": r["ret_v"],
                "diff": r["diff"],
                "verdict": verdict,
            }
            if pd.notna(ret_a):
                row["ret_a"] = ret_a
            report.append(row)

            if verdict != "unresolved":
                overrides.append(
                    {
                        "ticker": ticker,
                        "date": row["date"],
                        "verdict": verdict,
                        "ret_primary": r["ret_p"],
                        "ret_validation": r["ret_v"],
                        "ret_arbiter": ret_a if pd.notna(ret_a) else None,
                    }
                )

            # 裁決為 validation_outlier（Tiingo 誤差已被少數服從多數排除）者不計入窗口失敗計數。
            if verdict != "validation_outlier":
                counted_positions.append(pos)

        positions = pd.array(counted_positions, dtype="int64").to_numpy()
        for i in range(len(positions)):
            hits = ((positions >= positions[i]) & (positions < positions[i] + window_days)).sum()
            if hits >= window_max_hits:
                failed.append(ticker)
                break

    report.sort(key=lambda x: (x["ticker"], x["date"]))
    overrides.sort(key=lambda x: (x["ticker"], x["date"]))
    return CrossSourceResult(
        passed=not failed,
        report=report,
        failed_assets=sorted(set(failed)),
        overrides=overrides,
    )
