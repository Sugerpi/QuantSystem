"""QuantCore dashboard 入口（§11.1/§11.2）。st.navigation 多頁 + 全域控制列。

行程邊界（§2.2）：只讀 runs/、snapshots/。不 import 引擎。
"""

from __future__ import annotations

import streamlit as st

from quantcore.presentation import controls

st.set_page_config(page_title="QuantCore Dashboard", layout="wide")

_PAGES = [
    st.Page("pages/1_Overview.py", title="總覽", default=True),
    st.Page("pages/2_Decision_Explorer.py", title="決策解剖"),
    st.Page("pages/3_GARCH.py", title="GARCH"),
    st.Page("pages/4_Correlation.py", title="相關結構"),
    st.Page("pages/5_Portfolio_Cost.py", title="組合與成本"),
    st.Page("pages/6_Ablation.py", title="消融"),
    st.Page("pages/7_Data_Quality.py", title="資料品質"),
    st.Page("pages/8_Run_Lab.py", title="回測工作台"),
    st.Page("pages/9_Price_Trades.py", title="價格與交易"),
]

nav = st.navigation(_PAGES)
controls.render_sidebar()
nav.run()
