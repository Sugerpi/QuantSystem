"""頁 5 組合與成本（§11.2）：權重堆疊面積、曝險軌跡+帶事件、換手、累積成本。"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from quantcore.presentation import controls, readers

st.title("組合與成本")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)
_strats = controls.selected_strategies(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
nav = readers.load_nav(run_dir)
weights = readers.load_weights(run_dir)
decisions = readers.load_decisions(run_dir)
strat = (_strats or sorted(nav["strategy_id"].unique()))[0]

# 權重堆疊面積（含現金）
st.subheader(f"權重堆疊（{strat}，含現金）")
w = weights[weights["strategy_id"] == strat]
wide = w.pivot_table(index="date", columns="ticker", values="weight", fill_value=0.0).sort_index()
area = go.Figure()
for col in wide.columns:
    area.add_trace(go.Scatter(x=wide.index, y=wide[col], name=col, stackgroup="w", mode="lines"))
area.update_layout(height=380)
st.plotly_chart(area, use_container_width=True)

# 曝險軌跡 + 帶事件標記（band_blocked）
st.subheader("曝險軌跡與帶事件")
_mask = (decisions["strategy_id"] == strat) & decisions["exposure_applied"].notna()
d = decisions[_mask].sort_values("decision_date")
exp = go.Figure()
exp.add_trace(go.Scatter(x=d["decision_date"], y=d["exposure_applied"], name="E(t)", mode="lines"))
blocked = d[d["band_blocked"] == True]  # noqa: E712
if not blocked.empty:
    exp.add_trace(
        go.Scatter(
            x=blocked["decision_date"],
            y=blocked["exposure_applied"],
            name="band-blocked",
            mode="markers",
            marker_symbol="x",
        )
    )
exp.update_layout(height=300, yaxis_title="E(t)")
st.plotly_chart(exp, use_container_width=True)

# 換手 + 累積成本
st.subheader("每次再平衡換手率與累積成本")
n = nav[nav["strategy_id"] == strat].sort_values("date")
tc = go.Figure()
tc.add_trace(go.Bar(x=n["date"], y=n["turnover"], name="turnover"))
tc.add_trace(
    go.Scatter(x=n["date"], y=n["cost"].cumsum(), name="累積成本", yaxis="y2", mode="lines")
)
tc.update_layout(
    height=320,
    yaxis=dict(title="turnover"),
    yaxis2=dict(title="累積成本", overlaying="y", side="right"),
)
st.plotly_chart(tc, use_container_width=True)
