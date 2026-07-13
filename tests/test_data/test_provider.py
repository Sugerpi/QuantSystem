"""DataProvider Protocol 與 tidy schema。"""

import pandas as pd

from quantcore.data.provider import PRICE_COLUMNS, DataProvider, empty_prices


class _FakeProvider:
    def fetch_prices(self, tickers, start, end):
        return empty_prices()

    def fetch_metadata(self, tickers):
        return {t: {"inception_date": "2000-01-01", "name": t} for t in tickers}

    def fetch_series(self, series_id, start, end):
        return pd.Series(dtype="float64", name=series_id)


def test_price_columns_order():
    assert PRICE_COLUMNS == ["date", "ticker", "close", "adj_close", "volume"]


def test_empty_prices_has_schema():
    df = empty_prices()
    assert list(df.columns) == PRICE_COLUMNS


def test_fake_satisfies_protocol():
    p = _FakeProvider()
    assert isinstance(p, DataProvider)
    assert isinstance(p.fetch_metadata(["SPY"]), dict)


def test_incomplete_provider_fails_protocol():
    class _Broken:  # 缺 fetch_series
        def fetch_prices(self, tickers, start, end):
            return empty_prices()

        def fetch_metadata(self, tickers):
            return {}

    assert not isinstance(_Broken(), DataProvider)
