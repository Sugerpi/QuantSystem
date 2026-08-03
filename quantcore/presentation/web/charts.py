"""Plotly 圖表：深色 Bloomberg 風統一樣式 + 可嵌入片段。

不 import 引擎（§2.2）。顏色 token 集中此處，供各頁圖表沿用。
"""

from __future__ import annotations

import numpy as np
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


def momentum_bar(scores: dict[str, float], selected: list[str]) -> go.Figure:
    """動量分數長條，selected（前 K）以綠色高亮、其餘灰。"""
    items = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    sel = set(selected or [])
    colors = [UP if k in sel else "#6a6a62" for k, _ in items]
    fig = go.Figure(go.Bar(x=[k for k, _ in items], y=[v for _, v in items], marker_color=colors))
    return style_dark(fig)


def heatmap(z, x, y, *, zmin=None, zmax=None, colorscale="Viridis") -> go.Figure:
    """通用熱圖（相關矩陣 / 敏感度）。"""
    fig = go.Figure(
        go.Heatmap(z=z, x=list(x), y=list(y), zmin=zmin, zmax=zmax, colorscale=colorscale)
    )
    return style_dark(fig)


def line_series(named: dict[str, tuple]) -> go.Figure:
    """多條命名折線；named[name] = (x, y)。"""
    fig = go.Figure()
    for name, (xs, ys) in named.items():
        fig.add_trace(go.Scatter(x=list(xs), y=list(ys), name=name, mode="lines"))
    return style_dark(fig)


def resid_qq(samples: np.ndarray) -> go.Figure:
    """標準化殘差 QQ（vs 常態）+ y=x 對角。"""
    from scipy import stats

    s = np.sort(np.asarray(samples, dtype=float))
    n = len(s)
    theo = stats.norm.ppf((np.arange(1, n + 1) - 0.5) / n)
    fig = go.Figure(go.Scatter(x=theo, y=s, mode="markers", name="樣本"))
    lim = [float(min(theo.min(), s.min())), float(max(theo.max(), s.max()))]
    fig.add_trace(go.Scatter(x=lim, y=lim, mode="lines", name="y=x"))
    fig.update_layout(xaxis_title="理論分位", yaxis_title="樣本分位")
    return style_dark(fig)


def resid_acf(samples: np.ndarray, lags: int = 20) -> go.Figure:
    """標準化殘差 ACF 長條。"""
    s = np.asarray(samples, dtype=float)
    s0 = s - s.mean()
    denom = float(np.dot(s0, s0)) or 1.0
    k = min(lags, len(s0) - 1)
    acf = [float(np.dot(s0[:-i], s0[i:]) / denom) for i in range(1, k + 1)]
    fig = go.Figure(go.Bar(x=list(range(1, k + 1)), y=acf))
    fig.update_layout(xaxis_title="lag")
    return style_dark(fig)


def price_with_trades(price, trades_tk, ticker: str) -> go.Figure:
    """單一標的 adj_close 折線 + 買賣進出場標記（marker customdata=execution_date ISO）。

    price 為該檔 adj_close Series（index=date）或 None；trades_tk 為該檔交易
    （execution_date/side/fill_price）。有 price 時標記 y 取當日 adj_close
    （reindex，缺值 NaN 不拋錯）；否則取 fill_price。customdata 供點擊跳決策解剖。
    """
    fig = go.Figure()
    has_price = price is not None and len(price) > 0
    if has_price:
        fig.add_trace(
            go.Scatter(x=price.index, y=price.to_numpy(), name=f"{ticker} price", mode="lines")
        )
    for side, sym, col in (("buy", "triangle-up", UP), ("sell", "triangle-down", DOWN)):
        ts = trades_tk[trades_tk["side"] == side]
        if ts.empty:
            continue
        y = (
            price.reindex(ts["execution_date"]).to_numpy()
            if has_price
            else ts["fill_price"].to_numpy()
        )
        cd = [pd.Timestamp(d).date().isoformat() for d in ts["execution_date"]]
        fig.add_trace(
            go.Scatter(
                x=ts["execution_date"],
                y=y,
                mode="markers",
                name=f"{ticker} {side}",
                marker=dict(symbol=sym, size=10, color=col),
                customdata=cd,
            )
        )
    return style_dark(fig)
