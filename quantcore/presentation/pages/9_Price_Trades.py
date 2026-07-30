"""頁 9 價格與交易（新增，§0/§3.5）：每檔 adj_close 折線 + 買賣標記 + blotter 明細表。"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from quantcore.presentation import controls, readers

st.title("價格與交易")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)
_strats = controls.selected_strategies(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
trades = readers.load_trades(run_dir)
if trades is None:
    st.info("本次未儲存（無 trades.parquet）。")
    st.stop()

strat = (_strats or sorted(trades["strategy_id"].unique()))[0]
tr = trades[trades["strategy_id"] == strat]
snap_dir = readers.snapshot_dir_for_run(run_dir)
panel = readers.load_adj_close_panel(snap_dir) if snap_dir.exists() else None

st.subheader("價格與進出場")
tickers = sorted(tr["ticker"].unique())
picks = st.multiselect("標的", tickers, default=tickers[:1])
fig = go.Figure()
for tk in picks:
    if panel is not None and tk in panel.columns:
        fig.add_trace(go.Scatter(x=panel.index, y=panel[tk], name=f"{tk} price", mode="lines"))
    t = tr[tr["ticker"] == tk]
    for side, sym, col in (("buy", "triangle-up", "#2ca02c"), ("sell", "triangle-down", "#d62728")):
        ts = t[t["side"] == side]
        if panel is not None and tk in panel.columns:
            # reindex（非 .loc）：合成/歷史快照日曆可能與 panel 索引不完全對齊，
            # 缺值以 NaN 呈現而非拋 KeyError。
            y = panel[tk].reindex(ts["execution_date"]).to_numpy()
        else:
            y = ts["fill_price"].to_numpy()
        fig.add_trace(
            go.Scatter(
                x=ts["execution_date"],
                y=y,
                mode="markers",
                name=f"{tk} {side}",
                marker=dict(symbol=sym, size=9, color=col),
            )
        )
fig.update_layout(height=460)
st.plotly_chart(fig, use_container_width=True)

st.subheader("交易明細（blotter）")
st.dataframe(tr.sort_values("execution_date"), use_container_width=True)
