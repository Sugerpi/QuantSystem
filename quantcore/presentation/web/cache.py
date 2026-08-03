"""讀檔快取：以 (路徑, mtime, loader) 為鍵包 readers。同路徑 mtime 變即失效重載。

localhost 單人、runs/ 為不可變產物，此快取避免切頁重讀 parquet。
_LOCK 序列化讀寫，保護 FastAPI threadpool 內的並發請求。
鍵含 loader 身份：同一路徑（如 run_dir）可被不同 loader 讀（load_correlation vs
load_comparison），少了 loader 會鍵碰撞、把 A 的結果當 B 供出（靜默供錯資料）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")

_CACHE: dict[tuple[str, float, str], object] = {}
_LOCK = threading.Lock()


def read(path: Path, loader: Callable[[Path], T]) -> T:
    loader_id = getattr(loader, "__qualname__", repr(loader))
    key = (str(path), path.stat().st_mtime, loader_id)
    with _LOCK:
        if key not in _CACHE:
            # 只汰換同路徑但 mtime 已變的舊項（保留同 mtime、不同 loader 的有效快取）。
            for stale in [k for k in _CACHE if k[0] == key[0] and k[1] != key[1]]:
                del _CACHE[stale]
            _CACHE[key] = loader(path)
        return _CACHE[key]  # type: ignore[return-value]


def clear() -> None:
    with _LOCK:
        _CACHE.clear()
