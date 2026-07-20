"""合成迷你快照：INV 測試專用，全離線、不碰 snapshots/。

回傳結構與 quantcore.data.snapshot.load_snapshot() 相同（prices/rates/metadata/manifest），
使引擎測試不需要真實快照即可在 CI 執行。
"""

from __future__ import annotations

import pandas as pd


def make_dates(n: int, start: str = "2020-01-02") -> pd.DatetimeIndex:
    """n 個連續「交易日」。合成資料不需真實 NYSE 日曆——引擎只認序列順序。"""
    return pd.bdate_range(start=start, periods=n)


def make_snapshot(
    prices_by_ticker: dict[str, list[float]],
    dates: pd.DatetimeIndex,
    dtb3_percent: float = 2.52,
) -> dict:
    """由每檔的 adj_close 序列組出快照 dict。

    prices_by_ticker 的序列長度可短於 dates：視為該檔較晚上市，
    對齊到 dates 的「尾端」（最後一筆對齊最後一天）。
    dtb3_percent 預設 2.52 → 日利率 0.0252/252 = 0.0001（整數，便於手算）。
    """
    frames = []
    for ticker, series in sorted(prices_by_ticker.items()):
        d = dates[len(dates) - len(series) :]
        frames.append(
            pd.DataFrame(
                {
                    "date": d,
                    "ticker": ticker,
                    "close": series,
                    "adj_close": series,
                    "volume": [1e6] * len(series),
                }
            )
        )
    prices = pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"])
    prices = prices.reset_index(drop=True)
    rates = pd.DataFrame({"date": dates, "DTB3": [dtb3_percent] * len(dates)})
    return {
        "prices": prices,
        "rates": rates,
        "metadata": {"tickers": {}, "overrides": [], "sources": {}},
        "manifest": {"snapshot_id": "synthetic", "content_hashes": {}},
    }


def make_cfg(menu: list[str], **overrides: dict):
    """由 default.yaml 生一份測試 config，套用巢狀覆寫後重新驗證。

    overrides 以巢狀 dict 給，如 make_cfg(["SPY"], signal={"top_k": 2}).
    """
    from quantcore.config import QuantConfig, load_config

    raw = load_config("quantcore/config/default.yaml").model_dump(mode="json")
    raw["universe"]["menu"] = list(menu)
    for section, values in overrides.items():
        raw[section].update(values)
    return QuantConfig.model_validate(raw)
