"""頁 7 資料品質（§11.2）：快照 MANIFEST、跨源差異、總報酬驗證、overrides 清單。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from quantcore.presentation import controls, readers

st.title("資料品質")

_state = st.session_state
_root = controls.runs_root(_state)
_runs = controls.selected_runs(_state)

if not _runs:
    st.info("請在左側選擇至少一個 run。")
    st.stop()

run_dir = _root / _runs[0]
snap_dir = readers.snapshot_dir_for_run(run_dir)
if not snap_dir.exists():
    st.info(f"快照 {snap_dir} 不在本機（可能只有 hash 進版控）。")
    st.stop()

st.subheader("快照 MANIFEST")
st.json(readers.load_snapshot_manifest(snap_dir))

meta = readers.load_snapshot_metadata(snap_dir)
st.subheader("資料源")
st.json(meta.get("sources", {}))

st.subheader(f"跨源裁決 overrides（{len(meta.get('overrides', []))} 筆）")
ov = meta.get("overrides", [])
if ov:
    st.dataframe(pd.DataFrame(ov), use_container_width=True)
else:
    st.write("無 overrides。")

st.subheader("選單 tickers")
st.json(meta.get("tickers", {}))
