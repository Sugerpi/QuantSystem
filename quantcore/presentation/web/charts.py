"""Plotly 圖表：深色 Bloomberg 風統一樣式 + 可嵌入片段。

不 import 引擎（§2.2）。顏色 token 集中此處，供各頁圖表沿用。
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

BG = "#000000"
FG = "#d8d8d3"
GRID = "#1c1c1c"
AMBER = "#ff8c1a"
UP = "#26a65b"
DOWN = "#e0483e"
BLUE = "#3a6ea5"
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


def nav_log(nav: pd.DataFrame, strategies: list[str]) -> go.Figure:
    """NAV 對數疊圖，每策略一線。"""
    fig = go.Figure()
    for sid in strategies:
        sub = nav[nav["strategy_id"] == sid].sort_values("date")
        fig.add_trace(go.Scatter(x=sub["date"], y=sub["nav"], name=sid, mode="lines"))
    fig.update_yaxes(type="log", title="NAV（對數）")
    return style_dark(fig)


def drawdown(nav: pd.DataFrame, strategies: list[str]) -> go.Figure:
    """回撤（nav/cummax − 1），每策略一線。"""
    fig = go.Figure()
    for sid in strategies:
        sub = nav[nav["strategy_id"] == sid].sort_values("date")
        cummax = sub["nav"].cummax()
        fig.add_trace(
            go.Scatter(x=sub["date"], y=sub["nav"] / cummax - 1.0, name=sid, mode="lines")
        )
    fig.update_yaxes(title="drawdown")
    return style_dark(fig)


def exposure(decisions: pd.DataFrame, strategies: list[str]) -> go.Figure:
    """曝險 E(t)（decisions.exposure_applied），每策略一線。"""
    fig = go.Figure()
    for sid in strategies:
        sub = decisions[
            (decisions["strategy_id"] == sid) & decisions["exposure_applied"].notna()
        ].sort_values("decision_date")
        if not sub.empty:
            fig.add_trace(
                go.Scatter(
                    x=sub["decision_date"], y=sub["exposure_applied"], name=sid, mode="lines"
                )
            )
    fig.update_yaxes(title="E(t)")
    return style_dark(fig)


def weight_stack(weights: pd.DataFrame, strategy: str) -> go.Figure:
    """權重堆疊面積（單一策略，含現金若有）。"""
    w = weights[weights["strategy_id"] == strategy]
    wide = w.pivot_table(
        index="date", columns="ticker", values="weight", fill_value=0.0
    ).sort_index()
    fig = go.Figure()
    for col in wide.columns:
        fig.add_trace(
            go.Scatter(x=wide.index, y=wide[col], name=str(col), stackgroup="w", mode="lines")
        )
    return style_dark(fig)


def exposure_band(decisions: pd.DataFrame, strategy: str) -> go.Figure:
    """曝險軌跡 + band_blocked 事件標記（單一策略）。"""
    d = decisions[
        (decisions["strategy_id"] == strategy) & decisions["exposure_applied"].notna()
    ].sort_values("decision_date")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=d["decision_date"], y=d["exposure_applied"], name="E(t)", mode="lines")
    )
    blocked = d[d["band_blocked"] == True]  # noqa: E712
    if not blocked.empty:
        fig.add_trace(
            go.Scatter(
                x=blocked["decision_date"],
                y=blocked["exposure_applied"],
                name="band-blocked",
                mode="markers",
                marker_symbol="x",
                marker_color=DOWN,
            )
        )
    fig.update_yaxes(title="E(t)")
    return style_dark(fig)


def turnover_cost(nav: pd.DataFrame, strategy: str) -> go.Figure:
    """每次再平衡換手率（bar）+ 累積成本（右軸線）。"""
    n = nav[nav["strategy_id"] == strategy].sort_values("date")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=n["date"], y=n["turnover"], name="turnover", marker_color=BLUE))
    fig.add_trace(
        go.Scatter(x=n["date"], y=n["cost"].cumsum(), name="累積成本", yaxis="y2", mode="lines")
    )
    style_dark(fig)
    fig.update_layout(yaxis2=dict(title="累積成本", overlaying="y", side="right", gridcolor=GRID))
    return fig
