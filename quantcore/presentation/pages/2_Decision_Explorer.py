"""頁 2 決策解剖（Decision Explorer，§11.2）：六層垂直瀑布。AC① 的 UI 出口。

資料源：readers.decision_layers（計畫 2a，逐層對應 decisions.parquet）。
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quantcore.presentation import controls, readers

st.title("決策解剖")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)
_strats = controls.selected_strategies(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
dec = readers.load_decisions(run_dir)
strat = (_strats or sorted(dec["strategy_id"].unique()))[0]
sub = dec[dec["strategy_id"] == strat].sort_values("decision_date")
if sub.empty:
    st.info(f"{strat} 無決策紀錄。")
    st.stop()

dates = list(sub["decision_date"])
idx = st.slider("決策日", 0, len(dates) - 1, len(dates) - 1)
ddate = dates[idx]
L = readers.decision_layers(run_dir, strat, ddate)
st.caption(f"{strat} · {pd.Timestamp(ddate).date()} · event={L.event} · exec={L.execution_date}")

# (a) 合格選單
st.subheader("(a) point-in-time 合格選單")
st.write(", ".join(L.eligible))

# (b) 動量分數長條圖，前 K 高亮
st.subheader("(b) 動量分數（前 K 高亮）")
if L.momentum_scores:
    items = sorted(L.momentum_scores.items(), key=lambda kv: kv[1], reverse=True)
    colors = ["#2ca02c" if k in (L.selected or []) else "#b0b0b0" for k, _ in items]
    bar = go.Figure(go.Bar(x=[k for k, _ in items], y=[v for _, v in items], marker_color=colors))
    bar.update_layout(height=300)
    st.plotly_chart(bar, use_container_width=True)
else:
    st.write("本策略無動量層。")

# (c) 絕對動量 pass/fail
st.subheader("(c) 絕對動量 pass/fail")
if L.absmom:
    st.dataframe(
        pd.DataFrame({"ticker": list(L.absmom), "pass": list(L.absmom.values())}),
        use_container_width=True,
    )
else:
    st.write("—")

# (d) GARCH σ̂（年化純量，含前一決策日對照）
st.subheader("(d) 波動 σ̂（年化，vs 上一決策日）")
prev = sub[sub["decision_date"] < ddate]
prev_sigma = (
    readers.decision_layers(run_dir, strat, prev["decision_date"].iloc[-1]).sigma_hat
    if not prev.empty
    else None
)
if L.sigma_hat:
    rows = [
        {"ticker": t, "σ̂": v, "σ̂(前)": (prev_sigma or {}).get(t)} for t, v in L.sigma_hat.items()
    ]
    st.dataframe(pd.DataFrame(rows).set_index("ticker"), use_container_width=True)
else:
    st.write("—")

# (e) 曝險公式展開
st.subheader("(e) 曝險：E = clip(σ*/σ̂_p)")
if L.sigma_p is not None:
    st.write(
        {
            "σ̂_p": L.sigma_p,
            "exposure_raw": L.exposure_raw,
            "exposure_applied": L.exposure_applied,
            "band_blocked": bool(L.band_blocked),
        }
    )
    if L.w_risky:
        st.caption("inverse-vol 權重 w_risky")
        st.dataframe(
            pd.DataFrame({"ticker": list(L.w_risky), "w_risky": list(L.w_risky.values())}),
            use_container_width=True,
        )
else:
    st.write("本策略無曝險層。")

# (f) 最終目標權重 vs 漂移後現況
st.subheader("(f) 目標權重（含 CASH）")
st.dataframe(
    pd.DataFrame(
        {"ticker": list(L.target_weights), "target": list(L.target_weights.values())}
    ).set_index("ticker"),
    use_container_width=True,
)
