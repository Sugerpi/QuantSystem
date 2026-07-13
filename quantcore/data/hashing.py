"""決定性 canonical hash（設計文件 §3.2）。

MANIFEST 的 content SHA-256 由資料的 canonical 表示計算，而非 parquet 位元組，
因 parquet 內嵌套件版本/時間戳，位元組不決定性。canonical_hash 逐欄雜湊
dtype 標籤 + 原始值，跨 pandas/pyarrow 版本與 OS 皆決定性。
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd


def canonicalize(df: pd.DataFrame, sort_cols: list[str]) -> pd.DataFrame:
    """固定列序、欄序、重設索引。hash 前一律先過此函數。"""
    return df.sort_values(sort_cols, kind="stable").reset_index(drop=True)


def canonical_hash(df: pd.DataFrame) -> str:
    """對 canonicalize 後的 DataFrame 計算決定性 SHA-256。"""
    h = hashlib.sha256()
    for col in df.columns:
        h.update(str(col).encode("utf-8"))
        s = df[col]
        kind = s.dtype.kind
        h.update(kind.encode("ascii"))
        if kind == "f":
            h.update(np.ascontiguousarray(s.to_numpy(dtype="float64")).tobytes())
        elif kind in ("i", "u"):
            h.update(np.ascontiguousarray(s.to_numpy(dtype="int64")).tobytes())
        elif kind == "b":
            h.update(np.ascontiguousarray(s.to_numpy(dtype="int8")).tobytes())
        elif kind == "M":
            arr = s.to_numpy(dtype="datetime64[ns]").astype("int64")
            h.update(np.ascontiguousarray(arr).tobytes())
        else:  # object / string
            for v in s.tolist():
                b = (
                    b"\x00NULL"
                    if v is None or (isinstance(v, float) and np.isnan(v))
                    else str(v).encode("utf-8")
                )
                h.update(len(b).to_bytes(8, "little"))
                h.update(b)
    return h.hexdigest()


def config_hash(config_dict: dict) -> str:
    """對 config（已轉為 JSON-safe dict）計算決定性 hash。"""
    payload = json.dumps(config_dict, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def combined_hash(parts: list[str]) -> str:
    """把多個 hex hash 合併成單一 hash（順序固定）。"""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("ascii"))
    return h.hexdigest()


def snapshot_id(build_date: pd.Timestamp, combined: str) -> str:
    """快照目錄名：{YYYY-MM-DD}_{前 6 hex}。"""
    return f"{build_date:%Y-%m-%d}_{combined[:6]}"
