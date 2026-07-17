"""run 目錄、manifest、決定性寫檔（規格 §7.1；INV-6）。

manifest 刻意切成 identity / created_at 兩塊（設計文件 §5.2）：
INV-6 是「(config, snapshot_hash, git_commit) 三元組決定**輸出**」，時間戳本就會變。
把邊界寫在資料結構上，而非藏在測試的 exclude 清單裡。
"""

from __future__ import annotations

import json
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pandas as pd
import yaml

try:
    QC_VERSION = version("quantcore")
except PackageNotFoundError:  # pragma: no cover
    QC_VERSION = "unknown"


def git_commit() -> str:
    """HEAD 的 sha；工作區有未提交改動則加 -dirty 後綴。

    不加 dirty 標記的話，INV-6 的三元組會撒謊——同一個 sha 可能對應不同的程式碼。
    """
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return f"{sha}-dirty" if dirty else sha


def create_run_dir(out_root: str | Path, label: str, now: pd.Timestamp) -> Path:
    """runs/YYYY-MM-DD_HHMM_<label>/。

    與 §7.1 範例（`..._full_default`）不同：一個 run 涵蓋多策略，
    目錄名放單一策略名無意義（設計文件 §5.1）。
    """
    d = Path(out_root) / f"{now:%Y-%m-%d_%H%M}_{label}"
    d.mkdir(parents=True, exist_ok=False)
    return d


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    """決定性寫檔：固定欄序與列序（沿用 Phase 1 達成 AC-4 的作法）。"""
    df.to_parquet(path, index=False)


def write_artifacts(
    run_dir: Path,
    cfg_dict: dict,
    identity: dict,
    created_at: str,
    nav: pd.DataFrame,
    weights: pd.DataFrame,
    decisions: pd.DataFrame,
    metrics: dict,
) -> None:
    """寫出 §7.1 的 Phase 2 子集（無 model_details/——Phase 2 無模型）。"""
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg_dict, sort_keys=True, allow_unicode=True), encoding="utf-8"
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {"identity": identity, "created_at": created_at},
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_parquet(nav, run_dir / "nav.parquet")
    _write_parquet(weights, run_dir / "weights.parquet")
    _write_parquet(decisions, run_dir / "decisions.parquet")
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
