"""快照組裝：決定性 hash、唯讀、MANIFEST、載入往返（全離線，用 fake providers）。"""

import numpy as np
import pandas as pd
import pytest

from quantcore.config import load_config
from quantcore.config.schema import QuantConfig
from quantcore.data.snapshot import create_snapshot, load_snapshot

CONFIG_YAML = "quantcore/config/default.yaml"


def _tidy(ticker, dates, adj):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "ticker": ticker,
            "close": adj,
            "adj_close": adj,
            "volume": [1e6] * len(dates),
        }
    )


class _FakePrimary:
    def __init__(self, menu, dates):
        self._menu, self._dates = menu, dates

    def fetch_prices(self, tickers, start, end):
        adj = list(100 + np.arange(len(self._dates)) * 0.1)
        return pd.concat([_tidy(t, self._dates, adj) for t in tickers], ignore_index=True)

    def fetch_metadata(self, tickers):
        return {t: {"inception_date": "2000-01-03", "name": t} for t in tickers}

    def fetch_series(self, series_id, start, end):
        raise NotImplementedError

    def fetch_dividends(self, ticker, start, end):
        return pd.DataFrame(
            {"date": pd.Series(dtype="datetime64[ns]"), "dividend": pd.Series(dtype="float64")}
        )


class _FakeValidation(_FakePrimary):
    pass


class _FakeRates:
    def __init__(self, dates):
        self._dates = dates

    def fetch_series(self, series_id, start, end):
        return pd.Series(
            [1.5] * len(self._dates), index=pd.to_datetime(self._dates), name=series_id
        )


def _small_config() -> QuantConfig:
    cfg = load_config(CONFIG_YAML)
    small = cfg.model_copy(deep=True)
    small.universe.menu = ["SPY", "QQQ"]
    small.signal.top_k = 2
    return small


def _sessions():
    import exchange_calendars as xcals

    cal = xcals.get_calendar("XNYS")
    s = cal.sessions_in_range(pd.Timestamp("2020-01-02"), pd.Timestamp("2020-02-14"))
    return pd.DatetimeIndex(s).tz_localize(None).normalize()


def test_snapshot_deterministic_hash(tmp_path):
    cfg = _small_config()
    dates = _sessions()

    def build():
        return create_snapshot(
            cfg,
            primary=_FakePrimary(cfg.universe.menu, dates),
            validation=_FakeValidation(cfg.universe.menu, dates),
            rates=_FakeRates(dates),
            out_root=tmp_path / "snapshots",
            build_date=pd.Timestamp("2026-07-13"),
        )

    d1 = build()
    d2 = build()
    assert d1.name == d2.name  # 同資料同日 → 同 hash → 同目錄名


def test_snapshot_files_and_load(tmp_path):
    cfg = _small_config()
    dates = _sessions()
    d = create_snapshot(
        cfg,
        primary=_FakePrimary(cfg.universe.menu, dates),
        validation=_FakeValidation(cfg.universe.menu, dates),
        rates=_FakeRates(dates),
        out_root=tmp_path / "snapshots",
        build_date=pd.Timestamp("2026-07-13"),
    )
    for fn in ("prices.parquet", "rates.parquet", "metadata.json", "MANIFEST.json"):
        assert (d / fn).exists()
    snap = load_snapshot(d)
    assert set(snap["prices"]["ticker"].unique()) == {"SPY", "QQQ"}
    assert snap["manifest"]["content_hashes"]["prices.parquet"]


def test_snapshot_fails_on_calendar_violation(tmp_path):
    cfg = _small_config()
    bad_dates = pd.DatetimeIndex([pd.Timestamp("2020-01-01")])  # 元旦非交易日
    with pytest.raises(ValueError, match="驗證失敗|calendar|§4.3"):
        create_snapshot(
            cfg,
            primary=_FakePrimary(cfg.universe.menu, bad_dates),
            validation=_FakeValidation(cfg.universe.menu, bad_dates),
            rates=_FakeRates(bad_dates),
            out_root=tmp_path / "snapshots",
            build_date=pd.Timestamp("2026-07-13"),
        )


def test_snapshot_fails_when_validation_missing_ticker(tmp_path):
    cfg = _small_config()
    dates = _sessions()

    class _PartialValidation(_FakePrimary):
        def fetch_prices(self, tickers, start, end):
            return super().fetch_prices(["SPY"], start, end)  # 漏掉 QQQ

    with pytest.raises(ValueError, match="驗證來源未回傳"):
        create_snapshot(
            cfg,
            primary=_FakePrimary(cfg.universe.menu, dates),
            validation=_PartialValidation(cfg.universe.menu, dates),
            rates=_FakeRates(dates),
            out_root=tmp_path / "snapshots",
            build_date=pd.Timestamp("2026-07-13"),
        )


def test_load_snapshot_detects_tampering(tmp_path):
    cfg = _small_config()
    dates = _sessions()
    d = create_snapshot(
        cfg,
        primary=_FakePrimary(cfg.universe.menu, dates),
        validation=_FakeValidation(cfg.universe.menu, dates),
        rates=_FakeRates(dates),
        out_root=tmp_path / "snapshots",
        build_date=pd.Timestamp("2026-07-13"),
    )
    tampered = pd.read_parquet(d / "prices.parquet")
    tampered.loc[0, "close"] = tampered.loc[0, "close"] + 999.0
    tampered.to_parquet(d / "prices.parquet", index=False)
    with pytest.raises(ValueError, match="hash 不符"):
        load_snapshot(d)
