"""run 目錄、manifest、決定性寫檔（規格 §7.1；INV-6）。

manifest 刻意切成 identity / created_at 兩塊（設計文件 §5.2）：
INV-6 是「(config, snapshot_hash, git_commit) 三元組決定**輸出**」，時間戳本就會變。
把邊界寫在資料結構上，而非藏在測試的 exclude 清單裡。
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pandas as pd
import yaml

from quantcore.data.hashing import canonical_hash, canonicalize

try:
    QC_VERSION = version("quantcore")
except PackageNotFoundError:  # pragma: no cover
    QC_VERSION = "unknown"


def _json_safe(obj):
    """把非有限浮點（NaN/inf）換成 None：標準 JSON 無這些字面值，presentation 層
    （§11）以嚴格 parser 讀取，`NaN` 會被拒。metrics 的比率在無定義時（如無回撤的
    Calmar）本就該是 null。"""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _frame_content_hash(df: pd.DataFrame, sort_cols: list[str]) -> str:
    """內容 hash（沿用 Phase 1 canonical_hash，設計文件 §5.3）。

    對 canonicalize 後的 DataFrame 內容取 hash，與 parquet 位元編碼無關，故 INV-6
    比對此 hash 比比對 parquet 位元組穩健——pyarrow/pandas 升級不會誤觸紅燈。
    canonical_hash 不支援 nullable 擴充型別（見其 docstring），decisions 的
    band_blocked 為 nullable boolean，故先把擴充型別欄轉 object 交 object 分支。
    """
    safe = df.copy()
    for c in safe.columns:
        if pd.api.types.is_extension_array_dtype(safe[c].dtype):
            safe[c] = safe[c].astype(object).where(safe[c].notna(), None)
    return canonical_hash(canonicalize(safe, sort_cols))


def _content_hashes(
    nav: pd.DataFrame,
    weights: pd.DataFrame,
    decisions: pd.DataFrame,
    trades: pd.DataFrame,
    metrics: dict,
) -> dict:
    """輸出檔的內容 hash，供 INV-6 以內容驗證可重現性。

    model_details/*（相關矩陣、殘差）為深掘診斷、不進 identity 合約（設計計畫 §設計決定）。
    """
    return {
        "nav.parquet": _frame_content_hash(nav, ["strategy_id", "date"]),
        "weights.parquet": _frame_content_hash(weights, ["strategy_id", "date", "ticker"]),
        "decisions.parquet": _frame_content_hash(decisions, ["strategy_id", "decision_date"])
        if not decisions.empty
        else hashlib.sha256(b"").hexdigest(),
        "trades.parquet": _frame_content_hash(trades, ["strategy_id", "execution_date", "ticker"])
        if not trades.empty
        else hashlib.sha256(b"").hexdigest(),
        "metrics.json": hashlib.sha256(
            json.dumps(_json_safe(metrics), sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }


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
    """原樣寫出 df 的欄序與列序，不額外排序。

    決定性靠呼叫端保證：runner 組 df 時列序本就固定（依 strategy_ids、
    交易日序列逐筆疊代），這裡排序反而多餘，故不做。若未來呼叫端改用
    不保序的來源（如 dict 迭代、集合運算），需在呼叫端補上排序，而非
    在此處靜默兜底。
    """
    df.to_parquet(path, index=False)


def write_artifacts(
    run_dir: Path,
    cfg_dict: dict,
    identity: dict,
    created_at: str,
    nav: pd.DataFrame,
    weights: pd.DataFrame,
    decisions: pd.DataFrame,
    trades: pd.DataFrame,
    correlations: pd.DataFrame,
    residuals: pd.DataFrame,
    metrics: dict,
) -> None:
    """寫出 §7.1 全量 artifacts：nav/weights/decisions/trades + model_details/（有模型
    診斷資料時才建立，設計文件 §設計決定）。

    manifest 三塊（設計文件 §5.2）：identity 為輸入三元組、content_hashes 為輸出
    內容指紋（與 parquet 位元編碼無關）、created_at 為時間戳。INV-6 比對 content_hashes
    使可重現性不受 pyarrow 版本影響。
    """
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg_dict, sort_keys=True, allow_unicode=True), encoding="utf-8"
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "identity": identity,
                "content_hashes": _content_hashes(nav, weights, decisions, trades, metrics),
                "created_at": created_at,
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_parquet(nav, run_dir / "nav.parquet")
    _write_parquet(weights, run_dir / "weights.parquet")
    _write_parquet(decisions, run_dir / "decisions.parquet")
    _write_parquet(trades, run_dir / "trades.parquet")
    if not correlations.empty or not residuals.empty:
        md = run_dir / "model_details"
        md.mkdir(exist_ok=True)
        if not correlations.empty:
            _write_parquet(correlations, md / "correlation.parquet")
        if not residuals.empty:
            _write_parquet(residuals, md / "residuals.parquet")
    (run_dir / "metrics.json").write_text(
        json.dumps(_json_safe(metrics), indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
