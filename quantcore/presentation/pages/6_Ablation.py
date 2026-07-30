"""頁 6 消融比較（§11.2）：指標表、敏感度熱圖、配對 bootstrap CI。"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from quantcore.presentation import controls, readers

st.title("消融比較")
st.caption("提示：敏感度表用於檢驗穩健性，不是用來挑最好的一格。")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
comp = readers.load_comparison(run_dir)
if comp is None:
    st.info("本 run 無消融表（comparison.parquet）——請選一個消融 run。")
    st.stop()

st.subheader("指標表")
st.dataframe(comp, use_container_width=True)

st.subheader("敏感度熱圖（cell × 策略）")
metric = st.selectbox("指標", ["sharpe", "calmar", "max_drawdown", "annualized_return"])
piv = comp.pivot_table(index="cell_label", columns="strategy_id", values=metric)
st.plotly_chart(
    go.Figure(
        go.Heatmap(z=piv.values, x=list(piv.columns), y=list(piv.index), colorscale="Viridis")
    ).update_layout(height=420),
    use_container_width=True,
)

st.subheader("配對 bootstrap CI（full vs 消融版）")
bs = readers.load_bootstrap(run_dir)
if bs is None:
    st.info("本 run 無 bootstrap.parquet。")
else:
    st.dataframe(bs, use_container_width=True)
