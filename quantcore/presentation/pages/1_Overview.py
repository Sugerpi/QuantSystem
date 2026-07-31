"""頁 1 總覽：NAV 對數疊圖、指標表、drawdown、曝險 E(t)、子期間表（§11.2）。"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quantcore.presentation import controls, readers

st.title("總覽")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)
_strats = controls.selected_strategies(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
if not readers.is_backtest_run(run_dir):
    st.info(f"{_runs[0]} 非回測 run（無 nav/decisions）——請選 canonical/backtest run。")
    st.stop()
nav = readers.load_nav(run_dir)
metrics = readers.load_metrics(run_dir)
decisions = readers.load_decisions(run_dir)
shown = _strats or sorted(nav["strategy_id"].unique())

# NAV 對數疊圖
fig = go.Figure()
for sid in shown:
    sub = nav[nav["strategy_id"] == sid].sort_values("date")
    fig.add_trace(go.Scatter(x=sub["date"], y=sub["nav"], name=sid, mode="lines"))
fig.update_yaxes(type="log", title="NAV（對數）")
fig.update_layout(title="NAV 疊圖", height=420)
st.plotly_chart(fig, use_container_width=True)

# 指標表
rows = [
    {
        "strategy": s,
        **{
            k: metrics[s][k]
            for k in (
                "annualized_return",
                "sharpe",
                "sortino",
                "max_drawdown",
                "calmar",
                "annualized_turnover",
                "average_exposure",
            )
        },
    }
    for s in shown
    if s in metrics
]
st.subheader("指標")
st.dataframe(pd.DataFrame(rows).set_index("strategy"), use_container_width=True)

# Drawdown
st.subheader("回撤")
dd = go.Figure()
for sid in shown:
    sub = nav[nav["strategy_id"] == sid].sort_values("date")
    cummax = sub["nav"].cummax()
    dd.add_trace(go.Scatter(x=sub["date"], y=sub["nav"] / cummax - 1.0, name=sid, mode="lines"))
dd.update_layout(height=300, yaxis_title="drawdown")
st.plotly_chart(dd, use_container_width=True)

# 曝險 E(t)（decisions.exposure_applied）
st.subheader("曝險 E(t)")
et = go.Figure()
for sid in shown:
    sub = decisions[(decisions["strategy_id"] == sid) & decisions["exposure_applied"].notna()]
    if not sub.empty:
        sub = sub.sort_values("decision_date")
        et.add_trace(go.Scatter(x=sub["decision_date"], y=sub["exposure_applied"], name=sid))
et.update_layout(height=300, yaxis_title="E(t)")
st.plotly_chart(et, use_container_width=True)

# 子期間表（第一個選中策略）
if shown and shown[0] in metrics and metrics[shown[0]].get("subperiods"):
    st.subheader(f"子期間績效（{shown[0]}）")
    st.dataframe(pd.DataFrame(metrics[shown[0]]["subperiods"]), use_container_width=True)
