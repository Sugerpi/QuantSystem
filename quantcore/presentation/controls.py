"""全域控制列 + 跨頁選擇存取（§11.2 全域控制列）。

accessors 收一個 mapping（st.session_state 或 dict），純函數、可獨立測。
render_sidebar 由 app.py 於每頁前呼叫，把選擇寫入 session_state。
不 import 引擎（§2.2）。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import streamlit as st

from quantcore.presentation import readers


def runs_root(state: Mapping) -> Path:
    """runs 根：session_state → 環境變數 QUANTCORE_RUNS_ROOT → 'runs'。"""
    val = state.get("runs_root") or os.environ.get("QUANTCORE_RUNS_ROOT") or "runs"
    return Path(val)


def selected_runs(state: Mapping) -> list[str]:
    return list(state.get("selected_runs") or [])


def selected_strategies(state: Mapping) -> list[str]:
    return list(state.get("selected_strategies") or [])


def date_range(state: Mapping) -> tuple:
    return tuple(state.get("date_range") or (None, None))


def render_sidebar() -> None:
    """側欄全域控制列：run 多選、策略多選、日期範圍。寫入 st.session_state。"""
    st.sidebar.title("QuantCore")
    root = runs_root(st.session_state)
    runs = readers.list_runs(root)
    if not runs:
        st.sidebar.warning(f"{root} 下無 run")
        return
    names = [r["name"] for r in runs]
    default = st.session_state.get("selected_runs") or names[-1:]
    st.sidebar.multiselect(
        "Run",
        names,
        default=default,
        key="selected_runs",
        help="目前各頁顯示第一個選中的 run；多 run 疊圖比較於後續增量（計畫 2b-2/後續）。",
    )

    strat_union = sorted(
        {s for r in runs if r["name"] in selected_runs(st.session_state) for s in r["strategies"]}
    )
    if strat_union:
        st.sidebar.multiselect("策略", strat_union, default=strat_union, key="selected_strategies")
