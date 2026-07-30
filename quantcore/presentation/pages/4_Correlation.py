"""頁 4 相關結構（§11.2）：相關矩陣熱圖 + 時間滑桿、資產對時間序列、DCC vs EWMA 疊圖。"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from quantcore.presentation import controls, readers

st.title("相關結構")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)
_strats = controls.selected_strategies(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
corr = readers.load_correlation(run_dir)
if corr is None or corr.empty:
    st.info("本次未儲存（無 model_details/correlation；僅 full/full_erc 有相關矩陣）。")
    st.stop()

strat = (_strats or sorted(corr["strategy_id"].unique()))[0]
csub = corr[corr["strategy_id"] == strat]
dates = sorted(csub["decision_date"].unique())

# 熱圖 + 時間滑桿
st.subheader("相關矩陣熱圖")
i = st.slider("決策日", 0, len(dates) - 1, len(dates) - 1)
mat = readers.correlation_matrix_at(csub, strat, dates[i])
st.plotly_chart(
    go.Figure(
        go.Heatmap(
            z=mat.values, x=list(mat.columns), y=list(mat.index), zmin=-1, zmax=1, colorscale="RdBu"
        )
    ).update_layout(height=460),
    use_container_width=True,
)

# 任選資產對時間序列
st.subheader("資產對相關時間序列")
tickers = sorted(mat.index)
c1, c2 = st.columns(2)
ti = c1.selectbox("資產 i", tickers, index=0)
tj = c2.selectbox("資產 j", tickers, index=min(1, len(tickers) - 1))
pair = csub[(csub["ticker_i"] == ti) & (csub["ticker_j"] == tj)].sort_values("decision_date")
ts = go.Figure(go.Scatter(x=pair["decision_date"], y=pair["corr"], mode="lines", name=f"{ti}-{tj}"))

# DCC vs EWMA 疊圖：頁內選第二個 run
st.subheader("疊圖：另一個 run（DCC vs EWMA）")
others = [r["name"] for r in readers.list_runs(_root) if r["name"] != _runs[0]]
if others:
    r2 = st.selectbox("第二個 run", ["（不疊）"] + others)
    if r2 != "（不疊）":
        c2df = readers.load_correlation(_root / r2)
        if c2df is not None and not c2df.empty:
            s2 = (_strats or sorted(c2df["strategy_id"].unique()))[0]
            p2 = c2df[
                (c2df["strategy_id"] == s2) & (c2df["ticker_i"] == ti) & (c2df["ticker_j"] == tj)
            ].sort_values("decision_date")
            ts.add_trace(
                go.Scatter(x=p2["decision_date"], y=p2["corr"], mode="lines", name=f"{r2}")
            )
ts.update_layout(height=320, yaxis_title="corr")
st.plotly_chart(ts, use_container_width=True)
