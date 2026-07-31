"""Plotly 圖表：深色 Bloomberg 風統一樣式 + 可嵌入片段。

不 import 引擎（§2.2）。顏色 token 集中此處，供各頁圖表沿用。
"""

from __future__ import annotations

import plotly.graph_objects as go

BG = "#000000"
FG = "#d8d8d3"
GRID = "#1c1c1c"
AMBER = "#ff8c1a"
UP = "#26a65b"
DOWN = "#e0483e"
COLORWAY = ["#e8b64a", "#3a6ea5", "#26a65b", "#7a5aa5", "#ff8c1a", "#8a8a82"]


def style_dark(fig: go.Figure) -> go.Figure:
    """套用深色主題（黑底、細格線、等寬字、Bloomberg 色盤）。"""
    fig.update_layout(
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(color=FG, family="ui-monospace, Menlo, monospace", size=12),
        colorway=COLORWAY,
        margin=dict(l=48, r=16, t=24, b=32),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    return fig


def to_fragment(fig: go.Figure, div_id: str) -> str:
    """轉成可嵌入 HTML 片段（不含 plotly.js，不含 <html>）。plotly.js 由 base.html 一次載入。"""
    return fig.to_html(include_plotlyjs=False, full_html=False, div_id=div_id)
