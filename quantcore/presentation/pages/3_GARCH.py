"""頁 3 GARCH 檢視（§11.2）：參數軌跡、persistence、fallback、QLIKE/MZ-R²、殘差 QQ/ACF。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scipy import stats

from quantcore.presentation import controls, readers

st.title("GARCH 檢視")

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
dec = readers.load_decisions(run_dir)
strat = (_strats or sorted(dec["strategy_id"].unique()))[0]
sub = dec[(dec["strategy_id"] == strat)].sort_values("decision_date")

# 參數軌跡（ω,α,β,ν）+ persistence
st.subheader("GARCH 參數軌跡與 persistence")
rows = []
for _, r in sub.iterrows():
    gp = r["garch_params"]
    if not gp:
        continue
    for t, p in gp.items():
        if p:
            rows.append(
                {
                    "date": r["decision_date"],
                    "ticker": t,
                    **p,
                    "persistence": p["alpha"] + p["beta"],
                }
            )
if not rows:
    st.info("本策略/此 run 無 GARCH 參數（EWMA 或非波動目標策略）。")
else:
    pt = pd.DataFrame(rows)
    tick = st.selectbox("資產", sorted(pt["ticker"].unique()))
    tp = pt[pt["ticker"] == tick].sort_values("date")
    fig = go.Figure()
    for col in ("omega", "alpha", "beta", "nu", "persistence"):
        fig.add_trace(go.Scatter(x=tp["date"], y=tp[col], name=col, mode="lines"))
    fig.update_layout(height=360)
    st.plotly_chart(fig, use_container_width=True)

# fallback 頻率
st.subheader("GARCH fallback 頻率（vol_fell_back）")
fb = []
for _, r in sub.iterrows():
    d = r["vol_fell_back"] or {}
    for t, v in d.items():
        fb.append({"ticker": t, "fell_back": bool(v)})
if fb:
    fbdf = pd.DataFrame(fb).groupby("ticker")["fell_back"].mean().reset_index()
    st.plotly_chart(
        go.Figure(go.Bar(x=fbdf["ticker"], y=fbdf["fell_back"])).update_layout(height=280),
        use_container_width=True,
    )
else:
    st.write("—")

# QLIKE / MZ-R²（vol_eval）
st.subheader("QLIKE / MZ-R²（GARCH vs EWMA）")
ve = readers.load_vol_eval(_root / "vol_eval")
if ve is None:
    st.info("本次未儲存（無 runs/vol_eval/）。")
else:
    st.dataframe(ve, use_container_width=True)

# 殘差 QQ + ACF
st.subheader("標準化殘差 QQ / ACF")
resid = readers.load_residuals(run_dir)
if resid is None or resid.empty:
    st.info("本次未儲存（無 model_details/residuals）。")
else:
    r_strat = resid[resid["strategy_id"] == strat] if "strategy_id" in resid.columns else resid
    tks = sorted(r_strat["ticker"].unique())
    if tks:
        tk = st.selectbox("殘差資產", tks, key="resid_tk")
        s = r_strat[r_strat["ticker"] == tk]["std_resid"].dropna().to_numpy()
        n = len(s)
        if n > 1:
            theo = stats.norm.ppf((np.arange(1, n + 1) - 0.5) / n)
            qq = go.Figure(go.Scatter(x=theo, y=np.sort(s), mode="markers"))
            lim = [min(theo.min(), s.min()), max(theo.max(), s.max())]
            qq.add_trace(go.Scatter(x=lim, y=lim, mode="lines", name="y=x"))
            qq.update_layout(
                height=320,
                title="QQ（標準化殘差 vs 常態）",
                xaxis_title="理論分位",
                yaxis_title="樣本分位",
            )
            st.plotly_chart(qq, use_container_width=True)
            s0 = s - s.mean()
            denom = float(np.dot(s0, s0))
            lags = min(20, n - 1)
            acf = [float(np.dot(s0[:-k], s0[k:]) / denom) for k in range(1, lags + 1)]
            st.plotly_chart(
                go.Figure(go.Bar(x=list(range(1, lags + 1)), y=acf)).update_layout(
                    height=280, title="ACF（標準化殘差）", xaxis_title="lag"
                ),
                use_container_width=True,
            )
