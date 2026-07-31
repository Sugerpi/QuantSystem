"""讀檔快取：以 (路徑, mtime) 為鍵包 readers。同路徑 mtime 變即失效重載。

localhost 單人、runs/ 為不可變產物，此快取避免切頁重讀 parquet。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")

_CACHE: dict[tuple[str, float], object] = {}


def read(path: Path, loader: Callable[[Path], T]) -> T:
    key = (str(path), path.stat().st_mtime)
    if key not in _CACHE:
        for stale in [k for k in _CACHE if k[0] == key[0]]:
            del _CACHE[stale]
        _CACHE[key] = loader(path)
    return _CACHE[key]  # type: ignore[return-value]


def clear() -> None:
    _CACHE.clear()
