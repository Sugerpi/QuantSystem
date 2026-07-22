"""合成迷你快照：INV 測試專用，全離線、不碰 snapshots/。

回傳結構與 quantcore.data.snapshot.load_snapshot() 相同（prices/rates/metadata/manifest），
使引擎測試不需要真實快照即可在 CI 執行。
"""

from __future__ import annotations

import numpy as np
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
    """由 default.yaml 生一份測試 config，套用覆寫後重新驗證。

    overrides 以「區塊 dict」給，如 make_cfg(["SPY"], signal={"top_k": 2})；
    只支援 dict 型別的區塊（signal/risk/universe/... ），一層淺合併（非遞迴）。
    便利性：套用 menu 與 overrides 後，top_k 會夾到 ≤ 選單檔數，讓小型合成選單
    不必每次都手動覆寫 top_k 也能通過 schema 驗證。
    """
    from quantcore.config import QuantConfig, load_config

    raw = load_config("quantcore/config/default.yaml").model_dump(mode="json")
    raw["universe"]["menu"] = list(menu)
    for section, values in overrides.items():
        raw[section].update(values)
    raw["signal"]["top_k"] = min(raw["signal"]["top_k"], len(raw["universe"]["menu"]))
    return QuantConfig.model_validate(raw)


def make_garch_t_returns(
    n: int,
    omega: float,
    alpha: float,
    beta: float,
    nu: float,
    seed: int,
) -> pd.Series:
    """已知參數 GARCH(1,1)-t 報酬序列（§8：合成資料驗證估計器正確性）。

    Student-t(ν) 創新標準化為單位變異數。回傳原始報酬尺度的 pd.Series
    （index 為連續 bdate）。α+β<1 由呼叫端保證平穩。
    """
    rng = np.random.default_rng(seed)
    z = rng.standard_t(nu, size=n) * np.sqrt((nu - 2) / nu)  # 單位變異數
    var = np.empty(n, dtype="float64")
    ret = np.empty(n, dtype="float64")
    var[0] = omega / (1 - alpha - beta)  # 無條件變異數起始
    ret[0] = np.sqrt(var[0]) * z[0]
    for t in range(1, n):
        var[t] = omega + alpha * ret[t - 1] ** 2 + beta * var[t - 1]
        ret[t] = np.sqrt(var[t]) * z[t]
    return pd.Series(ret, index=pd.bdate_range("2000-01-03", periods=n))
