"""唯讀 artifact 載入層（§11.1 行程邊界；§5.1）。

presentation 永不 import 引擎：只讀 runs/、snapshots/ 的 parquet/JSON。
由 tests/test_presentation/test_architecture.py 的 AST 守護強制此邊界。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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
    "load_decisions",
    "DecisionLayers",
    "decision_layers",
    "load_correlation",
    "load_residuals",
    "correlation_matrix_at",
    "load_adj_close_panel",
    "load_snapshot_metadata",
    "load_snapshot_manifest",
    "list_runs",
]

_JSON_COLS = (
    "target_weights",
    "eligible",
    "selected",
    "momentum_scores",
    "absmom",
    "sigma_hat",
    "w_risky",
    "vol_fell_back",
    "garch_params",
)


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


def _parse_json_cell(v):
    """JSON 字串 → Python 物件；None/NA → None（Phase 2/3 空欄慣例）。"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return json.loads(v)


def load_decisions(run_dir: str | Path) -> pd.DataFrame:
    """decisions.parquet，JSON 字串欄就地解析為 Python 物件（dict/list/None）。

    band_blocked/corr_fell_back 維持 nullable boolean。回傳供 Decision Explorer 與頁面消費。
    """
    dec = pd.read_parquet(Path(run_dir) / "decisions.parquet")
    for c in _JSON_COLS:
        if c in dec.columns:
            dec[c] = dec[c].map(_parse_json_cell)
    return dec


def load_correlation(run_dir: str | Path) -> pd.DataFrame | None:
    """model_details/correlation.parquet（長格式）。缺 → None（本次未儲存）。"""
    p = Path(run_dir) / "model_details" / "correlation.parquet"
    return pd.read_parquet(p) if p.exists() else None


def load_residuals(run_dir: str | Path) -> pd.DataFrame | None:
    """model_details/residuals.parquet。缺 → None。"""
    p = Path(run_dir) / "model_details" / "residuals.parquet"
    return pd.read_parquet(p) if p.exists() else None


def correlation_matrix_at(corr: pd.DataFrame, strategy_id: str, decision_date) -> pd.DataFrame:
    """長格式 → 某策略某決策日的方陣相關矩陣（頁 4 熱圖）。"""
    ddate = pd.Timestamp(decision_date)
    sub = corr[(corr["strategy_id"] == strategy_id) & (corr["decision_date"] == ddate)]
    return sub.pivot(index="ticker_i", columns="ticker_j", values="corr")


def load_adj_close_panel(snapshot_dir: str | Path) -> pd.DataFrame:
    """快照 prices.parquet → date×ticker 的 adj_close 面板（頁 9 價格折線）。"""
    prices = pd.read_parquet(Path(snapshot_dir) / "prices.parquet")
    panel = prices.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    panel.index.name = "date"
    return panel


def load_snapshot_metadata(snapshot_dir: str | Path) -> dict:
    """快照 metadata.json（overrides 裁決、跨源差異；頁 7）。"""
    return json.loads((Path(snapshot_dir) / "metadata.json").read_text(encoding="utf-8"))


def load_snapshot_manifest(snapshot_dir: str | Path) -> dict:
    """快照 MANIFEST.json（頁 7）。"""
    return json.loads((Path(snapshot_dir) / "MANIFEST.json").read_text(encoding="utf-8"))


def list_runs(runs_root: str | Path) -> list[dict]:
    """掃 runs_root 下含 manifest.json 的 run 目錄，回 [{name, path, created_at, snapshot_id,
    git_commit, strategies}]，供全域控制列 run 選擇器。非 run 目錄（無 manifest）略過。"""
    root = Path(runs_root)
    out = []
    for d in sorted(root.iterdir()):
        mf = d / "manifest.json"
        if not (d.is_dir() and mf.exists()):
            continue
        manifest = json.loads(mf.read_text(encoding="utf-8"))
        ident = manifest.get("identity", {})
        metrics = load_metrics(d) if (d / "metrics.json").exists() else {}
        out.append(
            {
                "name": d.name,
                "path": str(d),
                "created_at": manifest.get("created_at"),
                "snapshot_id": ident.get("snapshot_id"),
                "git_commit": ident.get("git_commit"),
                "strategies": sorted(metrics.keys()),
            }
        )
    return out


@dataclass(frozen=True)
class DecisionLayers:
    """Decision Explorer 六層（§11.2 頁 2；§2 對照表）。純資料，供頁面渲染。"""

    strategy_id: str
    decision_date: pd.Timestamp
    execution_date: pd.Timestamp | None
    event: str
    eligible: list[str]  # (a)
    momentum_scores: dict[str, float] | None  # (b)
    selected: list[str]  # (b) 前 K
    absmom: dict[str, bool] | None  # (c)
    sigma_hat: dict[str, float] | None  # (d) 年化純量
    w_risky: dict[str, float] | None  # (e)
    sigma_p: float | None  # (e)
    exposure_raw: float | None  # (e)
    exposure_applied: float | None  # (e)
    band_blocked: bool | None  # (e)
    target_weights: dict[str, float]  # (f) 含 CASH


def decision_layers(run_dir: str | Path, strategy_id: str, decision_date) -> DecisionLayers | None:
    """抽取某策略某決策日的六層。查無回 None。

    這是 AC① 的自動化出口：頁面渲染此結構，人工手查（Plan 2b）比對 decisions.parquet。
    """
    dec = load_decisions(run_dir)
    ddate = pd.Timestamp(decision_date)
    m = (dec["strategy_id"] == strategy_id) & (dec["decision_date"] == ddate)
    if not m.any():
        return None
    r = dec[m].iloc[0]

    def f(v):
        return None if pd.isna(v) else float(v)

    def b(v):
        return None if pd.isna(v) else bool(v)

    return DecisionLayers(
        strategy_id=strategy_id,
        decision_date=ddate,
        execution_date=None if pd.isna(r["execution_date"]) else r["execution_date"],
        event=r["event"],
        eligible=r["eligible"],
        momentum_scores=r["momentum_scores"],
        selected=r["selected"],
        absmom=r["absmom"],
        sigma_hat=r["sigma_hat"],
        w_risky=r["w_risky"],
        sigma_p=f(r["sigma_p"]),
        exposure_raw=f(r["exposure_raw"]),
        exposure_applied=f(r["exposure_applied"]),
        band_blocked=b(r["band_blocked"]),
        target_weights=r["target_weights"],
    )
