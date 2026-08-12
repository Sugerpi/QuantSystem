import pandas as pd
import plotly.graph_objects as go
import pytest

from quantcore.presentation.web import charts


def test_style_dark_sets_black_bg():
    fig = go.Figure()
    charts.style_dark(fig)
    assert fig.layout.paper_bgcolor == "#000000"
    assert fig.layout.plot_bgcolor == "#000000"


def test_to_fragment_is_embeddable_div():
    fig = go.Figure(data=[go.Scatter(y=[1, 2, 3])])
    html = charts.to_fragment(fig, "chart-x")
    assert "chart-x" in html
    assert "<html" not in html.lower()


def _nav_df():
    dates = pd.date_range("2020-01-01", periods=5, freq="D")
    rows = []
    for sid in ("full", "bh_spy"):
        for i, d in enumerate(dates):
            rows.append(
                {"date": d, "strategy_id": sid, "nav": 1.0 + 0.1 * i, "turnover": 0.2, "cost": 0.01}
            )
    return pd.DataFrame(rows)


def _dec_df():
    dates = pd.date_range("2020-01-01", periods=3, freq="D")
    rows = []
    for i, d in enumerate(dates):
        rows.append(
            {
                "strategy_id": "full",
                "decision_date": d,
                "exposure_applied": 0.7 + 0.05 * i,
                "band_blocked": (i == 1),
            }
        )
    return pd.DataFrame(rows)


def _weights_df():
    dates = pd.date_range("2020-01-01", periods=3, freq="D")
    rows = []
    for d in dates:
        for tk, w in (("SPY", 0.6), ("GLD", 0.4)):
            rows.append({"date": d, "strategy_id": "full", "ticker": tk, "weight": w})
    return pd.DataFrame(rows)


def test_nav_log_one_trace_per_strategy_log_axis():
    fig = charts.nav_log(_nav_df(), ["full", "bh_spy"])
    assert len(fig.data) == 2
    assert {t.name for t in fig.data} == {"full", "bh_spy"}
    assert fig.layout.yaxis.type == "log"
    assert fig.layout.paper_bgcolor == "#000000"


def test_drawdown_is_nonpositive():
    fig = charts.drawdown(_nav_df(), ["full"])
    assert len(fig.data) == 1
    assert max(fig.data[0].y) <= 1e-9


def test_exposure_plots_applied():
    fig = charts.exposure(_dec_df(), ["full"])
    assert len(fig.data) == 1
    assert list(fig.data[0].y) == pytest.approx([0.7, 0.75, 0.8])


def test_weight_stack_one_trace_per_ticker():
    fig = charts.weight_stack(_weights_df(), "full")
    assert {t.name for t in fig.data} == {"SPY", "GLD"}
    assert all(t.stackgroup == "w" for t in fig.data)


def test_exposure_band_marks_blocked():
    fig = charts.exposure_band(_dec_df(), "full")
    names = {t.name for t in fig.data}
    assert "E(t)" in names and "band-blocked" in names
    blocked = next(t for t in fig.data if t.name == "band-blocked")
    assert list(blocked.x) == [pd.Timestamp("2020-01-02")]


def test_turnover_cost_dual_series():
    fig = charts.turnover_cost(_nav_df(), "full")
    names = {t.name for t in fig.data}
    assert "turnover" in names and "累積成本" in names


def test_momentum_bar_highlights_selected():
    fig = charts.momentum_bar({"SPY": 0.3, "GLD": 0.1, "TLT": 0.2}, ["SPY", "TLT"])
    assert len(fig.data) == 1
    bar = fig.data[0]
    assert list(bar.x) == ["SPY", "TLT", "GLD"]  # 由高到低
    assert bar.marker.color[0] == charts.UP and bar.marker.color[2] != charts.UP


def test_heatmap_basic():
    fig = charts.heatmap([[1.0, 0.2], [0.2, 1.0]], ["A", "B"], ["A", "B"], zmin=-1, zmax=1)
    assert fig.data[0].type == "heatmap"
    assert list(fig.data[0].x) == ["A", "B"]


