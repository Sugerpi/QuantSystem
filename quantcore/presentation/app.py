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
    st.Page("pages/5_Portfolio_Cost.py", title="組合與成本"),
    st.Page("pages/8_Run_Lab.py", title="回測工作台"),
]

nav = st.navigation(_PAGES)
controls.render_sidebar()
nav.run()
