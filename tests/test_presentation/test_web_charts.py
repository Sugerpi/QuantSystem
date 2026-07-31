import plotly.graph_objects as go

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
