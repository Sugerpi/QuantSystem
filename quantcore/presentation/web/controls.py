"""全域控制列狀態：query string → Controls（純函數，可獨立測）。

不 import 引擎（§2.2）。run 預設優先選有 strategies 的回測 run，比照舊
Streamlit controls 的 is_backtest_run 防呆——否則 nav 類頁面對缺 nav 的
vol_eval/ablation run 崩潰。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Controls:
    runs_root: Path
    run: str | None
    run_dir: Path | None
    strategies: list[str]
    available_runs: list[str]
    available_strategies: list[str]
    date_from: str | None
    date_to: str | None

    @property
    def query_suffix(self) -> str:
        parts: list[str] = []
        if self.run:
            parts.append(f"run={self.run}")
        if self.strategies:
            parts.append("strat=" + ",".join(self.strategies))
        if self.date_from:
            parts.append(f"from={self.date_from}")
        if self.date_to:
            parts.append(f"to={self.date_to}")
        return ("?" + "&".join(parts)) if parts else ""


def _resolve_run(requested: str | None, runs: list[dict]) -> dict | None:
    if not runs:
        return None
    by_name = {r["name"]: r for r in runs}
    if requested and requested in by_name:
        return by_name[requested]
    backtest = [r for r in runs if r.get("strategies")]
    return backtest[-1] if backtest else runs[-1]


def parse_controls(params: Mapping[str, str], runs_root: Path, runs: list[dict]) -> Controls:
    """由 query params + list_runs 結果組出 Controls。runs 為 readers.list_runs 輸出。"""
    names = [r["name"] for r in runs]
    chosen = _resolve_run(params.get("run"), runs)
    date_from = params.get("from") or None
    date_to = params.get("to") or None
    if chosen is None:
        return Controls(runs_root, None, None, [], names, [], date_from, date_to)
    available = list(chosen.get("strategies") or [])
    raw = params.get("strat")
    if raw:
        requested = [s for s in raw.split(",") if s]
        strategies = [s for s in requested if s in available] or available
    else:
        strategies = available
    return Controls(
        runs_root=runs_root,
        run=chosen["name"],
        run_dir=Path(chosen["path"]),
        strategies=strategies,
        available_runs=names,
        available_strategies=available,
        date_from=date_from,
        date_to=date_to,
    )