def test_line_series_multi():
    fig = charts.line_series({"omega": ([1, 2], [0.1, 0.2]), "beta": ([1, 2], [0.8, 0.85])})
    assert {t.name for t in fig.data} == {"omega", "beta"}


def test_resid_qq_has_points_and_diagonal():
    import numpy as np

    fig = charts.resid_qq(np.array([-1.0, 0.0, 1.0, 2.0, -0.5]))
    assert len(fig.data) == 2  # 散點 + y=x
    assert "y=x" in {t.name for t in fig.data}


def test_resid_acf_lags():
    import numpy as np

    rng = np.random.default_rng(0)
    fig = charts.resid_acf(rng.normal(size=50), lags=10)
    assert fig.data[0].type == "bar"
    assert len(fig.data[0].y) == 10


def test_holdings_heatmap_orders_by_mean_weight():
    fig = charts.holdings_heatmap(_weights_df(), "full")
    assert len(fig.data) == 1
    hm = fig.data[0]
    assert hm.type == "heatmap"
    assert list(hm.y) == ["SPY", "GLD"]  # 平均權重 0.6 > 0.4 → 排前
    assert hm.zmin == 0.0
    assert hm.zmax == pytest.approx(0.6)  # zmax = 資料最大權重（非硬寫 1.0）
    assert len(hm.z) == 2 and len(hm.z[0]) == 3  # (n_ticker, n_date)
    assert fig.layout.yaxis.autorange == "reversed"  # 最高權重置頂


def test_holdings_heatmap_single_ticker_ok():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=2, freq="D"),
            "strategy_id": "bh_spy",
            "ticker": "SPY",
            "weight": [1.0, 1.0],
        }
    )
    fig = charts.holdings_heatmap(df, "bh_spy")
    assert fig.data[0].type == "heatmap"
    assert list(fig.data[0].y) == ["SPY"]


def test_price_with_trades_line_and_marks():
    price = pd.Series(
        [100.0, 101.0, 102.0, 103.0],
        index=pd.date_range("2020-01-01", periods=4, freq="D"),
    )
    tr = pd.DataFrame(
        {
            "execution_date": pd.to_datetime(["2020-01-02", "2020-01-04"]),
            "side": ["buy", "sell"],
            "fill_price": [101.0, 103.0],
        }
    )
    fig = charts.price_with_trades(price, tr, "SPY")
    names = {t.name for t in fig.data}
    assert "SPY price" in names
    assert any("buy" in n for n in names) and any("sell" in n for n in names)
    buy = next(t for t in fig.data if t.name.endswith("buy"))
    assert buy.customdata is not None  # 供點擊跳決策


def test_price_with_weight_dual_panel_keeps_customdata():
    price = pd.Series(
        [100.0, 101.0, 102.0, 103.0],
        index=pd.date_range("2020-01-01", periods=4, freq="D"),
    )
    tr = pd.DataFrame(
        {
            "execution_date": pd.to_datetime(["2020-01-02", "2020-01-04"]),
            "side": ["buy", "sell"],
            "fill_price": [101.0, 103.0],
        }
    )
    wser = pd.Series(
        [0.5, 0.6, 0.6, 0.7],
        index=pd.date_range("2020-01-01", periods=4, freq="D"),
    )
    fig = charts.price_with_weight(price, tr, wser, "SPY")
    names = {t.name for t in fig.data}
    assert "SPY price" in names
    assert "SPY w" in names
    buy = next(t for t in fig.data if t.name.endswith("buy"))
    assert buy.customdata is not None  # 保住點擊跳決策解剖契約
    wtrace = next(t for t in fig.data if t.name == "SPY w")
    assert wtrace.yaxis == "y2"  # 權重面積在下列


def test_price_with_weight_no_price_uses_fill():
    tr = pd.DataFrame(
        {
            "execution_date": pd.to_datetime(["2020-01-02"]),
            "side": ["buy"],
            "fill_price": [101.0],
        }
    )
    wser = pd.Series([0.5, 0.6], index=pd.date_range("2020-01-01", periods=2, freq="D"))
    fig = charts.price_with_weight(None, tr, wser, "SPY")
    buy = next(t for t in fig.data if t.name.endswith("buy"))
    assert list(buy.y) == [101.0]
