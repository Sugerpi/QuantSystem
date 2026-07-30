"""唯讀 artifact 載入層（§11.1 行程邊界；§5.1）。

presentation 永不 import 引擎：只讀 runs/、snapshots/ 的 parquet/JSON。
由 tests/test_presentation/test_architecture.py 的 AST 守護強制此邊界。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

__all__ = [
    "load_nav",
    "load_weights",
    "load_trades",
    "load_metrics",
    "load_manifest",
    "load_run_config",
]


def load_nav(run_dir: str | Path) -> pd.DataFrame:
    """nav.parquet（date, strategy_id, nav, turnover, cost）。"""
    return pd.read_parquet(Path(run_dir) / "nav.parquet")


def load_weights(run_dir: str | Path) -> pd.DataFrame:
    """weights.parquet（date, strategy_id, ticker, weight）。"""
    return pd.read_parquet(Path(run_dir) / "weights.parquet")


def load_trades(run_dir: str | Path) -> pd.DataFrame | None:
    """trades.parquet（缺 → None，舊 run「本次未儲存」）。"""
    p = Path(run_dir) / "trades.parquet"
    return pd.read_parquet(p) if p.exists() else None


def load_metrics(run_dir: str | Path) -> dict:
    """metrics.json（{strategy_id: {...}}）。"""
    return json.loads((Path(run_dir) / "metrics.json").read_text(encoding="utf-8"))


def load_manifest(run_dir: str | Path) -> dict:
    """manifest.json（identity/content_hashes/created_at）。"""
    return json.loads((Path(run_dir) / "manifest.json").read_text(encoding="utf-8"))


def load_run_config(run_dir: str | Path) -> dict:
    """該 run 的 config.yaml（dict）。"""
    return yaml.safe_load((Path(run_dir) / "config.yaml").read_text(encoding="utf-8"))
